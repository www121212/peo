"""Harmonogramownik EV i zarządzanie sesjami ładowania dla PEO.

Moduł implementuje:
- EVScheduler: obliczanie optymalnych harmonogramów ładowania (single/multi-vehicle)
- ChargingSessionManager: zarządzanie sesjami ładowania (start/stop, monitoring SoC)

Strategie ładowania:
- CHEAPEST ("najtańsze_okna"): minimalizacja kosztu bez ograniczenia czasowego
- READY_BY ("gotowy_do_godziny"): naładowany do docelowego SoC przed deadline
- PV_ONLY ("tylko_nadwyżka_PV"): ładowanie wyłącznie z nadwyżki PV
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Optional

from .charger_adapters import ChargerAdapter
from .const import (
    FAILSAFE_TIMEOUT,
    SOC_CHECK_INTERVAL,
)
from .enums import ChargingStrategy
from .models import (
    ChargerConfig,
    ChargingConstraints,
    ChargingSchedule,
    ChargingSession,
    HourlyCost,
    TimeWindow,
    VehicleChargerPair,
    VehicleConfig,
)
from .schedule_engine import (
    ScheduleDemand,
    ScheduleEngine,
    ScheduleResult,
    TimeSlot,
)

_LOGGER = logging.getLogger(__name__)

# Timeout for SoC unavailability before pausing automation (seconds)
SOC_UNAVAILABLE_TIMEOUT = 300  # 5 minutes


@dataclass
class ActiveSession:
    """Aktywna sesja ładowania — mutable state."""

    session_id: str
    vehicle_id: str
    charger_adapter: ChargerAdapter
    start_time: datetime
    target_soc: int
    schedule: ChargingSchedule
    energy_kwh: Decimal = Decimal("0.00")
    actual_cost_pln: Decimal = Decimal("0.00")
    is_manual: bool = False
    is_paused: bool = False
    last_soc_reading: Optional[float] = None
    last_soc_time: Optional[datetime] = None
    monitor_task: Optional[asyncio.Task] = None


class EVScheduler:
    """Scheduler ładowania EV.

    Oblicza optymalne harmonogramy ładowania na podstawie kosztów energii,
    ograniczeń mocy i strategii per pojazd. Wykorzystuje ScheduleEngine (LP solver).
    """

    def __init__(self) -> None:
        """Inicjalizacja EVScheduler."""
        self._engine = ScheduleEngine()

    def calculate_schedule(
        self,
        vehicle: VehicleConfig,
        charger: ChargerConfig,
        costs: list[HourlyCost],
        constraints: ChargingConstraints,
        current_soc: Optional[float] = None,
        pv_surplus_hours: Optional[list[int]] = None,
    ) -> ChargingSchedule:
        """Oblicz optymalny harmonogram ładowania dla jednego pojazdu.

        Konwertuje VehicleConfig + costs na dane wejściowe ScheduleEngine,
        rozwiązuje problem optymalizacji i zwraca ChargingSchedule.

        Args:
            vehicle: Konfiguracja pojazdu.
            charger: Konfiguracja ładowarki.
            costs: Lista kosztów godzinowych.
            constraints: Ograniczenia ładowania.
            current_soc: Aktualny SoC pojazdu (%). Jeśli None, używa 0.
            pv_surplus_hours: Godziny z nadwyżką PV (dla strategii PV_ONLY).

        Returns:
            ChargingSchedule z oknami ładowania, kosztem i feasibility.
        """
        if not costs:
            return self._empty_schedule(vehicle.vehicle_id, is_feasible=False)

        # Calculate required energy
        soc = current_soc if current_soc is not None else 0.0
        if soc >= vehicle.target_soc:
            # Already at target — no charging needed
            return self._empty_schedule(vehicle.vehicle_id, is_feasible=True)

        soc_delta = vehicle.target_soc - soc
        required_energy = (soc_delta / 100.0) * vehicle.battery_capacity_kwh

        if required_energy <= 0:
            return self._empty_schedule(vehicle.vehicle_id, is_feasible=True)

        # Build time slots from costs
        time_slots = self._costs_to_time_slots(costs)

        # Filter slots based on strategy
        filtered_slots, filtered_costs = self._apply_strategy_filter(
            vehicle.strategy,
            time_slots,
            costs,
            constraints.deadline,
            pv_surplus_hours,
        )

        if not filtered_slots:
            return self._infeasible_schedule(
                vehicle.vehicle_id, soc, vehicle.target_soc,
                vehicle.battery_capacity_kwh, required_energy,
            )

        # Determine power limits
        power_max = min(
            vehicle.max_charging_power_kw,
            charger.max_power_kw,
            constraints.charger_max_power_kw,
        )
        power_min = max(
            vehicle.min_charging_power_kw,
            constraints.min_charging_power_kw,
        )

        # Build existing load per slot
        existing_load = [constraints.current_building_load_kw] * len(filtered_slots)

        # Convert costs to Decimal list
        cost_values = [c.cost_pln_kwh for c in filtered_costs]

        # Solve using ScheduleEngine
        result = self._engine.solve_minimum_cost_schedule(
            time_slots=filtered_slots,
            costs=cost_values,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=constraints.grid_limit_kw,
            existing_load=existing_load,
            allow_discontinuous=constraints.allow_discontinuous,
        )

        # Convert ScheduleResult to ChargingSchedule
        return self._result_to_schedule(
            result, vehicle, soc, required_energy,
        )

    def calculate_multi_vehicle_schedule(
        self,
        vehicles: list[VehicleChargerPair],
        costs: list[HourlyCost],
        grid_limit_kw: float,
        current_socs: Optional[dict[str, float]] = None,
        current_building_load_kw: float = 0.0,
        pv_surplus_hours: Optional[list[int]] = None,
    ) -> list[ChargingSchedule]:
        """Harmonogram dla wielu pojazdów z priorytetami.

        Alokuje moc sekwencyjnie wg priorytetu (1 = najwyższy).
        Pojazd o wyższym priorytecie dostaje pełne zapotrzebowanie mocy,
        pozostała moc trafia do kolejnych pojazdów.

        Args:
            vehicles: Lista par pojazd-ładowarka.
            costs: Lista kosztów godzinowych.
            grid_limit_kw: Limit mocy przyłączeniowej.
            current_socs: Słownik aktualnych SoC per vehicle_id.
            current_building_load_kw: Bieżące obciążenie budynku.
            pv_surplus_hours: Godziny z nadwyżką PV.

        Returns:
            Lista ChargingSchedule — jeden per vehicle (w kolejności vehicles).
        """
        if not costs or not vehicles:
            return [
                self._empty_schedule(vp.vehicle.vehicle_id, is_feasible=True)
                for vp in vehicles
            ]

        socs = current_socs or {}
        time_slots = self._costs_to_time_slots(costs)
        cost_values = [c.cost_pln_kwh for c in costs]

        # Build ScheduleDemand list
        demands: list[ScheduleDemand] = []
        demand_vehicle_map: dict[str, VehicleChargerPair] = {}

        for vp in vehicles:
            vehicle = vp.vehicle
            charger = vp.charger
            soc = socs.get(vehicle.vehicle_id, 0.0)

            if soc >= vehicle.target_soc:
                # Already at target — skip
                continue

            soc_delta = vehicle.target_soc - soc
            required_energy = (soc_delta / 100.0) * vehicle.battery_capacity_kwh

            if required_energy <= 0:
                continue

            power_max = min(vehicle.max_charging_power_kw, charger.max_power_kw)
            power_min = vehicle.min_charging_power_kw

            # Filter slots based on strategy
            filtered_slots, _ = self._apply_strategy_filter(
                vehicle.strategy,
                time_slots,
                costs,
                vehicle.deadline,
                pv_surplus_hours,
            )

            if not filtered_slots:
                continue

            demand = ScheduleDemand(
                demand_id=vehicle.vehicle_id,
                required_energy=required_energy,
                power_min=power_min,
                power_max=power_max,
                priority=vehicle.priority,
                time_slots=filtered_slots,
                allow_discontinuous=True,
            )
            demands.append(demand)
            demand_vehicle_map[vehicle.vehicle_id] = vp

        if not demands:
            return [
                self._empty_schedule(vp.vehicle.vehicle_id, is_feasible=True)
                for vp in vehicles
            ]

        # Solve multi-priority schedule
        existing_load = [current_building_load_kw] * len(cost_values)
        results = self._engine.solve_multi_priority_schedule(
            demands=demands,
            costs=cost_values,
            grid_limit=grid_limit_kw,
            existing_load=existing_load,
        )

        # Map results back to vehicles in original order
        result_map: dict[str, ScheduleResult] = {}
        for demand, result in zip(demands, results):
            result_map[demand.demand_id] = result

        schedules: list[ChargingSchedule] = []
        for vp in vehicles:
            vehicle = vp.vehicle
            soc = socs.get(vehicle.vehicle_id, 0.0)

            if vehicle.vehicle_id in result_map:
                soc_delta = vehicle.target_soc - soc
                required_energy = (soc_delta / 100.0) * vehicle.battery_capacity_kwh
                schedule = self._result_to_schedule(
                    result_map[vehicle.vehicle_id],
                    vehicle,
                    soc,
                    required_energy,
                )
            else:
                # Vehicle already at target or no slots available
                schedule = self._empty_schedule(
                    vehicle.vehicle_id, is_feasible=(soc >= vehicle.target_soc)
                )
            schedules.append(schedule)

        return schedules

    def _costs_to_time_slots(self, costs: list[HourlyCost]) -> list[TimeSlot]:
        """Konwertuj listę HourlyCost na listę TimeSlot."""
        slots = []
        for cost in costs:
            start = cost.timestamp
            end = start + timedelta(hours=1)
            slots.append(TimeSlot(start=start, end=end, duration_hours=1.0))
        return slots

    def _apply_strategy_filter(
        self,
        strategy: ChargingStrategy,
        time_slots: list[TimeSlot],
        costs: list[HourlyCost],
        deadline: Optional[datetime],
        pv_surplus_hours: Optional[list[int]],
    ) -> tuple[list[TimeSlot], list[HourlyCost]]:
        """Filtruj sloty na podstawie strategii ładowania.

        Args:
            strategy: Strategia ładowania.
            time_slots: Wszystkie dostępne sloty.
            costs: Koszty per slot.
            deadline: Deadline (dla READY_BY).
            pv_surplus_hours: Godziny z nadwyżką PV (dla PV_ONLY).

        Returns:
            Tuple (filtered_slots, filtered_costs).
        """
        if strategy == ChargingStrategy.CHEAPEST:
            # No filtering — use all available slots
            return time_slots, costs

        elif strategy == ChargingStrategy.READY_BY:
            # Filter to slots before deadline
            if deadline is None:
                return time_slots, costs

            filtered_slots = []
            filtered_costs = []
            for slot, cost in zip(time_slots, costs):
                if slot.end <= deadline:
                    filtered_slots.append(slot)
                    filtered_costs.append(cost)
            return filtered_slots, filtered_costs

        elif strategy == ChargingStrategy.PV_ONLY:
            # Only use hours with PV surplus
            if pv_surplus_hours is None:
                return [], []

            filtered_slots = []
            filtered_costs = []
            for slot, cost in zip(time_slots, costs):
                if cost.hour in pv_surplus_hours:
                    filtered_slots.append(slot)
                    filtered_costs.append(cost)
            return filtered_slots, filtered_costs

        return time_slots, costs

    def _result_to_schedule(
        self,
        result: ScheduleResult,
        vehicle: VehicleConfig,
        current_soc: float,
        required_energy: float,
    ) -> ChargingSchedule:
        """Konwertuj ScheduleResult na ChargingSchedule."""
        if not result.windows:
            if not result.is_feasible:
                return self._infeasible_schedule(
                    vehicle.vehicle_id, current_soc, vehicle.target_soc,
                    vehicle.battery_capacity_kwh, required_energy,
                )
            return self._empty_schedule(vehicle.vehicle_id, is_feasible=True)

        # Convert ScheduleWindows to TimeWindows
        windows = [
            TimeWindow(
                start=w.slot.start,
                end=w.slot.end,
                power_kw=w.power_kw,
            )
            for w in result.windows
        ]

        # Estimated completion is end of last window
        estimated_completion = max(w.end for w in windows)

        # If infeasible, calculate best achievable SoC
        best_achievable_soc: Optional[int] = None
        if not result.is_feasible:
            achievable_energy = result.total_energy
            achievable_soc_gain = (achievable_energy / vehicle.battery_capacity_kwh) * 100
            best_achievable_soc = int(current_soc + achievable_soc_gain)
            best_achievable_soc = min(best_achievable_soc, 100)

        return ChargingSchedule(
            vehicle_id=vehicle.vehicle_id,
            windows=windows,
            estimated_cost_pln=result.total_cost,
            estimated_energy_kwh=result.total_energy,
            estimated_completion=estimated_completion,
            is_feasible=result.is_feasible,
            best_achievable_soc=best_achievable_soc,
        )

    def _empty_schedule(
        self, vehicle_id: str, is_feasible: bool
    ) -> ChargingSchedule:
        """Utwórz pusty harmonogram."""
        return ChargingSchedule(
            vehicle_id=vehicle_id,
            windows=[],
            estimated_cost_pln=Decimal("0.00"),
            estimated_energy_kwh=0.0,
            estimated_completion=datetime.now(),
            is_feasible=is_feasible,
            best_achievable_soc=None,
        )

    def _infeasible_schedule(
        self,
        vehicle_id: str,
        current_soc: float,
        target_soc: int,
        battery_capacity_kwh: float,
        required_energy: float,
    ) -> ChargingSchedule:
        """Utwórz harmonogram z flagą infeasible i best_achievable_soc."""
        # Calculate best achievable SoC (what we can reach with 0 energy)
        best_achievable = int(current_soc)

        return ChargingSchedule(
            vehicle_id=vehicle_id,
            windows=[],
            estimated_cost_pln=Decimal("0.00"),
            estimated_energy_kwh=0.0,
            estimated_completion=datetime.now(),
            is_feasible=False,
            best_achievable_soc=best_achievable,
        )


class ChargingSessionManager:
    """Zarządzanie sesjami ładowania EV.

    Odpowiedzialności:
    - Start/stop sesji ładowania via ChargerAdapter
    - Monitoring SoC co SOC_CHECK_INTERVAL (60s)
    - Warunek zatrzymania: SoC >= target_soc OR okno zakończone
    - Obsługa niedostępności SoC >5min: pauza + powiadomienie
    - Rejestracja sesji (czas, energia, koszt)
    - Obsługa ładowania manualnego
    """

    def __init__(
        self,
        get_soc: Callable[[str], Optional[float]],
        get_current_cost: Callable[[], Decimal],
        notify_user: Callable[[str, str], Any],
        fire_event: Callable[[str, dict], Any],
    ) -> None:
        """Inicjalizacja ChargingSessionManager.

        Args:
            get_soc: Callback do odczytu SoC pojazdu (vehicle_id -> SoC%).
            get_current_cost: Callback do odczytu bieżącego kosztu energii.
            notify_user: Callback do powiadomienia użytkownika (title, message).
            fire_event: Callback do wyzwolenia zdarzenia HA (event_type, data).
        """
        self._get_soc = get_soc
        self._get_current_cost = get_current_cost
        self._notify_user = notify_user
        self._fire_event = fire_event
        self._active_sessions: dict[str, ActiveSession] = {}
        self._completed_sessions: list[ChargingSession] = []

    @property
    def active_sessions(self) -> dict[str, ActiveSession]:
        """Aktywne sesje ładowania."""
        return self._active_sessions

    @property
    def completed_sessions(self) -> list[ChargingSession]:
        """Zakończone sesje ładowania."""
        return self._completed_sessions

    async def start_session(
        self,
        vehicle_id: str,
        charger_adapter: ChargerAdapter,
        schedule: ChargingSchedule,
        target_soc: int,
        power_kw: float,
        is_manual: bool = False,
    ) -> bool:
        """Rozpocznij sesję ładowania.

        Args:
            vehicle_id: ID pojazdu.
            charger_adapter: Adapter ładowarki.
            schedule: Harmonogram ładowania.
            target_soc: Docelowy SoC.
            power_kw: Moc ładowania (kW).
            is_manual: Czy ładowanie manualne.

        Returns:
            True jeśli sesja została rozpoczęta pomyślnie.
        """
        if vehicle_id in self._active_sessions:
            _LOGGER.warning(
                "Sesja ładowania dla %s już aktywna — pomijam start",
                vehicle_id,
            )
            return False

        # Send start command to charger
        success = await charger_adapter.start_charging(power_kw)
        if not success:
            _LOGGER.error(
                "Nie udało się rozpocząć ładowania dla %s", vehicle_id
            )
            return False

        session = ActiveSession(
            session_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            charger_adapter=charger_adapter,
            start_time=datetime.now(),
            target_soc=target_soc,
            schedule=schedule,
            is_manual=is_manual,
        )

        self._active_sessions[vehicle_id] = session

        # Fire charging started event
        self._fire_event("peo_charging_started", {
            "vehicle_id": vehicle_id,
            "session_id": session.session_id,
            "target_soc": target_soc,
            "power_kw": power_kw,
            "is_manual": is_manual,
            "timestamp": session.start_time.isoformat(),
        })

        # Start SoC monitoring task
        session.monitor_task = asyncio.create_task(
            self._monitor_loop(vehicle_id)
        )

        _LOGGER.info(
            "Sesja ładowania rozpoczęta: vehicle=%s, target_soc=%d%%, power=%.1f kW",
            vehicle_id,
            target_soc,
            power_kw,
        )
        return True

    async def stop_session(self, vehicle_id: str) -> Optional[ChargingSession]:
        """Zatrzymaj sesję ładowania.

        Args:
            vehicle_id: ID pojazdu.

        Returns:
            ChargingSession z danymi zakończonej sesji, lub None jeśli brak aktywnej sesji.
        """
        session = self._active_sessions.get(vehicle_id)
        if session is None:
            _LOGGER.warning(
                "Brak aktywnej sesji ładowania dla %s", vehicle_id
            )
            return None

        # Cancel monitor task
        if session.monitor_task and not session.monitor_task.done():
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        # Send stop command to charger
        await session.charger_adapter.stop_charging()

        # Calculate session data
        end_time = datetime.now()
        duration_minutes = int(
            (end_time - session.start_time).total_seconds() / 60
        )

        # Create completed session record
        completed = ChargingSession(
            session_id=session.session_id,
            vehicle_id=vehicle_id,
            start_time=session.start_time,
            end_time=end_time,
            energy_kwh=session.energy_kwh,
            actual_cost_pln=session.actual_cost_pln,
            hypothetical_cost_pln=Decimal("0.00"),  # Calculated externally
            is_manual=session.is_manual,
            duration_minutes=duration_minutes,
        )

        self._completed_sessions.append(completed)
        del self._active_sessions[vehicle_id]

        # Fire charging completed event
        self._fire_event("peo_charging_completed", {
            "vehicle_id": vehicle_id,
            "session_id": completed.session_id,
            "duration_minutes": duration_minutes,
            "energy_kwh": str(completed.energy_kwh),
            "actual_cost_pln": str(completed.actual_cost_pln),
            "is_manual": completed.is_manual,
            "timestamp": end_time.isoformat(),
        })

        _LOGGER.info(
            "Sesja ładowania zakończona: vehicle=%s, duration=%d min, energy=%.2f kWh",
            vehicle_id,
            duration_minutes,
            float(completed.energy_kwh),
        )
        return completed

    async def monitor_soc(self, vehicle_id: str) -> None:
        """Sprawdź SoC pojazdu i podejmij decyzję o kontynuacji/zatrzymaniu.

        Warunki zatrzymania:
        - SoC >= target_soc
        - Okno ładowania zakończone

        Obsługa niedostępności SoC:
        - >5 minut bez odczytu: pauza + powiadomienie

        Args:
            vehicle_id: ID pojazdu.
        """
        session = self._active_sessions.get(vehicle_id)
        if session is None:
            return

        now = datetime.now()

        # Read current SoC
        soc = self._get_soc(vehicle_id)

        if soc is not None:
            session.last_soc_reading = soc
            session.last_soc_time = now

            # Check stop condition: SoC >= target
            if soc >= session.target_soc:
                _LOGGER.info(
                    "SoC osiągnął cel (%d%% >= %d%%) — zatrzymuję ładowanie %s",
                    int(soc),
                    session.target_soc,
                    vehicle_id,
                )
                await self.stop_session(vehicle_id)
                return

            # Update energy estimate based on SoC change
            # (simplified — real implementation would use charger meter)

            # Resume if was paused
            if session.is_paused:
                session.is_paused = False
                _LOGGER.info(
                    "SoC ponownie dostępny — wznawiam ładowanie %s", vehicle_id
                )
        else:
            # SoC unavailable
            if session.last_soc_time is not None:
                elapsed = (now - session.last_soc_time).total_seconds()
                if elapsed > SOC_UNAVAILABLE_TIMEOUT and not session.is_paused:
                    # Pause automation and notify user
                    session.is_paused = True
                    _LOGGER.warning(
                        "SoC niedostępny >5 min dla %s — wstrzymuję automatykę",
                        vehicle_id,
                    )
                    self._notify_user(
                        "PEO: Brak danych SoC",
                        f"Encja SoC pojazdu {vehicle_id} jest niedostępna "
                        f"od ponad 5 minut. Automatyczne sterowanie ładowaniem "
                        f"zostało wstrzymane.",
                    )
            elif not session.is_paused:
                # First check and SoC is already unavailable
                session.last_soc_time = now

        # Check stop condition: window ended
        if self._is_window_ended(session, now):
            _LOGGER.info(
                "Okno ładowania zakończone — zatrzymuję ładowanie %s",
                vehicle_id,
            )
            await self.stop_session(vehicle_id)
            return

        # Update energy and cost tracking
        self._update_session_tracking(session, now)

    async def _monitor_loop(self, vehicle_id: str) -> None:
        """Pętla monitoringu SoC — sprawdza co SOC_CHECK_INTERVAL (60s).

        Args:
            vehicle_id: ID pojazdu.
        """
        try:
            while vehicle_id in self._active_sessions:
                await self.monitor_soc(vehicle_id)
                # Check if session was stopped during monitor_soc
                if vehicle_id not in self._active_sessions:
                    break
                await asyncio.sleep(SOC_CHECK_INTERVAL)
        except asyncio.CancelledError:
            _LOGGER.debug("Monitor SoC anulowany dla %s", vehicle_id)
            raise

    def _is_window_ended(self, session: ActiveSession, now: datetime) -> bool:
        """Sprawdź czy bieżące okno ładowania się zakończyło."""
        if not session.schedule.windows:
            return False

        # Check if current time is past all windows
        last_window_end = max(w.end for w in session.schedule.windows)
        return now >= last_window_end

    def _update_session_tracking(
        self, session: ActiveSession, now: datetime
    ) -> None:
        """Aktualizuj śledzenie energii i kosztu sesji."""
        # Estimate energy consumed in last interval
        # In real implementation, this would read from charger meter
        elapsed_hours = SOC_CHECK_INTERVAL / 3600.0

        # Get current charging power from schedule windows
        current_power = self._get_current_power(session, now)
        if current_power > 0 and not session.is_paused:
            energy_increment = Decimal(str(
                round(current_power * elapsed_hours, 4)
            ))
            cost_increment = energy_increment * self._get_current_cost()
            session.energy_kwh += energy_increment
            session.actual_cost_pln += cost_increment

    def _get_current_power(
        self, session: ActiveSession, now: datetime
    ) -> float:
        """Pobierz aktualną moc ładowania z harmonogramu."""
        for window in session.schedule.windows:
            if window.start <= now < window.end:
                return window.power_kw
        return 0.0

    def handle_manual_charging(
        self,
        vehicle_id: str,
        charger_adapter: ChargerAdapter,
        target_soc: int,
    ) -> None:
        """Zarejestruj ładowanie manualne.

        Tworzy sesję z flagą is_manual=True.
        Kontynuuje odczyt SoC i energii.

        Args:
            vehicle_id: ID pojazdu.
            charger_adapter: Adapter ładowarki.
            target_soc: Docelowy SoC.
        """
        # Create a manual schedule (empty windows — no automated control)
        manual_schedule = ChargingSchedule(
            vehicle_id=vehicle_id,
            windows=[],
            estimated_cost_pln=Decimal("0.00"),
            estimated_energy_kwh=0.0,
            estimated_completion=datetime.now(),
            is_feasible=True,
            best_achievable_soc=None,
        )

        session = ActiveSession(
            session_id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            charger_adapter=charger_adapter,
            start_time=datetime.now(),
            target_soc=target_soc,
            schedule=manual_schedule,
            is_manual=True,
        )

        self._active_sessions[vehicle_id] = session

        _LOGGER.info(
            "Ładowanie manualne zarejestrowane: vehicle=%s", vehicle_id
        )

    def get_session_data(self, vehicle_id: str) -> Optional[dict]:
        """Pobierz dane aktywnej sesji.

        Args:
            vehicle_id: ID pojazdu.

        Returns:
            Słownik z danymi sesji lub None.
        """
        session = self._active_sessions.get(vehicle_id)
        if session is None:
            return None

        return {
            "session_id": session.session_id,
            "vehicle_id": session.vehicle_id,
            "start_time": session.start_time.isoformat(),
            "target_soc": session.target_soc,
            "energy_kwh": str(session.energy_kwh),
            "actual_cost_pln": str(session.actual_cost_pln),
            "is_manual": session.is_manual,
            "is_paused": session.is_paused,
            "last_soc_reading": session.last_soc_reading,
        }
