"""Testy jednostkowe dla EVScheduler i ChargingSessionManager."""

from datetime import datetime, timedelta
from decimal import Decimal
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.peo.enums import ChargingStrategy, TimeZoneName
from custom_components.peo.ev_scheduler import (
    ActiveSession,
    ChargingSessionManager,
    EVScheduler,
    SOC_UNAVAILABLE_TIMEOUT,
)
from custom_components.peo.models import (
    ChargerConfig,
    ChargingConstraints,
    ChargingSchedule,
    HourlyCost,
    TariffRates,
    TimeWindow,
    VehicleChargerPair,
    VehicleConfig,
)


@pytest.fixture
def scheduler():
    """Fixture: instancja EVScheduler."""
    return EVScheduler()


@pytest.fixture
def base_time():
    """Fixture: bazowy czas startowy."""
    return datetime(2024, 1, 15, 0, 0)


@pytest.fixture
def default_rates():
    """Fixture: domyślne stawki taryfowe."""
    return TariffRates(
        energy_price=Decimal("0.50"),
        distribution_variable=Decimal("0.20"),
        transition_fee=Decimal("0.01"),
        oze_fee=Decimal("0.01"),
        capacity_fee=Decimal("0.05"),
        cogeneration_fee=Decimal("0.01"),
    )


def make_costs(base: datetime, count: int, cost_values: list[Decimal] | None = None, rates: TariffRates | None = None) -> list[HourlyCost]:
    """Utwórz listę kosztów godzinowych."""
    if rates is None:
        rates = TariffRates(
            energy_price=Decimal("0.50"),
            distribution_variable=Decimal("0.20"),
            transition_fee=Decimal("0.01"),
            oze_fee=Decimal("0.01"),
            capacity_fee=Decimal("0.05"),
            cogeneration_fee=Decimal("0.01"),
        )
    if cost_values is None:
        cost_values = [Decimal("0.78")] * count

    return [
        HourlyCost(
            hour=(base + timedelta(hours=i)).hour,
            timestamp=base + timedelta(hours=i),
            cost_pln_kwh=cost_values[i] if i < len(cost_values) else Decimal("0.78"),
            zone=TimeZoneName.POZASZCZYT,
            components=rates,
        )
        for i in range(count)
    ]


def make_vehicle(
    vehicle_id: str = "ev1",
    battery_kwh: float = 60.0,
    max_power: float = 11.0,
    min_power: float = 1.4,
    target_soc: int = 80,
    strategy: ChargingStrategy = ChargingStrategy.CHEAPEST,
    deadline: datetime | None = None,
    priority: int = 1,
) -> VehicleConfig:
    """Utwórz konfigurację pojazdu."""
    return VehicleConfig(
        vehicle_id=vehicle_id,
        name=f"Test EV {vehicle_id}",
        battery_capacity_kwh=battery_kwh,
        max_charging_power_kw=max_power,
        min_charging_power_kw=min_power,
        soc_entity_id=f"sensor.{vehicle_id}_soc",
        target_soc=target_soc,
        deadline=deadline,
        priority=priority,
        strategy=strategy,
    )


def make_charger(
    charger_id: str = "charger1",
    max_power: float = 22.0,
    max_current: float = 32.0,
) -> ChargerConfig:
    """Utwórz konfigurację ładowarki."""
    return ChargerConfig(
        charger_id=charger_id,
        name=f"Test Charger {charger_id}",
        protocol="ocpp16",
        host="192.168.1.100",
        api_key=None,
        entity_id=None,
        max_power_kw=max_power,
        max_current_a=max_current,
    )


def make_constraints(
    grid_limit: float = 12.0,
    building_load: float = 2.0,
    charger_max_power: float = 11.0,
    charger_max_current: float = 16.0,
    min_power: float = 1.4,
    deadline: datetime | None = None,
    allow_discontinuous: bool = True,
) -> ChargingConstraints:
    """Utwórz ograniczenia ładowania."""
    return ChargingConstraints(
        grid_limit_kw=grid_limit,
        current_building_load_kw=building_load,
        charger_max_power_kw=charger_max_power,
        charger_max_current_a=charger_max_current,
        min_charging_power_kw=min_power,
        deadline=deadline,
        allow_discontinuous=allow_discontinuous,
    )


class TestEVSchedulerCalculateSchedule:
    """Testy EVScheduler.calculate_schedule()."""

    def test_already_at_target_soc(self, scheduler, base_time):
        """Pojazd już naładowany do celu — brak okien, feasible."""
        vehicle = make_vehicle(target_soc=80)
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=85.0,
        )

        assert result.is_feasible
        assert result.windows == []
        assert result.estimated_energy_kwh == 0.0

    def test_empty_costs_returns_infeasible(self, scheduler):
        """Puste koszty → infeasible."""
        vehicle = make_vehicle()
        charger = make_charger()
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=[],
            constraints=constraints,
            current_soc=20.0,
        )

        assert not result.is_feasible

    def test_cheapest_strategy_uses_all_slots(self, scheduler, base_time):
        """Strategia CHEAPEST — używa wszystkich dostępnych slotów."""
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=80,
            strategy=ChargingStrategy.CHEAPEST,
        )
        charger = make_charger()
        # Varying costs — cheapest at hours 2, 5
        cost_values = [
            Decimal("0.80"), Decimal("0.70"), Decimal("0.30"),
            Decimal("0.60"), Decimal("0.50"), Decimal("0.25"),
            Decimal("0.90"), Decimal("0.85"),
        ]
        costs = make_costs(base_time, 8, cost_values)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
        )

        assert result.is_feasible
        assert result.vehicle_id == "ev1"
        # Required energy: (80-50)/100 * 60 = 18 kWh
        assert result.estimated_energy_kwh >= 18.0 - 0.1
        assert result.estimated_cost_pln > Decimal("0.00")
        assert len(result.windows) > 0

    def test_ready_by_strategy_respects_deadline(self, scheduler, base_time):
        """Strategia READY_BY — tylko sloty przed deadline."""
        deadline = base_time + timedelta(hours=4)
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=80,
            strategy=ChargingStrategy.READY_BY,
            deadline=deadline,
        )
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints(deadline=deadline)

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
        )

        # All windows should end before or at deadline
        for window in result.windows:
            assert window.end <= deadline

    def test_pv_only_strategy_uses_surplus_hours(self, scheduler, base_time):
        """Strategia PV_ONLY — tylko godziny z nadwyżką PV."""
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=60,
            strategy=ChargingStrategy.PV_ONLY,
        )
        charger = make_charger()
        costs = make_costs(base_time, 24)
        constraints = make_constraints()

        # PV surplus only at hours 10, 11, 12, 13
        pv_surplus_hours = [10, 11, 12, 13]

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
            pv_surplus_hours=pv_surplus_hours,
        )

        # Windows should only be in PV surplus hours
        for window in result.windows:
            assert window.start.hour in pv_surplus_hours

    def test_pv_only_no_surplus_returns_infeasible(self, scheduler, base_time):
        """Strategia PV_ONLY bez nadwyżki → infeasible."""
        vehicle = make_vehicle(
            strategy=ChargingStrategy.PV_ONLY,
        )
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=20.0,
            pv_surplus_hours=None,  # No PV surplus
        )

        assert not result.is_feasible

    def test_infeasible_sets_best_achievable_soc(self, scheduler, base_time):
        """Infeasible harmonogram ustawia best_achievable_soc."""
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=100,
            strategy=ChargingStrategy.READY_BY,
            deadline=base_time + timedelta(hours=1),
        )
        charger = make_charger(max_power=3.0)
        costs = make_costs(base_time, 1)
        # Only 1 hour, max 3kW → max 3 kWh → max ~5% SoC gain on 60kWh battery
        constraints = make_constraints(charger_max_power=3.0)

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=20.0,
        )

        # Can't reach 100% in 1 hour with 3kW on 60kWh battery
        assert not result.is_feasible
        assert result.best_achievable_soc is not None
        # Best achievable: 20 + (3kWh / 60kWh * 100) = 25%
        assert result.best_achievable_soc == 25

    def test_respects_charger_power_limit(self, scheduler, base_time):
        """Moc nie przekracza limitu ładowarki."""
        vehicle = make_vehicle(max_power=22.0)
        charger = make_charger(max_power=7.0)  # Charger limits to 7kW
        costs = make_costs(base_time, 8)
        constraints = make_constraints(charger_max_power=7.0)

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=20.0,
        )

        assert result.is_feasible
        for window in result.windows:
            assert window.power_kw <= 7.0 + 0.01

    def test_respects_grid_limit(self, scheduler, base_time):
        """Moc + obciążenie budynku nie przekracza grid_limit."""
        vehicle = make_vehicle(max_power=11.0)
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints(
            grid_limit=10.0,
            building_load=5.0,
            charger_max_power=11.0,
        )

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
        )

        assert result.is_feasible
        for window in result.windows:
            # power + building_load <= grid_limit
            assert window.power_kw + 5.0 <= 10.0 + 0.01

    def test_required_energy_calculation(self, scheduler, base_time):
        """Wymagana energia = (target_soc - current_soc) / 100 * battery_kwh."""
        vehicle = make_vehicle(battery_kwh=50.0, target_soc=90)
        charger = make_charger()
        costs = make_costs(base_time, 12)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=40.0,
        )

        # Required: (90-40)/100 * 50 = 25 kWh
        assert result.is_feasible
        assert result.estimated_energy_kwh >= 25.0 - 0.1

    def test_schedule_has_time_windows(self, scheduler, base_time):
        """Harmonogram zawiera TimeWindow z start, end, power_kw."""
        vehicle = make_vehicle()
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
        )

        assert result.is_feasible
        for window in result.windows:
            assert isinstance(window, TimeWindow)
            assert window.start < window.end
            assert window.power_kw > 0

    def test_estimated_completion_is_end_of_last_window(self, scheduler, base_time):
        """estimated_completion = koniec ostatniego okna."""
        vehicle = make_vehicle()
        charger = make_charger()
        costs = make_costs(base_time, 8)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
        )

        if result.windows:
            last_end = max(w.end for w in result.windows)
            assert result.estimated_completion == last_end


class TestEVSchedulerMultiVehicle:
    """Testy EVScheduler.calculate_multi_vehicle_schedule()."""

    def test_empty_vehicles_returns_empty(self, scheduler, base_time):
        """Pusta lista pojazdów → pusta lista wyników."""
        costs = make_costs(base_time, 8)
        result = scheduler.calculate_multi_vehicle_schedule(
            vehicles=[],
            costs=costs,
            grid_limit_kw=12.0,
        )
        assert result == []

    def test_single_vehicle(self, scheduler, base_time):
        """Jeden pojazd — działa jak calculate_schedule."""
        vehicle = make_vehicle(target_soc=80)
        charger = make_charger()
        costs = make_costs(base_time, 8)

        vehicles = [VehicleChargerPair(vehicle=vehicle, charger=charger)]
        results = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles,
            costs=costs,
            grid_limit_kw=12.0,
            current_socs={"ev1": 50.0},
        )

        assert len(results) == 1
        assert results[0].is_feasible
        assert results[0].vehicle_id == "ev1"

    def test_two_vehicles_priority_order(self, scheduler, base_time):
        """Dwa pojazdy — wyższy priorytet dostaje pełną alokację."""
        vehicle1 = make_vehicle(
            vehicle_id="ev1", priority=1, target_soc=80, battery_kwh=60.0,
        )
        vehicle2 = make_vehicle(
            vehicle_id="ev2", priority=2, target_soc=80, battery_kwh=60.0,
        )
        charger1 = make_charger(charger_id="ch1")
        charger2 = make_charger(charger_id="ch2")
        costs = make_costs(base_time, 8)

        vehicles = [
            VehicleChargerPair(vehicle=vehicle1, charger=charger1),
            VehicleChargerPair(vehicle=vehicle2, charger=charger2),
        ]
        results = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles,
            costs=costs,
            grid_limit_kw=15.0,
            current_socs={"ev1": 50.0, "ev2": 50.0},
        )

        assert len(results) == 2
        # First vehicle (priority 1) should be feasible
        assert results[0].is_feasible
        assert results[0].vehicle_id == "ev1"

    def test_vehicle_already_at_target(self, scheduler, base_time):
        """Pojazd już naładowany — pusty harmonogram, feasible."""
        vehicle = make_vehicle(target_soc=80)
        charger = make_charger()
        costs = make_costs(base_time, 8)

        vehicles = [VehicleChargerPair(vehicle=vehicle, charger=charger)]
        results = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles,
            costs=costs,
            grid_limit_kw=12.0,
            current_socs={"ev1": 90.0},  # Already above target
        )

        assert len(results) == 1
        assert results[0].is_feasible
        assert results[0].windows == []

    def test_results_in_vehicle_order(self, scheduler, base_time):
        """Wyniki w kolejności vehicles (nie priorytetów)."""
        vehicle_low = make_vehicle(vehicle_id="ev_low", priority=3)
        vehicle_high = make_vehicle(vehicle_id="ev_high", priority=1)
        charger1 = make_charger(charger_id="ch1")
        charger2 = make_charger(charger_id="ch2")
        costs = make_costs(base_time, 8)

        vehicles = [
            VehicleChargerPair(vehicle=vehicle_low, charger=charger1),
            VehicleChargerPair(vehicle=vehicle_high, charger=charger2),
        ]
        results = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles,
            costs=costs,
            grid_limit_kw=30.0,
            current_socs={"ev_low": 50.0, "ev_high": 50.0},
        )

        assert len(results) == 2
        assert results[0].vehicle_id == "ev_low"
        assert results[1].vehicle_id == "ev_high"


class TestChargingSessionManager:
    """Testy ChargingSessionManager."""

    @pytest.fixture
    def mock_adapter(self):
        """Fixture: mock ChargerAdapter."""
        adapter = AsyncMock()
        adapter.start_charging = AsyncMock(return_value=True)
        adapter.stop_charging = AsyncMock(return_value=True)
        return adapter

    @pytest.fixture
    def session_manager(self):
        """Fixture: instancja ChargingSessionManager."""
        return ChargingSessionManager(
            get_soc=MagicMock(return_value=50.0),
            get_current_cost=MagicMock(return_value=Decimal("0.78")),
            notify_user=MagicMock(),
            fire_event=MagicMock(),
        )

    @pytest.fixture
    def sample_schedule(self, base_time):
        """Fixture: przykładowy harmonogram."""
        return ChargingSchedule(
            vehicle_id="ev1",
            windows=[
                TimeWindow(
                    start=base_time,
                    end=base_time + timedelta(hours=2),
                    power_kw=7.0,
                ),
            ],
            estimated_cost_pln=Decimal("10.92"),
            estimated_energy_kwh=14.0,
            estimated_completion=base_time + timedelta(hours=2),
            is_feasible=True,
            best_achievable_soc=None,
        )

    @pytest.mark.asyncio
    async def test_start_session_success(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Start sesji — sukces."""
        result = await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        assert result is True
        assert "ev1" in session_manager.active_sessions
        mock_adapter.start_charging.assert_called_once_with(7.0)

    @pytest.mark.asyncio
    async def test_start_session_fires_event(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Start sesji wyzwala zdarzenie peo_charging_started."""
        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        session_manager._fire_event.assert_called_once()
        call_args = session_manager._fire_event.call_args
        assert call_args[0][0] == "peo_charging_started"
        assert call_args[0][1]["vehicle_id"] == "ev1"

    @pytest.mark.asyncio
    async def test_start_session_duplicate_rejected(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Duplikat sesji — odrzucony."""
        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        result = await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_start_session_charger_failure(
        self, session_manager, sample_schedule
    ):
        """Charger nie odpowiada — sesja nie rozpoczęta."""
        adapter = AsyncMock()
        adapter.start_charging = AsyncMock(return_value=False)

        result = await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        assert result is False
        assert "ev1" not in session_manager.active_sessions

    @pytest.mark.asyncio
    async def test_stop_session_success(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Stop sesji — sukces, zwraca ChargingSession."""
        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        # Cancel the monitor task to avoid interference
        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        completed = await session_manager.stop_session("ev1")

        assert completed is not None
        assert completed.vehicle_id == "ev1"
        assert completed.end_time is not None
        assert "ev1" not in session_manager.active_sessions
        mock_adapter.stop_charging.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_session_fires_event(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Stop sesji wyzwala zdarzenie peo_charging_completed."""
        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        await session_manager.stop_session("ev1")

        # Should have fired both started and completed events
        assert session_manager._fire_event.call_count == 2
        last_call = session_manager._fire_event.call_args_list[-1]
        assert last_call[0][0] == "peo_charging_completed"

    @pytest.mark.asyncio
    async def test_stop_nonexistent_session(self, session_manager):
        """Stop nieistniejącej sesji → None."""
        result = await session_manager.stop_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_monitor_soc_stops_at_target(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Monitor SoC — zatrzymuje ładowanie gdy SoC >= target."""
        # Set SoC to return target value
        session_manager._get_soc = MagicMock(return_value=82.0)

        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        # Cancel the auto-started monitor task
        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        # Manually call monitor_soc
        await session_manager.monitor_soc("ev1")

        # Session should be stopped
        assert "ev1" not in session_manager.active_sessions
        assert len(session_manager.completed_sessions) == 1

    @pytest.mark.asyncio
    async def test_monitor_soc_unavailable_pauses(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Monitor SoC — niedostępność >5min pauzuje automatykę."""
        session_manager._get_soc = MagicMock(return_value=None)

        # Use a schedule with windows far in the future so window-ended check doesn't trigger
        from datetime import datetime, timedelta
        future_time = datetime.now() + timedelta(hours=10)
        future_schedule = ChargingSchedule(
            vehicle_id="ev1",
            windows=[
                TimeWindow(
                    start=future_time,
                    end=future_time + timedelta(hours=2),
                    power_kw=7.0,
                ),
            ],
            estimated_cost_pln=Decimal("10.92"),
            estimated_energy_kwh=14.0,
            estimated_completion=future_time + timedelta(hours=2),
            is_feasible=True,
            best_achievable_soc=None,
        )

        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=future_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        # First call sets last_soc_time
        await session_manager.monitor_soc("ev1")
        assert not session.is_paused

        # Simulate time passing > 5 minutes
        session.last_soc_time = datetime.now() - timedelta(seconds=SOC_UNAVAILABLE_TIMEOUT + 10)

        # Second call should trigger pause
        await session_manager.monitor_soc("ev1")
        assert session.is_paused
        session_manager._notify_user.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_soc_window_ended_stops(
        self, session_manager, mock_adapter, base_time
    ):
        """Monitor SoC — okno zakończone → stop."""
        # Schedule with window in the past
        past_schedule = ChargingSchedule(
            vehicle_id="ev1",
            windows=[
                TimeWindow(
                    start=base_time - timedelta(hours=3),
                    end=base_time - timedelta(hours=1),
                    power_kw=7.0,
                ),
            ],
            estimated_cost_pln=Decimal("10.92"),
            estimated_energy_kwh=14.0,
            estimated_completion=base_time - timedelta(hours=1),
            is_feasible=True,
            best_achievable_soc=None,
        )

        session_manager._get_soc = MagicMock(return_value=50.0)

        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=past_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        await session_manager.monitor_soc("ev1")

        # Session should be stopped (window ended)
        assert "ev1" not in session_manager.active_sessions

    def test_handle_manual_charging(self, session_manager, mock_adapter):
        """Rejestracja ładowania manualnego."""
        session_manager.handle_manual_charging(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            target_soc=80,
        )

        assert "ev1" in session_manager.active_sessions
        session = session_manager.active_sessions["ev1"]
        assert session.is_manual is True

    def test_get_session_data(self, session_manager, mock_adapter):
        """Pobieranie danych sesji."""
        session_manager.handle_manual_charging(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            target_soc=80,
        )

        data = session_manager.get_session_data("ev1")
        assert data is not None
        assert data["vehicle_id"] == "ev1"
        assert data["target_soc"] == 80
        assert data["is_manual"] is True

    def test_get_session_data_nonexistent(self, session_manager):
        """Pobieranie danych nieistniejącej sesji → None."""
        data = session_manager.get_session_data("nonexistent")
        assert data is None

    @pytest.mark.asyncio
    async def test_completed_sessions_stored(
        self, session_manager, mock_adapter, sample_schedule
    ):
        """Zakończone sesje są przechowywane."""
        await session_manager.start_session(
            vehicle_id="ev1",
            charger_adapter=mock_adapter,
            schedule=sample_schedule,
            target_soc=80,
            power_kw=7.0,
        )

        session = session_manager.active_sessions["ev1"]
        if session.monitor_task:
            session.monitor_task.cancel()
            try:
                await session.monitor_task
            except asyncio.CancelledError:
                pass

        await session_manager.stop_session("ev1")

        assert len(session_manager.completed_sessions) == 1
        completed = session_manager.completed_sessions[0]
        assert completed.vehicle_id == "ev1"
        assert completed.duration_minutes >= 0


class TestEVSchedulerStrategies:
    """Testy strategii ładowania."""

    def test_cheapest_no_deadline_constraint(self, scheduler, base_time):
        """CHEAPEST — brak ograniczenia deadline."""
        vehicle = make_vehicle(
            strategy=ChargingStrategy.CHEAPEST,
            deadline=None,
        )
        charger = make_charger()
        # Cheapest hours at end of range
        cost_values = [Decimal("0.90")] * 6 + [Decimal("0.20")] * 2
        costs = make_costs(base_time, 8, cost_values)
        constraints = make_constraints()

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=70.0,
        )

        assert result.is_feasible
        # Should prefer the cheap hours (6, 7)
        if result.windows:
            cheapest_window = min(result.windows, key=lambda w: w.start)
            # At least one window should be in cheap hours
            cheap_hours = {base_time + timedelta(hours=6), base_time + timedelta(hours=7)}
            window_starts = {w.start for w in result.windows}
            assert window_starts & cheap_hours

    def test_ready_by_with_tight_deadline(self, scheduler, base_time):
        """READY_BY z ciasnym deadline — może być infeasible."""
        deadline = base_time + timedelta(hours=1)
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=100,
            strategy=ChargingStrategy.READY_BY,
            deadline=deadline,
            max_power=7.0,
        )
        charger = make_charger(max_power=7.0)
        costs = make_costs(base_time, 8)
        constraints = make_constraints(
            charger_max_power=7.0,
            deadline=deadline,
        )

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=20.0,
        )

        # Need (100-20)/100 * 60 = 48 kWh, but max 7kW * 1h = 7 kWh
        assert not result.is_feasible

    def test_pv_only_with_sufficient_surplus(self, scheduler, base_time):
        """PV_ONLY z wystarczającą nadwyżką — feasible."""
        # Start at hour 8 so PV surplus hours (10, 11, 12, 13) are reachable
        start = base_time.replace(hour=8)
        vehicle = make_vehicle(
            battery_kwh=60.0,
            target_soc=55,  # Need only 3 kWh (5% of 60)
            strategy=ChargingStrategy.PV_ONLY,
            max_power=11.0,
        )
        charger = make_charger()
        costs = make_costs(start, 8)
        constraints = make_constraints()

        # PV surplus at hours 10, 11, 12, 13
        pv_surplus_hours = [10, 11, 12, 13]

        result = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=50.0,
            pv_surplus_hours=pv_surplus_hours,
        )

        assert result.is_feasible
