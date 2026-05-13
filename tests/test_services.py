"""Unit tests for PEO services.py.

Tests service registration, parameter validation, and service handlers.

Requirements: 12.1, 12.3, 12.4
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone

import voluptuous as vol

from custom_components.peo.services import (
    async_register_services,
    async_unregister_services,
    ServiceValidationError,
    SCHEMA_START_EV_CHARGING,
    SCHEMA_STOP_EV_CHARGING,
    SCHEMA_SET_LOAD_THRESHOLD,
    SCHEMA_FORCE_LOAD_ON,
    SCHEMA_FORCE_LOAD_OFF,
    SCHEMA_RECALCULATE_SCHEDULE,
    _get_runtime_data,
)
from custom_components.peo.const import (
    DOMAIN,
    SERVICE_START_EV_CHARGING,
    SERVICE_STOP_EV_CHARGING,
    SERVICE_SET_LOAD_THRESHOLD,
    SERVICE_FORCE_LOAD_ON,
    SERVICE_FORCE_LOAD_OFF,
    SERVICE_RECALCULATE_SCHEDULE,
)


def _make_hass():
    """Create a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.services.async_remove = MagicMock()
    return hass


def _make_entry(entry_id="test_entry"):
    """Create a mock ConfigEntry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {}
    entry.options = {}
    return entry


class TestServiceSchemaValidation:
    """Tests for service parameter schema validation."""

    def test_start_ev_charging_valid_params(self):
        """Valid start_ev_charging params pass schema validation."""
        result = SCHEMA_START_EV_CHARGING({
            "vehicle_id": "ev_1",
            "power_kw": 11.0,
            "target_soc": 80,
        })
        assert result["vehicle_id"] == "ev_1"
        assert result["power_kw"] == 11.0
        assert result["target_soc"] == 80

    def test_start_ev_charging_minimal_params(self):
        """Minimal start_ev_charging params (only vehicle_id) pass."""
        result = SCHEMA_START_EV_CHARGING({"vehicle_id": "ev_1"})
        assert result["vehicle_id"] == "ev_1"

    def test_start_ev_charging_invalid_power_too_low(self):
        """Power below 1.4 kW is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_START_EV_CHARGING({
                "vehicle_id": "ev_1",
                "power_kw": 0.5,
            })

    def test_start_ev_charging_invalid_power_too_high(self):
        """Power above 22 kW is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_START_EV_CHARGING({
                "vehicle_id": "ev_1",
                "power_kw": 50.0,
            })

    def test_start_ev_charging_invalid_soc_too_low(self):
        """Target SoC below 10 is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_START_EV_CHARGING({
                "vehicle_id": "ev_1",
                "target_soc": 5,
            })

    def test_start_ev_charging_invalid_soc_too_high(self):
        """Target SoC above 100 is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_START_EV_CHARGING({
                "vehicle_id": "ev_1",
                "target_soc": 110,
            })

    def test_start_ev_charging_missing_vehicle_id(self):
        """Missing vehicle_id is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_START_EV_CHARGING({"power_kw": 11.0})

    def test_stop_ev_charging_valid(self):
        """Valid stop_ev_charging params pass."""
        result = SCHEMA_STOP_EV_CHARGING({"vehicle_id": "ev_1"})
        assert result["vehicle_id"] == "ev_1"

    def test_stop_ev_charging_missing_vehicle_id(self):
        """Missing vehicle_id is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_STOP_EV_CHARGING({})

    def test_set_load_threshold_valid(self):
        """Valid set_load_threshold params pass."""
        result = SCHEMA_SET_LOAD_THRESHOLD({
            "load_id": "load_1",
            "threshold_on": 0.35,
            "threshold_off": 0.55,
        })
        assert result["load_id"] == "load_1"
        assert result["threshold_on"] == 0.35
        assert result["threshold_off"] == 0.55

    def test_set_load_threshold_invalid_range(self):
        """Threshold outside 0.01-5.0 is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_SET_LOAD_THRESHOLD({
                "load_id": "load_1",
                "threshold_on": 10.0,
            })

    def test_set_load_threshold_negative(self):
        """Negative threshold is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_SET_LOAD_THRESHOLD({
                "load_id": "load_1",
                "threshold_on": -0.5,
            })

    def test_force_load_on_valid(self):
        """Valid force_load_on params pass."""
        result = SCHEMA_FORCE_LOAD_ON({
            "load_id": "load_cwu",
            "duration_minutes": 60,
        })
        assert result["load_id"] == "load_cwu"
        assert result["duration_minutes"] == 60

    def test_force_load_on_invalid_duration(self):
        """Duration outside 1-1440 is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_FORCE_LOAD_ON({
                "load_id": "load_1",
                "duration_minutes": 0,
            })

    def test_force_load_off_valid(self):
        """Valid force_load_off params pass."""
        result = SCHEMA_FORCE_LOAD_OFF({"load_id": "load_1"})
        assert result["load_id"] == "load_1"

    def test_recalculate_schedule_valid(self):
        """Valid recalculate_schedule params pass."""
        result = SCHEMA_RECALCULATE_SCHEDULE({"modules": ["all"]})
        assert result["modules"] == ["all"]

    def test_recalculate_schedule_empty(self):
        """Empty recalculate_schedule params pass (defaults to all)."""
        result = SCHEMA_RECALCULATE_SCHEDULE({})
        assert "modules" not in result

    def test_recalculate_schedule_invalid_module(self):
        """Invalid module name is rejected."""
        with pytest.raises(vol.Invalid):
            SCHEMA_RECALCULATE_SCHEDULE({"modules": ["invalid_module"]})


class TestServiceRegistration:
    """Tests for service registration."""

    @pytest.mark.asyncio
    async def test_registers_all_six_services(self):
        """All 6 PEO services are registered."""
        hass = _make_hass()
        entry = _make_entry()

        await async_register_services(hass, entry)

        assert hass.services.async_register.call_count == 6

    @pytest.mark.asyncio
    async def test_does_not_register_twice(self):
        """Services are not registered if already present."""
        hass = _make_hass()
        hass.services.has_service = MagicMock(return_value=True)
        entry = _make_entry()

        await async_register_services(hass, entry)

        hass.services.async_register.assert_not_called()

    @pytest.mark.asyncio
    async def test_unregister_services(self):
        """All services are unregistered."""
        hass = _make_hass()

        await async_unregister_services(hass)

        assert hass.services.async_remove.call_count == 6


class TestServiceValidationError:
    """Tests for ServiceValidationError."""

    def test_error_has_message(self):
        """ServiceValidationError stores message."""
        err = ServiceValidationError("Test error message")
        assert err.message == "Test error message"
        assert str(err) == "Test error message"


class TestGetRuntimeData:
    """Tests for _get_runtime_data helper."""

    def test_returns_none_when_no_domain(self):
        """Returns None when DOMAIN not in hass.data."""
        hass = MagicMock()
        hass.data = {}
        assert _get_runtime_data(hass) is None

    def test_returns_none_when_empty_domain(self):
        """Returns None when DOMAIN data is empty."""
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        assert _get_runtime_data(hass) is None

    def test_returns_first_entry_data(self):
        """Returns runtime data from first active entry."""
        hass = MagicMock()
        runtime = {"coordinators": {}, "listeners": []}
        hass.data = {DOMAIN: {"entry_1": runtime}}
        assert _get_runtime_data(hass) == runtime
