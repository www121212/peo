"""Sensory per pojazd-ładowarka dla PEO.

Implementuje oddzielny zestaw sensorów dla każdej pary pojazd-ładowarka:
- Status ładowania (charging_status)
- Planowane okna (planned_windows)
- Szacowany koszt (estimated_cost)
- Szacowany czas zakończenia (estimated_completion)
- Przydzielona moc (allocated_power)

Powiadamia użytkownika gdy ładowanie jest odroczone z powodu ograniczeń mocy.

Requirements: 11.5, 11.6
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .const import DOMAIN
from .models import (
    ChargingSchedule,
    TimeWindow,
    VehicleChargerPair,
    VehicleConfig,
    ChargerConfig,
)

_LOGGER = logging.getLogger(__name__)


class VehicleChargingSensor:
    """Sensor zestawu danych ładowania dla pary pojazd-ładowarka.

    Udostępnia atrybuty:
    - charging_status: idle / charging / scheduled / deferred / completed
    - planned_windows: lista okien ładowania (JSON)
    - estimated_cost: szacowany koszt w PLN
    - estimated_completion: szacowany czas zakończenia (ISO 8601)
    - allocated_power: przydzielona moc w kW

    Requirement 11.5, 11.6
    """

    def __init__(
        self,
        vehicle: VehicleConfig,
        charger: ChargerConfig,
        entry_id: str,
    ) -> None:
        """Inicjalizacja sensora pojazdu.

        Args:
            vehicle: Konfiguracja pojazdu.
            charger: Konfiguracja ładowarki.
            entry_id: ID wpisu konfiguracyjnego.
        """
        self._vehicle = vehicle
        self._charger = charger
        self._entry_id = entry_id

        # Sensor identity
        self._attr_name = f"PEO {vehicle.name} ładowanie"
        self._attr_unique_id = (
            f"{DOMAIN}_{entry_id}_{vehicle.vehicle_id}_{charger.charger_id}"
        )

        # State
        self._charging_status: str = "idle"
        self._planned_windows: list[dict[str, Any]] = []
        self._estimated_cost_pln: Decimal = Decimal("0.00")
        self._estimated_completion: Optional[str] = None
        self._allocated_power_kw: float = 0.0
        self._is_deferred: bool = False
        self._defer_reason: Optional[str] = None
        self._last_updated: Optional[str] = None

    @property
    def name(self) -> str:
        """Nazwa sensora."""
        return self._attr_name

    @property
    def unique_id(self) -> str:
        """Unikalny identyfikator sensora."""
        return self._attr_unique_id

    @property
    def vehicle_id(self) -> str:
        """ID pojazdu."""
        return self._vehicle.vehicle_id

    @property
    def charger_id(self) -> str:
        """ID ładowarki."""
        return self._charger.charger_id

    @property
    def state(self) -> str:
        """Stan sensora (charging_status)."""
        return self._charging_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Atrybuty stanu sensora."""
        return {
            "vehicle_id": self._vehicle.vehicle_id,
            "vehicle_name": self._vehicle.name,
            "charger_id": self._charger.charger_id,
            "charger_name": self._charger.name,
            "charging_status": self._charging_status,
            "planned_windows": self._planned_windows,
            "estimated_cost_pln": str(self._estimated_cost_pln),
            "estimated_completion": self._estimated_completion,
            "allocated_power_kw": round(self._allocated_power_kw, 2),
            "is_deferred": self._is_deferred,
            "defer_reason": self._defer_reason,
            "target_soc": self._vehicle.target_soc,
            "priority": self._vehicle.priority,
            "strategy": str(self._vehicle.strategy),
            "last_updated": self._last_updated,
        }

    @property
    def device_info(self) -> dict[str, Any]:
        """Informacje o urządzeniu."""
        return {
            "identifiers": {(DOMAIN, self._entry_id)},
            "name": "Polish Energy Optimizer",
            "manufacturer": "PEO",
            "model": "Energy Optimizer",
            "sw_version": "1.0.0",
        }

    def update_schedule(self, schedule: ChargingSchedule) -> None:
        """Aktualizuj sensor na podstawie nowego harmonogramu.

        Args:
            schedule: Nowy harmonogram ładowania.
        """
        self._last_updated = datetime.now(timezone.utc).isoformat()

        # Update planned windows
        self._planned_windows = [
            {
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "power_kw": round(w.power_kw, 2),
            }
            for w in schedule.windows
        ]

        # Update estimated cost and completion
        self._estimated_cost_pln = schedule.estimated_cost_pln
        self._estimated_completion = (
            schedule.estimated_completion.isoformat()
            if schedule.windows
            else None
        )

        # Update status based on schedule
        if not schedule.is_feasible:
            self._charging_status = "deferred"
            self._is_deferred = True
            self._defer_reason = "Nieosiągalny docelowy SoC w dostępnym czasie"
        elif schedule.windows:
            self._charging_status = "scheduled"
            self._is_deferred = False
            self._defer_reason = None
        else:
            self._charging_status = "idle"
            self._is_deferred = False
            self._defer_reason = None

    def set_charging_active(self, power_kw: float) -> None:
        """Ustaw status na aktywne ładowanie.

        Args:
            power_kw: Aktualna moc ładowania.
        """
        self._charging_status = "charging"
        self._allocated_power_kw = power_kw
        self._is_deferred = False
        self._defer_reason = None
        self._last_updated = datetime.now(timezone.utc).isoformat()

    def set_charging_completed(self) -> None:
        """Ustaw status na zakończone ładowanie."""
        self._charging_status = "completed"
        self._allocated_power_kw = 0.0
        self._last_updated = datetime.now(timezone.utc).isoformat()

    def set_deferred(self, reason: str) -> None:
        """Ustaw status na odroczone ładowanie.

        Args:
            reason: Powód odroczenia.
        """
        self._charging_status = "deferred"
        self._is_deferred = True
        self._defer_reason = reason
        self._allocated_power_kw = 0.0
        self._last_updated = datetime.now(timezone.utc).isoformat()

    def set_idle(self) -> None:
        """Ustaw status na bezczynny."""
        self._charging_status = "idle"
        self._allocated_power_kw = 0.0
        self._is_deferred = False
        self._defer_reason = None
        self._last_updated = datetime.now(timezone.utc).isoformat()

    def set_allocated_power(self, power_kw: float) -> None:
        """Aktualizuj przydzieloną moc.

        Args:
            power_kw: Przydzielona moc w kW.
        """
        self._allocated_power_kw = power_kw
        self._last_updated = datetime.now(timezone.utc).isoformat()


class VehicleSensorManager:
    """Menedżer sensorów pojazdów.

    Tworzy i zarządza zestawem sensorów dla każdej pary pojazd-ładowarka.
    Powiadamia użytkownika o odroczeniach ładowania.
    """

    def __init__(
        self,
        entry_id: str,
        notify_callback: Optional[Any] = None,
    ) -> None:
        """Inicjalizacja menedżera sensorów.

        Args:
            entry_id: ID wpisu konfiguracyjnego.
            notify_callback: Callback do powiadomień (title, message).
        """
        self._entry_id = entry_id
        self._notify_callback = notify_callback
        self._sensors: dict[str, VehicleChargingSensor] = {}

    @property
    def sensors(self) -> dict[str, VehicleChargingSensor]:
        """Słownik sensorów (klucz: vehicle_id)."""
        return self._sensors

    def register_vehicle(
        self,
        vehicle: VehicleConfig,
        charger: ChargerConfig,
    ) -> VehicleChargingSensor:
        """Zarejestruj parę pojazd-ładowarka i utwórz sensor.

        Args:
            vehicle: Konfiguracja pojazdu.
            charger: Konfiguracja ładowarki.

        Returns:
            Utworzony sensor.
        """
        sensor = VehicleChargingSensor(
            vehicle=vehicle,
            charger=charger,
            entry_id=self._entry_id,
        )
        self._sensors[vehicle.vehicle_id] = sensor

        _LOGGER.info(
            "Zarejestrowano sensor pojazdu: %s (%s) z ładowarką %s",
            vehicle.name,
            vehicle.vehicle_id,
            charger.name,
        )
        return sensor

    def register_vehicles(
        self,
        pairs: list[VehicleChargerPair],
    ) -> list[VehicleChargingSensor]:
        """Zarejestruj wiele par pojazd-ładowarka.

        Args:
            pairs: Lista par pojazd-ładowarka.

        Returns:
            Lista utworzonych sensorów.
        """
        sensors = []
        for pair in pairs:
            sensor = self.register_vehicle(pair.vehicle, pair.charger)
            sensors.append(sensor)
        return sensors

    def update_schedules(
        self,
        schedules: list[ChargingSchedule],
    ) -> None:
        """Aktualizuj harmonogramy dla wszystkich pojazdów.

        Powiadamia użytkownika gdy ładowanie jest odroczone.

        Args:
            schedules: Lista harmonogramów (jeden per pojazd).
        """
        for schedule in schedules:
            sensor = self._sensors.get(schedule.vehicle_id)
            if sensor is None:
                continue

            old_status = sensor.state
            sensor.update_schedule(schedule)

            # Notify user when charging is deferred due to power constraints
            if sensor.state == "deferred" and old_status != "deferred":
                self._notify_deferred(sensor, schedule)

    def notify_power_constraint_deferral(
        self,
        vehicle_id: str,
        reason: str,
    ) -> None:
        """Powiadom o odroczeniu ładowania z powodu ograniczeń mocy.

        Args:
            vehicle_id: ID pojazdu.
            reason: Powód odroczenia.
        """
        sensor = self._sensors.get(vehicle_id)
        if sensor is None:
            return

        sensor.set_deferred(reason)

        if self._notify_callback:
            self._notify_callback(
                "PEO: Ładowanie odroczone",
                f"Ładowanie pojazdu {sensor._vehicle.name} zostało odroczone. "
                f"Powód: {reason}",
            )

        _LOGGER.warning(
            "Ładowanie pojazdu %s odroczone: %s",
            vehicle_id,
            reason,
        )

    def get_sensor(self, vehicle_id: str) -> Optional[VehicleChargingSensor]:
        """Pobierz sensor dla pojazdu.

        Args:
            vehicle_id: ID pojazdu.

        Returns:
            Sensor lub None.
        """
        return self._sensors.get(vehicle_id)

    def get_all_attributes(self) -> list[dict[str, Any]]:
        """Pobierz atrybuty wszystkich sensorów.

        Returns:
            Lista słowników z atrybutami sensorów.
        """
        return [
            sensor.extra_state_attributes
            for sensor in self._sensors.values()
        ]

    def _notify_deferred(
        self,
        sensor: VehicleChargingSensor,
        schedule: ChargingSchedule,
    ) -> None:
        """Wyślij powiadomienie o odroczeniu ładowania.

        Args:
            sensor: Sensor pojazdu.
            schedule: Harmonogram (infeasible).
        """
        if self._notify_callback is None:
            return

        best_soc = schedule.best_achievable_soc
        message = (
            f"Ładowanie pojazdu {sensor._vehicle.name} zostało odroczone "
            f"z powodu ograniczeń mocy. "
        )
        if best_soc is not None:
            message += (
                f"Najlepszy osiągalny SoC: {best_soc}% "
                f"(cel: {sensor._vehicle.target_soc}%)."
            )

        self._notify_callback("PEO: Ładowanie odroczone", message)

        _LOGGER.warning(
            "Ładowanie pojazdu %s odroczone — best_achievable_soc=%s%%",
            sensor.vehicle_id,
            best_soc,
        )
