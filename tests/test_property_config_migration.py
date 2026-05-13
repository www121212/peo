"""Property-based tests for config migration.

**Validates: Requirements 8.10**

Property 21: Migracja konfiguracji zachowuje dane
Dla dowolnej konfiguracji w starym formacie, migracja do nowego formatu
powinna zachować wszystkie wartości konfiguracyjne użytkownika lub
przekształcić je do nowego formatu bez utraty danych.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    text,
    integers,
    floats,
    booleans,
    lists,
    dictionaries,
    composite,
    sampled_from,
    just,
    one_of,
    fixed_dictionaries,
    none,
)

from custom_components.peo.__init__ import (
    CONFIG_VERSION,
    _migrate_v0_to_v1,
    async_migrate_entry,
)
from custom_components.peo.const import (
    CONF_MODULES_ENABLED,
    CONF_OSD_OPERATOR,
    CONF_TARIFF_TYPE,
    CONF_TARIFF_RATES,
    CONF_EV_VEHICLES,
    CONF_LOADS,
    CONF_GRID_LIMIT_KW,
    CONF_PV,
    CONF_SOLAR_PROVIDER,
    CONF_SOLAR_API_KEY,
    CONF_CHARGERS,
    MODULE_PRICES,
    MODULE_TARIFF,
    MODULE_EV,
    MODULE_LOADS,
    MODULE_PV,
    MODULE_ANALYZER,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies for generating valid config data ---

VALID_MODULES = [MODULE_PRICES, MODULE_TARIFF, MODULE_EV, MODULE_LOADS, MODULE_PV, MODULE_ANALYZER]
VALID_OSD_OPERATORS = ["tauron", "pge", "enea", "energa", "innogy_stoen"]
VALID_TARIFF_TYPES = ["G11", "G12", "G12w", "G12r", "G13", "C11", "C12a", "C12b"]
VALID_SOLAR_PROVIDERS = ["solcast", "forecast_solar", "openweathermap"]
VALID_STRATEGIES = ["najtańsze_okna", "gotowy_do_godziny", "tylko_nadwyżka_PV"]


@composite
def valid_modules_list(draw):
    """Generate a valid list of enabled modules (at least one)."""
    all_modules = list(VALID_MODULES)
    # Pick at least 1 module
    count = draw(integers(min_value=1, max_value=len(all_modules)))
    selected = draw(
        lists(
            sampled_from(all_modules),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    return selected


@composite
def valid_tariff_rates(draw):
    """Generate valid tariff rates dictionary."""
    return {
        "energy_price": str(round(draw(floats(min_value=0.01, max_value=4.99, allow_nan=False, allow_infinity=False)), 4)),
        "distribution_variable": str(round(draw(floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False)), 4)),
        "transition_fee": str(round(draw(floats(min_value=0.0001, max_value=0.1, allow_nan=False, allow_infinity=False)), 4)),
        "oze_fee": str(round(draw(floats(min_value=0.0001, max_value=0.1, allow_nan=False, allow_infinity=False)), 4)),
        "capacity_fee": str(round(draw(floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False)), 4)),
        "cogeneration_fee": str(round(draw(floats(min_value=0.0001, max_value=0.1, allow_nan=False, allow_infinity=False)), 4)),
    }


@composite
def valid_ev_vehicle(draw):
    """Generate a valid EV vehicle config."""
    return {
        "id": f"ev_{draw(integers(min_value=1, max_value=4))}",
        "name": draw(text(min_size=1, max_size=30)),
        "battery_kwh": draw(floats(min_value=20.0, max_value=150.0, allow_nan=False, allow_infinity=False)),
        "max_power_kw": draw(floats(min_value=1.4, max_value=22.0, allow_nan=False, allow_infinity=False)),
        "min_power_kw": draw(floats(min_value=1.0, max_value=3.0, allow_nan=False, allow_infinity=False)),
        "soc_entity": f"sensor.ev_soc_{draw(integers(min_value=1, max_value=10))}",
        "target_soc": draw(integers(min_value=10, max_value=100)),
        "priority": draw(integers(min_value=1, max_value=4)),
        "strategy": draw(sampled_from(VALID_STRATEGIES)),
    }


@composite
def valid_load_config(draw):
    """Generate a valid load config."""
    return {
        "id": f"load_{draw(integers(min_value=1, max_value=16))}",
        "name": draw(text(min_size=1, max_size=30)),
        "entity_id": f"switch.load_{draw(integers(min_value=1, max_value=20))}",
        "threshold_on": str(round(draw(floats(min_value=0.01, max_value=2.0, allow_nan=False, allow_infinity=False)), 4)),
        "threshold_off": str(round(draw(floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False)), 4)),
        "min_hours": round(draw(floats(min_value=0.5, max_value=12.0, allow_nan=False, allow_infinity=False)), 1),
        "max_hours": round(draw(floats(min_value=1.0, max_value=24.0, allow_nan=False, allow_infinity=False)), 1),
        "allowed_start": "22:00",
        "allowed_end": "06:00",
        "priority": draw(integers(min_value=1, max_value=16)),
        "power_w": draw(integers(min_value=100, max_value=10000)),
        "failsafe": draw(booleans()),
    }


@composite
def valid_config_data(draw):
    """Generate a valid ConfigEntry.data dictionary."""
    modules = draw(valid_modules_list())
    data = {
        CONF_MODULES_ENABLED: modules,
        CONF_OSD_OPERATOR: draw(sampled_from(VALID_OSD_OPERATORS)),
        CONF_TARIFF_TYPE: draw(sampled_from(VALID_TARIFF_TYPES)),
    }

    # Optionally add solar provider
    if MODULE_PV in modules:
        data[CONF_SOLAR_PROVIDER] = draw(sampled_from(VALID_SOLAR_PROVIDERS))
        data[CONF_SOLAR_API_KEY] = draw(text(min_size=10, max_size=64))

    # Optionally add chargers
    if MODULE_EV in modules:
        data[CONF_CHARGERS] = [{
            "id": "charger_1",
            "protocol": draw(sampled_from(["ocpp16", "ocpp20", "tesla", "wallbox", "openevse"])),
            "host": f"192.168.1.{draw(integers(min_value=1, max_value=254))}",
            "api_key": draw(text(min_size=5, max_size=32)),
        }]

    return data


@composite
def valid_config_options(draw):
    """Generate a valid ConfigEntry.options dictionary."""
    options = {}

    # Tariff rates
    options[CONF_TARIFF_RATES] = draw(valid_tariff_rates())

    # EV vehicles (0-4)
    num_vehicles = draw(integers(min_value=0, max_value=2))
    if num_vehicles > 0:
        options[CONF_EV_VEHICLES] = [draw(valid_ev_vehicle()) for _ in range(num_vehicles)]

    # Loads (0-10)
    num_loads = draw(integers(min_value=0, max_value=3))
    if num_loads > 0:
        options[CONF_LOADS] = [draw(valid_load_config()) for _ in range(num_loads)]

    # Grid limit
    options[CONF_GRID_LIMIT_KW] = round(
        draw(floats(min_value=3.0, max_value=40.0, allow_nan=False, allow_infinity=False)), 1
    )

    return options


@composite
def config_at_version_0(draw):
    """Generate a config that simulates version 0 (missing required keys)."""
    # Version 0 might be missing some keys that v1 requires
    data = {}

    # Randomly include/exclude keys to simulate incomplete old configs
    if draw(booleans()):
        data[CONF_OSD_OPERATOR] = draw(sampled_from(VALID_OSD_OPERATORS))
    if draw(booleans()):
        data[CONF_TARIFF_TYPE] = draw(sampled_from(VALID_TARIFF_TYPES))
    if draw(booleans()):
        data[CONF_MODULES_ENABLED] = draw(valid_modules_list())

    # May have extra keys from old schema
    if draw(booleans()):
        data["legacy_key"] = draw(text(min_size=1, max_size=20))

    options = {}
    if draw(booleans()):
        options[CONF_TARIFF_RATES] = draw(valid_tariff_rates())
    if draw(booleans()):
        options[CONF_GRID_LIMIT_KW] = round(
            draw(floats(min_value=3.0, max_value=40.0, allow_nan=False, allow_infinity=False)), 1
        )

    return data, options


# --- Property 21: Config Migration Preserves Data ---


class TestProperty21ConfigMigration:
    """Property 21: Migracja konfiguracji zachowuje dane.

    For any valid config at version N, migration to version N+1
    preserves all user values.
    """

    @given(data=valid_config_data(), options=valid_config_options())
    @PROPERTY_TEST_SETTINGS
    def test_migration_v0_to_v1_preserves_existing_values(self, data, options):
        """Migration from v0 to v1 preserves all existing user values.

        **Validates: Requirements 8.10**
        """
        # Store original values
        original_data = dict(data)
        original_options = dict(options)

        # Perform migration
        new_data, new_options = _migrate_v0_to_v1(dict(data), dict(options))

        # All original data keys must be preserved
        for key, value in original_data.items():
            assert key in new_data, (
                f"Key '{key}' lost during migration from data"
            )
            assert new_data[key] == value, (
                f"Value for '{key}' changed during migration: "
                f"{value!r} -> {new_data[key]!r}"
            )

        # All original options keys must be preserved
        for key, value in original_options.items():
            assert key in new_options, (
                f"Key '{key}' lost during migration from options"
            )
            assert new_options[key] == value, (
                f"Value for '{key}' changed during migration: "
                f"{value!r} -> {new_options[key]!r}"
            )

    @given(config=config_at_version_0())
    @PROPERTY_TEST_SETTINGS
    def test_migration_v0_to_v1_adds_required_defaults(self, config):
        """Migration from v0 to v1 adds required keys with defaults.

        **Validates: Requirements 8.10**
        """
        data, options = config

        # Perform migration
        new_data, new_options = _migrate_v0_to_v1(dict(data), dict(options))

        # Required keys must exist after migration
        assert CONF_MODULES_ENABLED in new_data, (
            "modules_enabled must exist after migration"
        )
        assert CONF_OSD_OPERATOR in new_data, (
            "osd_operator must exist after migration"
        )
        assert CONF_TARIFF_TYPE in new_data, (
            "tariff_type must exist after migration"
        )

        # modules_enabled must be a non-empty list
        assert isinstance(new_data[CONF_MODULES_ENABLED], list)
        assert len(new_data[CONF_MODULES_ENABLED]) > 0

        # OSD operator must be valid
        assert new_data[CONF_OSD_OPERATOR] in VALID_OSD_OPERATORS

        # Tariff type must be valid
        assert new_data[CONF_TARIFF_TYPE] in VALID_TARIFF_TYPES + [
            "C22a", "C22b", "C23"
        ]

    @given(config=config_at_version_0())
    @PROPERTY_TEST_SETTINGS
    def test_migration_preserves_user_values_over_defaults(self, config):
        """If user already has a value, migration does not overwrite it.

        **Validates: Requirements 8.10**
        """
        data, options = config

        # Perform migration
        new_data, new_options = _migrate_v0_to_v1(dict(data), dict(options))

        # If original data had a value, it must be preserved (not overwritten by default)
        if CONF_MODULES_ENABLED in data:
            assert new_data[CONF_MODULES_ENABLED] == data[CONF_MODULES_ENABLED]
        if CONF_OSD_OPERATOR in data:
            assert new_data[CONF_OSD_OPERATOR] == data[CONF_OSD_OPERATOR]
        if CONF_TARIFF_TYPE in data:
            assert new_data[CONF_TARIFF_TYPE] == data[CONF_TARIFF_TYPE]

    @given(data=valid_config_data(), options=valid_config_options())
    @PROPERTY_TEST_SETTINGS
    def test_migration_is_idempotent(self, data, options):
        """Applying migration twice produces the same result as once.

        **Validates: Requirements 8.10**
        """
        # First migration
        data1, options1 = _migrate_v0_to_v1(dict(data), dict(options))

        # Second migration (should be no-op since all keys exist)
        data2, options2 = _migrate_v0_to_v1(dict(data1), dict(options1))

        assert data1 == data2, "Migration is not idempotent for data"
        assert options1 == options2, "Migration is not idempotent for options"

    @given(data=valid_config_data(), options=valid_config_options())
    @PROPERTY_TEST_SETTINGS
    def test_migration_does_not_remove_keys(self, data, options):
        """Migration never removes any existing keys from config.

        **Validates: Requirements 8.10**
        """
        original_data_keys = set(data.keys())
        original_options_keys = set(options.keys())

        new_data, new_options = _migrate_v0_to_v1(dict(data), dict(options))

        # No keys should be removed
        assert original_data_keys.issubset(set(new_data.keys())), (
            f"Keys removed from data: {original_data_keys - set(new_data.keys())}"
        )
        assert original_options_keys.issubset(set(new_options.keys())), (
            f"Keys removed from options: {original_options_keys - set(new_options.keys())}"
        )

    @given(data=valid_config_data(), options=valid_config_options())
    @PROPERTY_TEST_SETTINGS
    def test_migrated_config_has_valid_structure(self, data, options):
        """After migration, config has all required fields with valid types.

        **Validates: Requirements 8.10**
        """
        new_data, new_options = _migrate_v0_to_v1(dict(data), dict(options))

        # Validate structure
        assert isinstance(new_data[CONF_MODULES_ENABLED], list)
        assert isinstance(new_data[CONF_OSD_OPERATOR], str)
        assert isinstance(new_data[CONF_TARIFF_TYPE], str)

        # All modules must be valid
        for module in new_data[CONF_MODULES_ENABLED]:
            assert module in VALID_MODULES, f"Invalid module: {module}"
