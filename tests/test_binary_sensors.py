"""Unit tests for PEO binary_sensors.py.

Tests binary sensors, schedule sensor, and event firing.

Requirements: 12.2, 12.5, 12.6
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from decimal import Decimal

from custom_components.peo.binary_sensors import (
    CheapWindowBinarySensor,
    EVChargingActiveBinarySensor,
    PVSurplusActiveBinarySensor,
    PEOScheduleSensor,
    fire_load_shifted_event,
    async_setup_binary_sensors,
)
from custom_components.peo.const import (
    DOMAIN,
    CONF_MODULES_ENABLED,
    CONF_PRICE_THRESHOLD_CHEAP,
    EVENT_CHARGING_STARTED,
    EVENT_CHARGING_COMPLETED,
    EVENT_LOAD_SHIFTED,
    EVENT_PRICE_THRESHOLD_CROSSED,
    EVENT_SCHEDULE_UPDATED,
    MODULE_PRICES,
    MODULE_EV,
    MODULE_PV,
)


def _make_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    return hass


def _make_entry(entry_id="test_entry", options=None, data=None):
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.options = options or {}
    entry.data = data or {CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_EV, MODULE_PV]}
    return entry


class TestCheapWindowBinarySensor:
    """Tests for CheapWindowBinarySensor."""

    def test_initial_state_is_off(self):
        """Sensor starts in OFF state."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = CheapWindowBinarySensor(hass, entry)
        assert sensor.is_on is False

    def test_on_when_price_below_threshold(self):
        """Sensor is ON when price is below threshold."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.30"))

        assert sensor.is_on is True

    def test_off_when_price_above_threshold(self):
        """Sensor is OFF when price is at or above threshold."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.50"))

        assert sensor.is_on is False

    def test_off_when_price_equals_threshold(self):
        """Sensor is OFF when price equals threshold (not strictly below)."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.40"))

        assert sensor.is_on is False

    def test_fires_event_on_threshold_crossing_below(self):
        """Fires peo_price_threshold_crossed when price drops below threshold."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        # Start above threshold
        sensor.update_price(Decimal("0.50"))
        hass.bus.async_fire.reset_mock()

        # Drop below threshold
        sensor.update_price(Decimal("0.30"))

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_PRICE_THRESHOLD_CROSSED
        assert call_args[0][1]["direction"] == "below"

    def test_fires_event_on_threshold_crossing_above(self):
        """Fires peo_price_threshold_crossed when price rises above threshold."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        # Start below threshold
        sensor.update_price(Decimal("0.30"))
        hass.bus.async_fire.reset_mock()

        # Rise above threshold
        sensor.update_price(Decimal("0.50"))

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_PRICE_THRESHOLD_CROSSED
        assert call_args[0][1]["direction"] == "above"

    def test_no_event_when_state_unchanged(self):
        """No event fired when state doesn't change."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.30"))
        hass.bus.async_fire.reset_mock()

        # Still below threshold
        sensor.update_price(Decimal("0.25"))

        hass.bus.async_fire.assert_not_called()

    def test_update_threshold(self):
        """Updating threshold recalculates state."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.35"))
        assert sensor.is_on is True

        # Raise threshold below current price
        sensor.update_threshold(Decimal("0.30"))
        assert sensor.is_on is False

    def test_has_correct_attributes(self):
        """Sensor exposes correct extra state attributes."""
        hass = _make_hass()
        entry = _make_entry(options={CONF_PRICE_THRESHOLD_CHEAP: "0.40"})
        sensor = CheapWindowBinarySensor(hass, entry)

        sensor.update_price(Decimal("0.35"))

        attrs = sensor.extra_state_attributes
        assert "current_price_pln_kwh" in attrs
        assert "threshold_pln_kwh" in attrs
        assert "last_updated" in attrs
        assert attrs["current_price_pln_kwh"] == "0.35"
        assert attrs["threshold_pln_kwh"] == "0.40"

    def test_unique_id_format(self):
        """Sensor has correct unique_id format."""
        hass = _make_hass()
        entry = _make_entry(entry_id="abc123")
        sensor = CheapWindowBinarySensor(hass, entry)

        assert sensor.unique_id == "peo_abc123_cheap_window"

    def test_device_info(self):
        """Sensor provides device_info."""
        hass = _make_hass()
        entry = _make_entry(entry_id="abc123")
        sensor = CheapWindowBinarySensor(hass, entry)

        info = sensor.device_info
        assert "identifiers" in info
        assert "name" in info


class TestEVChargingActiveBinarySensor:
    """Tests for EVChargingActiveBinarySensor."""

    def test_initial_state_is_off(self):
        """Sensor starts in OFF state."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)
        assert sensor.is_on is False

    def test_set_charging_active(self):
        """Setting charging active turns sensor ON."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        sensor.set_charging_active(True, "ev_1")

        assert sensor.is_on is True

    def test_fires_charging_started_event(self):
        """Fires peo_charging_started when charging begins."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        sensor.set_charging_active(True, "ev_1")

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_CHARGING_STARTED
        assert call_args[0][1]["vehicle_id"] == "ev_1"
        assert "timestamp" in call_args[0][1]
        assert "entity_id" in call_args[0][1]

    def test_fires_charging_completed_event(self):
        """Fires peo_charging_completed when charging stops."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        sensor.set_charging_active(True, "ev_1")
        hass.bus.async_fire.reset_mock()

        sensor.set_charging_active(False, "ev_1")

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_CHARGING_COMPLETED
        assert call_args[0][1]["vehicle_id"] == "ev_1"

    def test_no_event_when_already_active(self):
        """No event when setting active while already active."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = EVChargingActiveBinarySensor(hass, entry)

        sensor.set_charging_active(True, "ev_1")
        hass.bus.async_fire.reset_mock()

        sensor.set_charging_active(True, "ev_1")

        hass.bus.async_fire.assert_not_called()

    def test_unique_id_format(self):
        """Sensor has correct unique_id."""
        hass = _make_hass()
        entry = _make_entry(entry_id="xyz")
        sensor = EVChargingActiveBinarySensor(hass, entry)
        assert sensor.unique_id == "peo_xyz_ev_charging_active"


class TestPVSurplusActiveBinarySensor:
    """Tests for PVSurplusActiveBinarySensor."""

    def test_initial_state_is_off(self):
        """Sensor starts in OFF state."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)
        assert sensor.is_on is False

    def test_on_when_production_exceeds_consumption(self):
        """Sensor is ON when PV production > consumption."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)

        sensor.update_pv_status(production_kw=5.0, consumption_kw=3.0)

        assert sensor.is_on is True

    def test_off_when_consumption_exceeds_production(self):
        """Sensor is OFF when consumption > PV production."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)

        sensor.update_pv_status(production_kw=2.0, consumption_kw=4.0)

        assert sensor.is_on is False

    def test_off_when_equal(self):
        """Sensor is OFF when production equals consumption."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)

        sensor.update_pv_status(production_kw=3.0, consumption_kw=3.0)

        assert sensor.is_on is False

    def test_attributes_include_surplus(self):
        """Attributes include surplus_kw calculation."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)

        sensor.update_pv_status(production_kw=7.5, consumption_kw=3.2)

        attrs = sensor.extra_state_attributes
        assert attrs["production_kw"] == 7.5
        assert attrs["consumption_kw"] == 3.2
        assert attrs["surplus_kw"] == 4.3

    def test_surplus_never_negative(self):
        """Surplus attribute is never negative."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PVSurplusActiveBinarySensor(hass, entry)

        sensor.update_pv_status(production_kw=1.0, consumption_kw=5.0)

        attrs = sensor.extra_state_attributes
        assert attrs["surplus_kw"] == 0.0


class TestPEOScheduleSensor:
    """Tests for PEOScheduleSensor."""

    def test_initial_state_is_idle(self):
        """Sensor starts in idle state."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)
        assert sensor.state == "idle"

    def test_update_hourly_prices(self):
        """Updating hourly prices changes state to active."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)

        prices = [{"hour": i, "price": 0.3 + i * 0.01} for i in range(24)]
        sensor.update_hourly_prices(prices)

        assert sensor.state == "active"
        attrs = sensor.extra_state_attributes
        assert len(attrs["hourly_prices"]) == 24
        assert attrs["last_updated"] is not None

    def test_update_hourly_prices_truncates_to_24(self):
        """Hourly prices are truncated to 24 entries."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)

        prices = [{"hour": i, "price": 0.3} for i in range(30)]
        sensor.update_hourly_prices(prices)

        attrs = sensor.extra_state_attributes
        assert len(attrs["hourly_prices"]) == 24

    def test_update_schedule(self):
        """Updating schedule fires event and changes state."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)

        schedule = {
            "type": "ev_charging",
            "windows": [{"start": "22:00", "end": "06:00", "power_kw": 11}],
        }
        sensor.update_schedule(schedule)

        assert sensor.state == "active"
        attrs = sensor.extra_state_attributes
        assert attrs["schedule"] == schedule
        hass.bus.async_fire.assert_called_once()

    def test_schedule_event_has_required_fields(self):
        """Schedule update event contains timestamp and entity_id."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)

        sensor.update_schedule({"type": "loads"})

        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_SCHEDULE_UPDATED
        event_data = call_args[0][1]
        assert "timestamp" in event_data
        assert "entity_id" in event_data
        assert "schedule_type" in event_data

    def test_unique_id_format(self):
        """Sensor has correct unique_id."""
        hass = _make_hass()
        entry = _make_entry(entry_id="test123")
        sensor = PEOScheduleSensor(hass, entry)
        assert sensor.unique_id == "peo_test123_schedule"

    def test_device_info(self):
        """Sensor provides device_info."""
        hass = _make_hass()
        entry = _make_entry()
        sensor = PEOScheduleSensor(hass, entry)
        info = sensor.device_info
        assert "identifiers" in info
        assert "name" in info


class TestFireLoadShiftedEvent:
    """Tests for fire_load_shifted_event helper."""

    def test_fires_event_with_all_fields(self):
        """Event contains all required fields."""
        hass = _make_hass()

        fire_load_shifted_event(
            hass,
            load_id="load_cwu",
            entity_id="switch.bojler",
            action="on",
            reason="Cena poniżej progu",
            cost_pln_kwh="0.35",
        )

        hass.bus.async_fire.assert_called_once()
        call_args = hass.bus.async_fire.call_args
        assert call_args[0][0] == EVENT_LOAD_SHIFTED
        event_data = call_args[0][1]
        assert "timestamp" in event_data
        assert event_data["entity_id"] == "switch.bojler"
        assert event_data["load_id"] == "load_cwu"
        assert event_data["action"] == "on"
        assert event_data["reason"] == "Cena poniżej progu"
        assert event_data["cost_pln_kwh"] == "0.35"


class TestAsyncSetupBinarySensors:
    """Tests for async_setup_binary_sensors."""

    @pytest.mark.asyncio
    async def test_creates_sensors_for_all_modules(self):
        """Creates all sensors when all modules enabled."""
        hass = _make_hass()
        hass.data = {DOMAIN: {"test_entry": {}}}
        entry = _make_entry(data={
            CONF_MODULES_ENABLED: [MODULE_PRICES, MODULE_EV, MODULE_PV]
        })

        sensors = await async_setup_binary_sensors(hass, entry)

        # Should have: cheap_window, ev_charging, pv_surplus, schedule
        assert len(sensors) == 4

    @pytest.mark.asyncio
    async def test_creates_minimal_sensors(self):
        """Creates only schedule sensor when no modules enabled."""
        hass = _make_hass()
        hass.data = {DOMAIN: {"test_entry": {}}}
        entry = _make_entry(data={CONF_MODULES_ENABLED: []})

        sensors = await async_setup_binary_sensors(hass, entry)

        # Only schedule sensor
        assert len(sensors) == 1

    @pytest.mark.asyncio
    async def test_creates_cheap_window_for_prices_module(self):
        """Creates cheap window sensor when prices module enabled."""
        hass = _make_hass()
        hass.data = {DOMAIN: {"test_entry": {}}}
        entry = _make_entry(data={CONF_MODULES_ENABLED: [MODULE_PRICES]})

        sensors = await async_setup_binary_sensors(hass, entry)

        sensor_types = [type(s).__name__ for s in sensors]
        assert "CheapWindowBinarySensor" in sensor_types
