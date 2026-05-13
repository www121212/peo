"""Unit tests for vehicle_sensors module.

Tests multi-vehicle sensor exposure and deferral notifications.
Requirements: 11.5, 11.6
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from custom_components.peo.vehicle_sensors import (
    VehicleChargingSensor,
    VehicleSensorManager,
)
from custom_components.peo.models import (
    ChargingSchedule,
    TimeWindow,
    VehicleConfig,
    ChargerConfig,
    VehicleChargerPair,
)
from custom_components.peo.enums import ChargingStrategy


# --- Fixtures ---

def _make_vehicle(
    vehicle_id: str = "ev_1",
    name: str = "Tesla Model 3",
    target_soc: int = 80,
    priority: int = 1,
) -> VehicleConfig:
    """Create a test VehicleConfig."""
    return VehicleConfig(
        vehicle_id=vehicle_id,
        name=name,
        battery_capacity_kwh=60.0,
        max_charging_power_kw=11.0,
        min_charging_power_kw=1.4,
        soc_entity_id=f"sensor.{vehicle_id}_soc",
        target_soc=target_soc,
        deadline=None,
        priority=priority,
        strategy=ChargingStrategy.CHEAPEST,
    )


def _make_charger(
    charger_id: str = "charger_1",
    name: str = "Wallbox Pulsar",
) -> ChargerConfig:
    """Create a test ChargerConfig."""
    return ChargerConfig(
        charger_id=charger_id,
        name=name,
        protocol="wallbox",
        host="192.168.1.100",
        api_key="test_key",
        entity_id=None,
        max_power_kw=22.0,
        max_current_a=32.0,
    )


def _make_schedule(
    vehicle_id: str = "ev_1",
    is_feasible: bool = True,
    windows: list[TimeWindow] | None = None,
    cost: Decimal = Decimal("15.50"),
) -> ChargingSchedule:
    """Create a test ChargingSchedule."""
    now = datetime.now(timezone.utc)
    if windows is None and is_feasible:
        windows = [
            TimeWindow(
                start=now + timedelta(hours=1),
                end=now + timedelta(hours=3),
                power_kw=7.4,
            )
        ]
    elif windows is None:
        windows = []

    return ChargingSchedule(
        vehicle_id=vehicle_id,
        windows=windows,
        estimated_cost_pln=cost,
        estimated_energy_kwh=14.8,
        estimated_completion=now + timedelta(hours=3) if windows else now,
        is_feasible=is_feasible,
        best_achievable_soc=60 if not is_feasible else None,
    )


# --- VehicleChargingSensor Tests ---

class TestVehicleChargingSensor:
    """Tests for VehicleChargingSensor class."""

    def test_initial_state_is_idle(self):
        """Sensor starts in idle state."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        assert sensor.state == "idle"
        assert sensor.vehicle_id == "ev_1"
        assert sensor.charger_id == "charger_1"

    def test_unique_id_includes_vehicle_and_charger(self):
        """Unique ID includes vehicle and charger IDs."""
        vehicle = _make_vehicle(vehicle_id="ev_2")
        charger = _make_charger(charger_id="charger_3")
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        assert "ev_2" in sensor.unique_id
        assert "charger_3" in sensor.unique_id

    def test_update_schedule_sets_scheduled_status(self):
        """Updating with feasible schedule sets status to 'scheduled'."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        schedule = _make_schedule(is_feasible=True)
        sensor.update_schedule(schedule)

        assert sensor.state == "scheduled"
        attrs = sensor.extra_state_attributes
        assert len(attrs["planned_windows"]) > 0
        assert attrs["estimated_cost_pln"] == "15.50"
        assert attrs["is_deferred"] is False

    def test_update_schedule_infeasible_sets_deferred(self):
        """Updating with infeasible schedule sets status to 'deferred'."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        schedule = _make_schedule(is_feasible=False)
        sensor.update_schedule(schedule)

        assert sensor.state == "deferred"
        attrs = sensor.extra_state_attributes
        assert attrs["is_deferred"] is True
        assert attrs["defer_reason"] is not None

    def test_set_charging_active(self):
        """set_charging_active updates status and power."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        sensor.set_charging_active(7.4)

        assert sensor.state == "charging"
        attrs = sensor.extra_state_attributes
        assert attrs["allocated_power_kw"] == 7.4
        assert attrs["is_deferred"] is False

    def test_set_charging_completed(self):
        """set_charging_completed updates status."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        sensor.set_charging_active(7.4)
        sensor.set_charging_completed()

        assert sensor.state == "completed"
        attrs = sensor.extra_state_attributes
        assert attrs["allocated_power_kw"] == 0.0

    def test_set_deferred_with_reason(self):
        """set_deferred sets status and reason."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        sensor.set_deferred("Przekroczony limit mocy przyłączeniowej")

        assert sensor.state == "deferred"
        attrs = sensor.extra_state_attributes
        assert attrs["is_deferred"] is True
        assert "limit mocy" in attrs["defer_reason"]

    def test_set_idle_resets_state(self):
        """set_idle resets all state to defaults."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        sensor.set_charging_active(11.0)
        sensor.set_idle()

        assert sensor.state == "idle"
        attrs = sensor.extra_state_attributes
        assert attrs["allocated_power_kw"] == 0.0
        assert attrs["is_deferred"] is False

    def test_extra_state_attributes_contain_all_fields(self):
        """Extra state attributes contain all required fields."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        attrs = sensor.extra_state_attributes
        required_keys = [
            "vehicle_id", "vehicle_name", "charger_id", "charger_name",
            "charging_status", "planned_windows", "estimated_cost_pln",
            "estimated_completion", "allocated_power_kw", "is_deferred",
            "defer_reason", "target_soc", "priority", "strategy",
            "last_updated",
        ]
        for key in required_keys:
            assert key in attrs, f"Missing attribute: {key}"

    def test_device_info_structure(self):
        """Device info has correct structure."""
        vehicle = _make_vehicle()
        charger = _make_charger()
        sensor = VehicleChargingSensor(vehicle, charger, "entry_1")

        info = sensor.device_info
        assert "identifiers" in info
        assert "name" in info
        assert "manufacturer" in info


# --- VehicleSensorManager Tests ---

class TestVehicleSensorManager:
    """Tests for VehicleSensorManager class."""

    def test_register_vehicle_creates_sensor(self):
        """Registering a vehicle creates a sensor."""
        manager = VehicleSensorManager(entry_id="entry_1")
        vehicle = _make_vehicle()
        charger = _make_charger()

        sensor = manager.register_vehicle(vehicle, charger)

        assert sensor is not None
        assert sensor.vehicle_id == "ev_1"
        assert "ev_1" in manager.sensors

    def test_register_multiple_vehicles(self):
        """Registering multiple vehicles creates separate sensors."""
        manager = VehicleSensorManager(entry_id="entry_1")

        v1 = _make_vehicle(vehicle_id="ev_1", name="Tesla")
        v2 = _make_vehicle(vehicle_id="ev_2", name="BMW")
        c1 = _make_charger(charger_id="c1")
        c2 = _make_charger(charger_id="c2")

        manager.register_vehicle(v1, c1)
        manager.register_vehicle(v2, c2)

        assert len(manager.sensors) == 2
        assert "ev_1" in manager.sensors
        assert "ev_2" in manager.sensors

    def test_register_vehicles_from_pairs(self):
        """register_vehicles creates sensors from VehicleChargerPair list."""
        manager = VehicleSensorManager(entry_id="entry_1")

        pairs = [
            VehicleChargerPair(
                vehicle=_make_vehicle(vehicle_id="ev_1"),
                charger=_make_charger(charger_id="c1"),
            ),
            VehicleChargerPair(
                vehicle=_make_vehicle(vehicle_id="ev_2"),
                charger=_make_charger(charger_id="c2"),
            ),
        ]

        sensors = manager.register_vehicles(pairs)
        assert len(sensors) == 2

    def test_update_schedules_updates_sensors(self):
        """update_schedules updates all matching sensors."""
        manager = VehicleSensorManager(entry_id="entry_1")
        manager.register_vehicle(_make_vehicle("ev_1"), _make_charger("c1"))
        manager.register_vehicle(_make_vehicle("ev_2"), _make_charger("c2"))

        schedules = [
            _make_schedule(vehicle_id="ev_1", is_feasible=True),
            _make_schedule(vehicle_id="ev_2", is_feasible=True),
        ]
        manager.update_schedules(schedules)

        assert manager.sensors["ev_1"].state == "scheduled"
        assert manager.sensors["ev_2"].state == "scheduled"

    def test_notify_on_deferral(self):
        """Notifies user when charging is deferred."""
        notify_mock = MagicMock()
        manager = VehicleSensorManager(
            entry_id="entry_1",
            notify_callback=notify_mock,
        )
        manager.register_vehicle(
            _make_vehicle("ev_1", name="Tesla"),
            _make_charger("c1"),
        )

        # First set to non-deferred state
        manager.sensors["ev_1"].set_idle()

        # Now update with infeasible schedule
        schedules = [_make_schedule(vehicle_id="ev_1", is_feasible=False)]
        manager.update_schedules(schedules)

        # Should have notified
        assert notify_mock.called
        call_args = notify_mock.call_args
        assert "odroczone" in call_args[0][0].lower() or "odroczone" in call_args[0][1].lower()

    def test_notify_power_constraint_deferral(self):
        """notify_power_constraint_deferral sets deferred and notifies."""
        notify_mock = MagicMock()
        manager = VehicleSensorManager(
            entry_id="entry_1",
            notify_callback=notify_mock,
        )
        manager.register_vehicle(
            _make_vehicle("ev_1", name="Tesla"),
            _make_charger("c1"),
        )

        manager.notify_power_constraint_deferral(
            "ev_1", "Przekroczony limit mocy"
        )

        assert manager.sensors["ev_1"].state == "deferred"
        assert notify_mock.called

    def test_get_sensor_returns_correct_sensor(self):
        """get_sensor returns the correct sensor by vehicle_id."""
        manager = VehicleSensorManager(entry_id="entry_1")
        manager.register_vehicle(_make_vehicle("ev_1"), _make_charger("c1"))

        sensor = manager.get_sensor("ev_1")
        assert sensor is not None
        assert sensor.vehicle_id == "ev_1"

    def test_get_sensor_returns_none_for_unknown(self):
        """get_sensor returns None for unknown vehicle_id."""
        manager = VehicleSensorManager(entry_id="entry_1")
        assert manager.get_sensor("unknown") is None

    def test_get_all_attributes(self):
        """get_all_attributes returns attributes for all sensors."""
        manager = VehicleSensorManager(entry_id="entry_1")
        manager.register_vehicle(_make_vehicle("ev_1"), _make_charger("c1"))
        manager.register_vehicle(_make_vehicle("ev_2"), _make_charger("c2"))

        attrs = manager.get_all_attributes()
        assert len(attrs) == 2
        assert all("vehicle_id" in a for a in attrs)
