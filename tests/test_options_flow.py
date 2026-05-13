"""Unit tests for PEOOptionsFlow.

Tests cover:
- Init step shows module selection menu
- Tariff rates reconfiguration
- EV configuration update
- Loads add/remove without full reconfiguration
- PV configuration update
- ConfigEntry.options updated without reload
- Polish error messages for invalid inputs

Requirements: 7.5, 7.6, 8.9
"""

import pytest
import asyncio
from unittest.mock import MagicMock

from custom_components.peo.options_flow import PEOOptionsFlow
from custom_components.peo.const import (
    CONF_TARIFF_RATES,
    CONF_EV_VEHICLES,
    CONF_LOADS,
    CONF_GRID_LIMIT_KW,
    CONF_PV,
)


# --- Helper to run async tests ---
def run_async(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_config_entry(options=None):
    """Create a mock ConfigEntry with given options."""
    entry = MagicMock()
    entry.options = options or {}
    return entry


# --- Init Step Tests ---


class TestOptionsFlowInit:
    """Tests for the init step (module selection menu)."""

    def test_init_no_input_shows_menu(self):
        """Init step with no input shows module selection menu."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_init(None))
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    def test_init_select_tariff_rates(self):
        """Selecting tariff_rates navigates to tariff rates step."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_init({"module": "tariff_rates"}))
        assert result["type"] == "form"
        assert result["step_id"] == "tariff_rates"

    def test_init_select_ev_config(self):
        """Selecting ev_config navigates to EV config step."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_init({"module": "ev_config"}))
        assert result["type"] == "form"
        assert result["step_id"] == "ev_config"

    def test_init_select_loads_config(self):
        """Selecting loads_config navigates to loads config step."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_init({"module": "loads_config"}))
        assert result["type"] == "form"
        assert result["step_id"] == "loads_config"

    def test_init_select_pv_config(self):
        """Selecting pv_config navigates to PV config step."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_init({"module": "pv_config"}))
        assert result["type"] == "form"
        assert result["step_id"] == "pv_config"


# --- Tariff Rates Step Tests ---


class TestOptionsFlowTariffRates:
    """Tests for tariff rates reconfiguration (Requirement 7.6, 8.9)."""

    def test_tariff_rates_no_input_shows_form(self):
        """Tariff rates step with no input shows form with current values."""
        entry = _make_config_entry({
            CONF_TARIFF_RATES: {
                "energy_price": "0.50",
                "distribution_variable": "0.22",
                "transition_fee": "0.001",
                "oze_fee": "0.003",
                "capacity_fee": "0.07",
                "cogeneration_fee": "0.003",
            }
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates(None))
        assert result["type"] == "form"
        assert result["step_id"] == "tariff_rates"

    def test_tariff_rates_valid_input_creates_entry(self):
        """Valid tariff rates update creates entry with new options."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "0.55",
            "distribution_variable": "0.23",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_TARIFF_RATES]["energy_price"] == "0.55"

    def test_tariff_rates_invalid_rate_shows_error(self):
        """Invalid rate value shows Polish error message."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "10.00",  # > 5 PLN/kWh
            "distribution_variable": "0.21",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        assert result["type"] == "form"
        assert "energy_price" in result["errors"]

    def test_tariff_rates_negative_rate_shows_error(self):
        """Negative rate value shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "-0.50",
            "distribution_variable": "0.21",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        assert result["type"] == "form"
        assert "energy_price" in result["errors"]

    def test_tariff_rates_updates_without_reload(self):
        """Tariff rates update modifies options without requiring reload."""
        entry = _make_config_entry({
            CONF_TARIFF_RATES: {"energy_price": "0.45"}
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "0.60",
            "distribution_variable": "0.25",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        assert result["type"] == "create_entry"
        assert result["data"][CONF_TARIFF_RATES]["energy_price"] == "0.60"


# --- EV Config Step Tests ---


class TestOptionsFlowEVConfig:
    """Tests for EV configuration update (Requirement 7.6)."""

    def test_ev_config_no_input_shows_form(self):
        """EV config step with no input shows form."""
        entry = _make_config_entry({
            CONF_EV_VEHICLES: [{
                "id": "ev_1",
                "name": "Tesla",
                "max_power_kw": 11,
                "min_power_kw": 1.4,
                "soc_entity": "sensor.tesla_soc",
                "target_soc": 80,
                "strategy": "gotowy_do_godziny",
            }],
            CONF_GRID_LIMIT_KW: 12.0,
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_ev_config(None))
        assert result["type"] == "form"
        assert result["step_id"] == "ev_config"

    def test_ev_config_valid_update(self):
        """Valid EV config update creates entry."""
        entry = _make_config_entry({
            CONF_EV_VEHICLES: [{
                "id": "ev_1",
                "name": "Tesla",
                "target_soc": 80,
            }]
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_ev_config({
            "vehicle_name": "Tesla Model Y",
            "max_charging_power_kw": "22",
            "min_charging_power_kw": "1.4",
            "soc_entity_id": "sensor.tesla_soc",
            "target_soc": "90",
            "strategy": "najtańsze_okna",
            "grid_limit_kw": "15",
        }))
        assert result["type"] == "create_entry"
        vehicles = result["data"][CONF_EV_VEHICLES]
        assert vehicles[0]["name"] == "Tesla Model Y"
        assert vehicles[0]["target_soc"] == 90
        assert result["data"][CONF_GRID_LIMIT_KW] == 15.0

    def test_ev_config_invalid_soc_shows_error(self):
        """Invalid SoC value shows Polish error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_ev_config({
            "vehicle_name": "Tesla",
            "target_soc": "150",  # > 100
            "max_charging_power_kw": "11",
            "soc_entity_id": "sensor.soc",
            "grid_limit_kw": "12",
        }))
        assert result["type"] == "form"
        assert "target_soc" in result["errors"]

    def test_ev_config_invalid_power_shows_error(self):
        """Invalid power value shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_ev_config({
            "vehicle_name": "Tesla",
            "target_soc": "80",
            "max_charging_power_kw": "200",  # > 100 kW
            "soc_entity_id": "sensor.soc",
            "grid_limit_kw": "12",
        }))
        assert result["type"] == "form"
        assert "max_charging_power_kw" in result["errors"]

    def test_ev_config_invalid_grid_limit_shows_error(self):
        """Invalid grid limit shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_ev_config({
            "vehicle_name": "Tesla",
            "target_soc": "80",
            "max_charging_power_kw": "11",
            "soc_entity_id": "sensor.soc",
            "grid_limit_kw": "abc",
        }))
        assert result["type"] == "form"
        assert "grid_limit_kw" in result["errors"]


# --- Loads Config Step Tests ---


class TestOptionsFlowLoadsConfig:
    """Tests for loads add/remove (Requirement 7.5, 7.6)."""

    def test_loads_config_no_input_shows_form(self):
        """Loads config step with no input shows form."""
        entry = _make_config_entry({CONF_LOADS: []})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config(None))
        assert result["type"] == "form"
        assert result["step_id"] == "loads_config"

    def test_loads_add_valid_load(self):
        """Adding a valid load creates entry with new load."""
        entry = _make_config_entry({CONF_LOADS: []})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
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
        }))
        assert result["type"] == "create_entry"
        loads = result["data"][CONF_LOADS]
        assert len(loads) == 1
        assert loads[0]["name"] == "Bojler CWU"

    def test_loads_add_without_name_shows_error(self):
        """Adding load without name shows Polish error."""
        entry = _make_config_entry({CONF_LOADS: []})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
            "load_name": "",
            "entity_id": "switch.bojler",
        }))
        assert result["type"] == "form"
        assert "load_name" in result["errors"]
        assert "wymagana" in result["errors"]["load_name"]

    def test_loads_add_without_entity_shows_error(self):
        """Adding load without entity_id shows Polish error."""
        entry = _make_config_entry({CONF_LOADS: []})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
            "load_name": "Bojler",
            "entity_id": "",
        }))
        assert result["type"] == "form"
        assert "entity_id" in result["errors"]
        assert "wymagana" in result["errors"]["entity_id"]

    def test_loads_add_invalid_threshold_shows_error(self):
        """Adding load with invalid threshold shows error."""
        entry = _make_config_entry({CONF_LOADS: []})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
            "load_name": "Bojler",
            "entity_id": "switch.bojler",
            "threshold_on": "10.00",  # > 5 PLN/kWh
        }))
        assert result["type"] == "form"
        assert "threshold_on" in result["errors"]

    def test_loads_remove_valid_index(self):
        """Removing load by valid index creates entry without that load."""
        entry = _make_config_entry({
            CONF_LOADS: [
                {"id": "load_1", "name": "Bojler"},
                {"id": "load_2", "name": "Pompa"},
            ]
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "remove",
            "remove_index": "0",
        }))
        assert result["type"] == "create_entry"
        loads = result["data"][CONF_LOADS]
        assert len(loads) == 1
        assert loads[0]["name"] == "Pompa"

    def test_loads_remove_invalid_index_shows_error(self):
        """Removing load with invalid index shows error."""
        entry = _make_config_entry({CONF_LOADS: [{"id": "load_1", "name": "Bojler"}]})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "remove",
            "remove_index": "5",
        }))
        assert result["type"] == "form"
        assert "remove_index" in result["errors"]

    def test_loads_done_action_creates_entry(self):
        """Done action creates entry with current loads."""
        entry = _make_config_entry({
            CONF_LOADS: [{"id": "load_1", "name": "Bojler"}]
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "done",
        }))
        assert result["type"] == "create_entry"

    def test_loads_max_limit_shows_error(self):
        """Adding load when at max limit shows error."""
        existing_loads = [
            {"id": f"load_{i}", "name": f"Load {i}"}
            for i in range(16)
        ]
        entry = _make_config_entry({CONF_LOADS: existing_loads})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
            "load_name": "Extra Load",
            "entity_id": "switch.extra",
        }))
        assert result["type"] == "form"
        assert "base" in result["errors"]
        assert "maksymalną" in result["errors"]["base"]

    def test_loads_add_preserves_existing(self):
        """Adding a new load preserves existing loads."""
        entry = _make_config_entry({
            CONF_LOADS: [{"id": "load_1", "name": "Bojler", "entity_id": "switch.bojler"}]
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_loads_config({
            "action": "add",
            "load_name": "Pompa ciepła",
            "entity_id": "switch.pompa",
            "threshold_on": "0.30",
            "threshold_off": "0.50",
            "power_w": "3000",
        }))
        assert result["type"] == "create_entry"
        loads = result["data"][CONF_LOADS]
        assert len(loads) == 2
        assert loads[0]["name"] == "Bojler"
        assert loads[1]["name"] == "Pompa ciepła"


# --- PV Config Step Tests ---


class TestOptionsFlowPVConfig:
    """Tests for PV configuration update (Requirement 7.6)."""

    def test_pv_config_no_input_shows_form(self):
        """PV config step with no input shows form."""
        entry = _make_config_entry({
            CONF_PV: {
                "capacity_kwp": 10.0,
                "battery_capacity_kwh": 10.0,
                "min_soc": 10,
            }
        })
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config(None))
        assert result["type"] == "form"
        assert result["step_id"] == "pv_config"

    def test_pv_config_valid_update(self):
        """Valid PV config update creates entry."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config({
            "capacity_kwp": "15",
            "battery_capacity_kwh": "12",
            "min_soc_percent": "15",
            "degradation_cost": "0.20",
            "inverter_entity": "sensor.inverter",
            "battery_soc_entity": "sensor.battery_soc",
        }))
        assert result["type"] == "create_entry"
        pv = result["data"][CONF_PV]
        assert pv["capacity_kwp"] == 15.0
        assert pv["battery_capacity_kwh"] == 12.0
        assert pv["min_soc"] == 15

    def test_pv_config_invalid_battery_capacity_shows_error(self):
        """Invalid battery capacity shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config({
            "capacity_kwp": "10",
            "battery_capacity_kwh": "600",  # > 500
            "min_soc_percent": "10",
        }))
        assert result["type"] == "form"
        assert "battery_capacity_kwh" in result["errors"]

    def test_pv_config_invalid_min_soc_shows_error(self):
        """Invalid min SoC shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config({
            "capacity_kwp": "10",
            "battery_capacity_kwh": "10",
            "min_soc_percent": "50",  # > 30
        }))
        assert result["type"] == "form"
        assert "min_soc_percent" in result["errors"]

    def test_pv_config_invalid_degradation_cost_shows_error(self):
        """Invalid degradation cost shows error."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config({
            "capacity_kwp": "10",
            "battery_capacity_kwh": "10",
            "min_soc_percent": "10",
            "degradation_cost": "10.00",  # > 5 PLN/kWh
        }))
        assert result["type"] == "form"
        assert "degradation_cost" in result["errors"]

    def test_pv_config_without_battery(self):
        """PV config without battery creates entry with just capacity."""
        entry = _make_config_entry()
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_pv_config({
            "capacity_kwp": "8",
            "battery_capacity_kwh": "",
            "min_soc_percent": "",
        }))
        assert result["type"] == "create_entry"
        pv = result["data"][CONF_PV]
        assert pv["capacity_kwp"] == 8.0
        assert "battery_capacity_kwh" not in pv


# --- Integration Tests (Options update without reload) ---


class TestOptionsFlowNoReload:
    """Tests verifying options update without requiring reload (Requirement 8.9)."""

    def test_options_update_returns_create_entry(self):
        """Options update returns create_entry type (no reload needed)."""
        entry = _make_config_entry({CONF_TARIFF_RATES: {"energy_price": "0.45"}})
        flow = PEOOptionsFlow(entry)
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "0.50",
            "distribution_variable": "0.21",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        # create_entry in options flow means options are updated without reload
        assert result["type"] == "create_entry"

    def test_independent_module_reconfiguration(self):
        """Each module can be reconfigured independently."""
        initial_options = {
            CONF_TARIFF_RATES: {"energy_price": "0.45"},
            CONF_EV_VEHICLES: [{"id": "ev_1", "name": "Tesla"}],
            CONF_LOADS: [{"id": "load_1", "name": "Bojler"}],
            CONF_PV: {"capacity_kwp": 10.0},
        }
        entry = _make_config_entry(initial_options)
        flow = PEOOptionsFlow(entry)

        # Update only tariff rates — other modules should be preserved
        result = run_async(flow.async_step_tariff_rates({
            "energy_price": "0.60",
            "distribution_variable": "0.25",
            "transition_fee": "0.001",
            "oze_fee": "0.003",
            "capacity_fee": "0.07",
            "cogeneration_fee": "0.003",
        }))
        assert result["type"] == "create_entry"
        # Tariff rates updated
        assert result["data"][CONF_TARIFF_RATES]["energy_price"] == "0.60"
        # Other modules preserved
        assert result["data"][CONF_EV_VEHICLES] == [{"id": "ev_1", "name": "Tesla"}]
        assert result["data"][CONF_LOADS] == [{"id": "load_1", "name": "Bojler"}]
        assert result["data"][CONF_PV] == {"capacity_kwp": 10.0}
