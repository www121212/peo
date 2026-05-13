"""Unit tests for PEOConfigFlow.

Tests cover:
- Multi-step flow (user -> tariff -> ev -> loads -> pv)
- Module selection validation (at least one required)
- Tariff configuration with OSD operator
- EV configuration validation
- Load configuration validation
- PV configuration validation
- Quick setup mode
- Polish error messages
- Partial configuration preservation

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9
"""

import pytest
import asyncio

from custom_components.peo.config_flow import (
    PEOConfigFlow,
    _validate_modules,
    _validate_tariff_config,
    _validate_ev_config,
    _validate_load_config,
    _validate_pv_config,
    DEFAULT_RATES,
    DEFAULT_LOAD_CWU,
    MAX_CONFIG_LOADS,
)
from custom_components.peo.const import (
    CONF_MODULES_ENABLED,
    CONF_TARIFF_TYPE,
    CONF_OSD_OPERATOR,
    CONF_TARIFF_RATES,
    CONF_EV_VEHICLES,
    CONF_LOADS,
    CONF_GRID_LIMIT_KW,
    CONF_PV,
    CONF_SOLAR_PROVIDER,
    CONF_SOLAR_API_KEY,
    MODULE_PRICES,
    MODULE_TARIFF,
    MODULE_EV,
    MODULE_LOADS,
    MODULE_PV,
)
from custom_components.peo.enums import (
    TariffType,
    OSDOperator,
    SolarProvider,
    ChargingStrategy,
)


# --- Helper to run async tests ---
def run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- Module Validation Tests ---


class TestModuleValidation:
    """Tests for module selection validation (Requirement 7.9)."""

    def test_empty_modules_returns_error(self):
        """No modules selected returns Polish error message."""
        result = _validate_modules([])
        assert result is not None
        assert "co najmniej jeden moduł" in result

    def test_valid_single_module(self):
        """Single valid module passes validation."""
        result = _validate_modules([MODULE_PRICES])
        assert result is None

    def test_valid_multiple_modules(self):
        """Multiple valid modules pass validation."""
        result = _validate_modules([MODULE_PRICES, MODULE_TARIFF, MODULE_EV])
        assert result is None

    def test_unknown_module_returns_error(self):
        """Unknown module returns Polish error message."""
        result = _validate_modules(["unknown_module"])
        assert result is not None
        assert "Nieznany moduł" in result


# --- Tariff Validation Tests ---


class TestTariffValidation:
    """Tests for tariff configuration validation (Requirement 7.3)."""

    def test_missing_osd_operator(self):
        """Missing OSD operator returns error."""
        errors = _validate_tariff_config({"tariff_type": "G12"})
        assert "osd_operator" in errors

    def test_missing_tariff_type(self):
        """Missing tariff type returns error."""
        errors = _validate_tariff_config({"osd_operator": "tauron"})
        assert "tariff_type" in errors

    def test_invalid_osd_operator(self):
        """Invalid OSD operator returns Polish error."""
        errors = _validate_tariff_config({
            "osd_operator": "invalid",
            "tariff_type": "G12",
        })
        assert "osd_operator" in errors
        assert "Nieznany operator" in errors["osd_operator"]

    def test_invalid_tariff_type(self):
        """Invalid tariff type returns Polish error."""
        errors = _validate_tariff_config({
            "osd_operator": "tauron",
            "tariff_type": "INVALID",
        })
        assert "tariff_type" in errors
        assert "Nieznany typ taryfy" in errors["tariff_type"]

    def test_valid_tariff_config(self):
        """Valid tariff configuration passes."""
        errors = _validate_tariff_config({
            "osd_operator": "tauron",
            "tariff_type": "G12",
        })
        assert errors == {}

    def test_invalid_rate_value(self):
        """Rate value out of range returns error."""
        errors = _validate_tariff_config({
            "osd_operator": "tauron",
            "tariff_type": "G12",
            "energy_price": "10.00",  # > 5 PLN/kWh
        })
        assert "energy_price" in errors

    def test_valid_rate_values(self):
        """Valid rate values pass validation."""
        errors = _validate_tariff_config({
            "osd_operator": "tauron",
            "tariff_type": "G12",
            "energy_price": "0.45",
            "distribution_variable": "0.21",
        })
        assert errors == {}


# --- EV Validation Tests ---


class TestEVValidation:
    """Tests for EV configuration validation (Requirement 7.3)."""

    def test_missing_vehicle_name(self):
        """Missing vehicle name returns error."""
        errors = _validate_ev_config({
            "soc_entity_id": "sensor.ev_soc",
        })
        assert "vehicle_name" in errors

    def test_missing_soc_entity(self):
        """Missing SoC entity returns error."""
        errors = _validate_ev_config({
            "vehicle_name": "Tesla",
        })
        assert "soc_entity_id" in errors

    def test_invalid_battery_capacity(self):
        """Battery capacity out of range returns error."""
        errors = _validate_ev_config({
            "vehicle_name": "Tesla",
            "soc_entity_id": "sensor.ev_soc",
            "battery_capacity_kwh": "500",  # > 200
        })
        assert "battery_capacity_kwh" in errors

    def test_invalid_power(self):
        """Power out of range returns error."""
        errors = _validate_ev_config({
            "vehicle_name": "Tesla",
            "soc_entity_id": "sensor.ev_soc",
            "max_charging_power_kw": "200",  # > 100 kW
        })
        assert "max_charging_power_kw" in errors

    def test_invalid_soc_target(self):
        """SoC target out of range returns error."""
        errors = _validate_ev_config({
            "vehicle_name": "Tesla",
            "soc_entity_id": "sensor.ev_soc",
            "target_soc": "5",  # < 10
        })
        assert "target_soc" in errors

    def test_valid_ev_config(self):
        """Valid EV configuration passes."""
        errors = _validate_ev_config({
            "vehicle_name": "Tesla Model 3",
            "soc_entity_id": "sensor.tesla_soc",
            "battery_capacity_kwh": "60",
            "max_charging_power_kw": "11",
            "target_soc": "80",
        })
        assert errors == {}


# --- Load Validation Tests ---


class TestLoadValidation:
    """Tests for load configuration validation (Requirement 7.3, 7.5)."""

    def test_missing_load_name(self):
        """Missing load name returns error."""
        errors = _validate_load_config({
            "entity_id": "switch.bojler",
        })
        assert "load_name" in errors

    def test_missing_entity_id(self):
        """Missing entity_id returns error."""
        errors = _validate_load_config({
            "load_name": "Bojler",
        })
        assert "entity_id" in errors

    def test_invalid_threshold(self):
        """Threshold out of range returns error."""
        errors = _validate_load_config({
            "load_name": "Bojler",
            "entity_id": "switch.bojler",
            "threshold_on": "10.00",  # > 5 PLN/kWh
        })
        assert "threshold_on" in errors

    def test_invalid_min_hours(self):
        """Min hours out of range returns error."""
        errors = _validate_load_config({
            "load_name": "Bojler",
            "entity_id": "switch.bojler",
            "min_daily_hours": "0.1",  # < 0.5
        })
        assert "min_daily_hours" in errors

    def test_invalid_max_hours(self):
        """Max hours out of range returns error."""
        errors = _validate_load_config({
            "load_name": "Bojler",
            "entity_id": "switch.bojler",
            "max_daily_hours": "25",  # > 24
        })
        assert "max_daily_hours" in errors

    def test_invalid_power(self):
        """Power out of range returns error."""
        errors = _validate_load_config({
            "load_name": "Bojler",
            "entity_id": "switch.bojler",
            "power_w": "0",  # <= 0
        })
        assert "power_w" in errors

    def test_valid_load_config(self):
        """Valid load configuration passes."""
        errors = _validate_load_config({
            "load_name": "Bojler CWU",
            "entity_id": "switch.bojler",
            "threshold_on": "0.35",
            "threshold_off": "0.55",
            "min_daily_hours": "2.0",
            "max_daily_hours": "6.0",
            "power_w": "2000",
        })
        assert errors == {}


# --- PV Validation Tests ---


class TestPVValidation:
    """Tests for PV configuration validation (Requirement 7.3)."""

    def test_missing_solar_provider(self):
        """Missing solar provider returns error."""
        errors = _validate_pv_config({
            "solar_api_key": "test_key",
        })
        assert "solar_provider" in errors

    def test_invalid_solar_provider(self):
        """Invalid solar provider returns error."""
        errors = _validate_pv_config({
            "solar_provider": "invalid",
            "solar_api_key": "test_key",
        })
        assert "solar_provider" in errors
        assert "Nieznany dostawca" in errors["solar_provider"]

    def test_missing_api_key(self):
        """Missing API key returns error."""
        errors = _validate_pv_config({
            "solar_provider": "solcast",
        })
        assert "solar_api_key" in errors

    def test_invalid_battery_capacity(self):
        """Battery capacity out of range returns error."""
        errors = _validate_pv_config({
            "solar_provider": "solcast",
            "solar_api_key": "key",
            "battery_capacity_kwh": "600",  # > 500
        })
        assert "battery_capacity_kwh" in errors

    def test_invalid_min_soc(self):
        """Min SoC out of range returns error."""
        errors = _validate_pv_config({
            "solar_provider": "solcast",
            "solar_api_key": "key",
            "min_soc_percent": "50",  # > 30
        })
        assert "min_soc_percent" in errors

    def test_valid_pv_config(self):
        """Valid PV configuration passes."""
        errors = _validate_pv_config({
            "solar_provider": "solcast",
            "solar_api_key": "test_key_123",
            "battery_capacity_kwh": "10",
            "min_soc_percent": "10",
        })
        assert errors == {}


# --- Config Flow Step Tests ---


class TestConfigFlowSteps:
    """Tests for the multi-step config flow (Requirements 7.1, 7.4, 7.8)."""

    def test_step_user_no_input_shows_form(self):
        """Step user with no input shows module selection form."""
        flow = PEOConfigFlow()
        result = run_async(flow.async_step_user(None))
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    def test_step_user_empty_modules_shows_error(self):
        """Step user with empty modules shows error."""
        flow = PEOConfigFlow()
        result = run_async(flow.async_step_user({"modules_enabled": []}))
        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert "modules_enabled" in result["errors"]

    def test_step_user_valid_modules_proceeds_to_tariff(self):
        """Step user with valid modules proceeds to tariff step."""
        flow = PEOConfigFlow()
        result = run_async(flow.async_step_user({
            "modules_enabled": [MODULE_PRICES, MODULE_TARIFF],
        }))
        assert result["type"] == "form"
        assert result["step_id"] == "tariff"

    def test_step_user_quick_setup_proceeds(self):
        """Step user with quick_setup=True proceeds to quick setup."""
        flow = PEOConfigFlow()
        result = run_async(flow.async_step_user({"quick_setup": True}))
        assert result["type"] == "form"
        assert result["step_id"] == "quick_setup"

    def test_step_tariff_no_input_shows_form(self):
        """Step tariff with no input shows tariff form."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF]
        result = run_async(flow.async_step_tariff(None))
        assert result["type"] == "form"
        assert result["step_id"] == "tariff"

    def test_step_tariff_valid_creates_entry_when_no_more_modules(self):
        """Step tariff with valid data creates entry when no EV/loads/PV."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        result = run_async(flow.async_step_tariff({
            "osd_operator": "tauron",
            "tariff_type": "G12",
            "energy_price": "0.45",
            "distribution_variable": "0.21",
            "transition_fee": "0.0009",
            "oze_fee": "0.0029",
            "capacity_fee": "0.0688",
            "cogeneration_fee": "0.0027",
        }))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_OSD_OPERATOR] == "tauron"
        assert result["data"][CONF_TARIFF_TYPE] == "G12"

    def test_step_tariff_proceeds_to_ev_when_ev_module_selected(self):
        """Step tariff proceeds to EV step when EV module is selected."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        result = run_async(flow.async_step_tariff({
            "osd_operator": "pge",
            "tariff_type": "G12w",
        }))
        assert result["type"] == "form"
        assert result["step_id"] == "ev"

    def test_step_ev_skip_proceeds_to_loads(self):
        """Step EV with skip=True proceeds to loads step."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV, MODULE_LOADS]
        result = run_async(flow.async_step_ev({"skip": True}))
        assert result["type"] == "form"
        assert result["step_id"] == "loads"

    def test_step_ev_valid_config_proceeds(self):
        """Step EV with valid config proceeds to next step."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV]
        result = run_async(flow.async_step_ev({
            "vehicle_name": "Tesla Model 3",
            "battery_capacity_kwh": "60",
            "max_charging_power_kw": "11",
            "min_charging_power_kw": "1.4",
            "soc_entity_id": "sensor.tesla_soc",
            "target_soc": "80",
            "strategy": "gotowy_do_godziny",
            "charger_protocol": "ocpp16",
            "charger_host": "192.168.1.100",
            "charger_api_key": "",
            "grid_limit_kw": "12",
        }))
        assert result["type"] == "create_entry"
        assert CONF_EV_VEHICLES in result["options"]

    def test_step_loads_skip_creates_entry(self):
        """Step loads with skip=True creates entry when no PV module."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_LOADS]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        flow._data[CONF_OSD_OPERATOR] = "tauron"
        flow._data[CONF_TARIFF_TYPE] = "G12"
        result = run_async(flow.async_step_loads({"skip": True}))
        assert result["type"] == "create_entry"

    def test_step_loads_valid_config(self):
        """Step loads with valid config adds load and creates entry."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_LOADS]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        flow._data[CONF_OSD_OPERATOR] = "tauron"
        flow._data[CONF_TARIFF_TYPE] = "G12"
        result = run_async(flow.async_step_loads({
            "load_name": "Bojler CWU",
            "entity_id": "switch.bojler",
            "threshold_on": "0.35",
            "threshold_off": "0.55",
            "min_daily_hours": "2.0",
            "max_daily_hours": "6.0",
            "allowed_start": "22:00",
            "allowed_end": "06:00",
            "priority": "1",
            "power_w": "2000",
            "failsafe_state": True,
            "add_another": False,
        }))
        assert result["type"] == "create_entry"
        assert CONF_LOADS in result["options"]
        assert len(result["options"][CONF_LOADS]) == 1

    def test_step_pv_skip_creates_entry(self):
        """Step PV with skip=True creates entry."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_PV]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        flow._data[CONF_OSD_OPERATOR] = "tauron"
        flow._data[CONF_TARIFF_TYPE] = "G12"
        result = run_async(flow.async_step_pv({"skip": True}))
        assert result["type"] == "create_entry"

    def test_step_pv_valid_config(self):
        """Step PV with valid config creates entry."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_PV]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        flow._data[CONF_OSD_OPERATOR] = "tauron"
        flow._data[CONF_TARIFF_TYPE] = "G12"
        result = run_async(flow.async_step_pv({
            "solar_provider": "solcast",
            "solar_api_key": "test_api_key",
            "capacity_kwp": "10",
            "battery_capacity_kwh": "10",
            "min_soc_percent": "10",
            "degradation_cost": "0.15",
            "inverter_entity": "sensor.inverter",
            "battery_soc_entity": "sensor.battery_soc",
        }))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_SOLAR_PROVIDER] == "solcast"
        assert CONF_PV in result["options"]

    def test_quick_setup_creates_entry_with_defaults(self):
        """Quick setup creates entry with G12 + EV + bojler defaults."""
        flow = PEOConfigFlow()
        # First go through user step to trigger quick setup
        run_async(flow.async_step_user({"quick_setup": True}))
        # Then complete quick setup
        result = run_async(flow.async_step_quick_setup({
            "vehicle_name": "Mój EV",
            "soc_entity_id": "sensor.ev_soc",
        }))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_OSD_OPERATOR] == "tauron"
        assert result["data"][CONF_TARIFF_TYPE] == "G12"
        assert CONF_EV_VEHICLES in result["options"]
        assert CONF_LOADS in result["options"]
        assert CONF_TARIFF_RATES in result["options"]


# --- Polish Language Tests ---


class TestPolishMessages:
    """Tests for Polish language in error messages (Requirement 7.2)."""

    def test_module_error_in_polish(self):
        """Module validation error is in Polish."""
        result = _validate_modules([])
        assert "Musisz wybrać" in result

    def test_osd_error_in_polish(self):
        """OSD validation error is in Polish."""
        errors = _validate_tariff_config({"tariff_type": "G12"})
        assert "wymagany" in errors["osd_operator"]

    def test_ev_name_error_in_polish(self):
        """EV name validation error is in Polish."""
        errors = _validate_ev_config({"soc_entity_id": "sensor.soc"})
        assert "wymagana" in errors["vehicle_name"]

    def test_load_name_error_in_polish(self):
        """Load name validation error is in Polish."""
        errors = _validate_load_config({"entity_id": "switch.x"})
        assert "wymagana" in errors["load_name"]

    def test_pv_provider_error_in_polish(self):
        """PV provider validation error is in Polish."""
        errors = _validate_pv_config({"solar_api_key": "key"})
        assert "wymagany" in errors["solar_provider"]


# --- Partial Configuration Tests ---


class TestPartialConfiguration:
    """Tests for partial configuration preservation (Requirement 7.7)."""

    def test_partial_config_preserved_after_tariff_step(self):
        """Partial config is preserved after completing tariff step."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        run_async(flow.async_step_tariff({
            "osd_operator": "tauron",
            "tariff_type": "G12",
        }))

        partial = flow.partial_config
        assert partial["data"][CONF_OSD_OPERATOR] == "tauron"
        assert partial["data"][CONF_TARIFF_TYPE] == "G12"
        assert partial["modules"] == flow._modules

    def test_partial_config_includes_options(self):
        """Partial config includes options set so far."""
        flow = PEOConfigFlow()
        flow._modules = [MODULE_PRICES, MODULE_TARIFF]
        flow._data[CONF_MODULES_ENABLED] = flow._modules
        run_async(flow.async_step_tariff({
            "osd_operator": "enea",
            "tariff_type": "G13",
            "energy_price": "0.50",
        }))

        partial = flow.partial_config
        assert CONF_TARIFF_RATES in partial["options"]


# --- Config Flow VERSION and DOMAIN ---


class TestConfigFlowMetadata:
    """Tests for ConfigFlow metadata."""

    def test_version_is_1(self):
        """Config flow VERSION is 1."""
        assert PEOConfigFlow.VERSION == 1

    def test_domain_is_peo(self):
        """Config flow domain is 'peo'."""
        assert PEOConfigFlow._domain == "peo"
