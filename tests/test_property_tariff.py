"""Property-based tests for tariff calculation and validation.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.9**

Property 4: Obliczanie kosztu kWh dla taryf
Dla dowolnej kombinacji typu taryfy, operatora OSD, znacznika czasu i stawek
taryfowych, obliczony koszt kWh powinien być równy sumie wszystkich składników
(cena energii + opłata dystrybucyjna zmienna + opłata przejściowa + opłata OZE
+ opłata mocowa + opłata kogeneracyjna) z dokładnością do 4 miejsc po przecinku,
przy czym zastosowana stawka dystrybucyjna powinna odpowiadać strefie czasowej
aktywnej dla danego operatora OSD w podanym znaczniku czasu.

Property 5: Walidacja konfiguracji taryfa/OSD
Dla dowolnej nieprawidłowej kombinacji taryfy i operatora OSD lub brakujących
wymaganych stawek, system powinien wyświetlić komunikat o błędzie walidacji
w języku polskim i uniemożliwić zapis konfiguracji.
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    floats,
    composite,
    sampled_from,
    datetimes,
    just,
    one_of,
    dictionaries,
    fixed_dictionaries,
)

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import TariffRates
from custom_components.peo.tariff_calculator import TariffCalculator
from custom_components.peo.tariff_loader import TariffDefinitionLoader, TariffLoadError

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

# Precision for cost calculations (4 decimal places)
_COST_PRECISION = Decimal("0.0001")

# --- Strategies ---


@composite
def valid_tariff_rate_component(draw):
    """Generate a valid tariff rate component (positive Decimal, 4 dp)."""
    value = draw(
        floats(
            min_value=0.0001,
            max_value=5.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return Decimal(str(round(value, 4)))


@composite
def valid_tariff_rates(draw):
    """Generate a valid TariffRates with all components > 0."""
    return TariffRates(
        energy_price=draw(valid_tariff_rate_component()),
        distribution_variable=draw(valid_tariff_rate_component()),
        transition_fee=draw(valid_tariff_rate_component()),
        oze_fee=draw(valid_tariff_rate_component()),
        capacity_fee=draw(valid_tariff_rate_component()),
        cogeneration_fee=draw(valid_tariff_rate_component()),
    )


@composite
def valid_timestamp(draw):
    """Generate a random timestamp (any hour 0-23, any day of week, any month)."""
    return draw(
        datetimes(
            min_value=datetime(2024, 1, 1, 0, 0),
            max_value=datetime(2024, 12, 31, 23, 59),
        )
    )


# Single-zone tariffs always use SINGLE zone
SINGLE_ZONE_TARIFFS = [TariffType.G11, TariffType.C11, TariffType.C21]

# Multi-zone tariffs with szczyt/pozaszczyt
MULTI_ZONE_TARIFFS_2 = [
    TariffType.G12, TariffType.G12R,
    TariffType.C12A, TariffType.C12B,
    TariffType.C22A, TariffType.C22B,
]

# G12w has szczyt/pozaszczyt/weekend
# G13 has szczyt_poranny/szczyt_popołudniowy/pozaszczyt
# C23 has szczyt/pozaszczyt/noc


@composite
def single_zone_rates_dict(draw):
    """Generate rates dict for single-zone tariffs (G11, C11, C21)."""
    rates = draw(valid_tariff_rates())
    return {TimeZoneName.SINGLE: rates}


@composite
def two_zone_rates_dict(draw):
    """Generate rates dict for two-zone tariffs (G12, G12r, C12a, etc.)."""
    szczyt_rates = draw(valid_tariff_rates())
    pozaszczyt_rates = draw(valid_tariff_rates())
    return {
        TimeZoneName.SZCZYT: szczyt_rates,
        TimeZoneName.POZASZCZYT: pozaszczyt_rates,
    }


@composite
def g12w_rates_dict(draw):
    """Generate rates dict for G12w (szczyt/pozaszczyt — weekend uses pozaszczyt)."""
    szczyt_rates = draw(valid_tariff_rates())
    pozaszczyt_rates = draw(valid_tariff_rates())
    return {
        TimeZoneName.SZCZYT: szczyt_rates,
        TimeZoneName.POZASZCZYT: pozaszczyt_rates,
    }


@composite
def g13_rates_dict(draw):
    """Generate rates dict for G13 (szczyt_poranny/szczyt_popołudniowy/pozaszczyt)."""
    poranny_rates = draw(valid_tariff_rates())
    popoludniowy_rates = draw(valid_tariff_rates())
    pozaszczyt_rates = draw(valid_tariff_rates())
    return {
        TimeZoneName.SZCZYT_PORANNY: poranny_rates,
        TimeZoneName.SZCZYT_POPOLUDNIOWY: popoludniowy_rates,
        TimeZoneName.POZASZCZYT: pozaszczyt_rates,
    }


@composite
def c23_rates_dict(draw):
    """Generate rates dict for C23 (szczyt/pozaszczyt/noc)."""
    szczyt_rates = draw(valid_tariff_rates())
    pozaszczyt_rates = draw(valid_tariff_rates())
    noc_rates = draw(valid_tariff_rates())
    return {
        TimeZoneName.SZCZYT: szczyt_rates,
        TimeZoneName.POZASZCZYT: pozaszczyt_rates,
        TimeZoneName.NOC: noc_rates,
    }


@composite
def tariff_with_matching_rates(draw):
    """Generate a tariff type with matching rates dict and operator."""
    tariff = draw(sampled_from(list(TariffType)))
    operator = draw(sampled_from(list(OSDOperator)))
    timestamp = draw(valid_timestamp())

    if tariff in SINGLE_ZONE_TARIFFS:
        rates = draw(single_zone_rates_dict())
    elif tariff == TariffType.G12W:
        rates = draw(g12w_rates_dict())
    elif tariff == TariffType.G13:
        rates = draw(g13_rates_dict())
    elif tariff == TariffType.C23:
        rates = draw(c23_rates_dict())
    else:
        # G12, G12r, C12a, C12b, C22a, C22b
        rates = draw(two_zone_rates_dict())

    return tariff, operator, timestamp, rates


# --- Property 4 Tests ---


class TestProperty4TariffCostCalculation:
    """Property 4: Obliczanie kosztu kWh dla taryf.

    For any combination of tariff type, OSD operator, timestamp, and tariff rates,
    the calculated cost per kWh should equal the sum of all components with 4 decimal
    places precision, where the applied distribution rate corresponds to the active
    time zone for the given OSD operator at the given timestamp.

    **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=tariff_with_matching_rates())
    def test_cost_equals_sum_of_all_components(self, data):
        """For any tariff/operator/timestamp/rates combination, calculate_cost
        equals the sum of all 6 components for the active zone.

        **Validates: Requirements 2.1, 2.3**
        """
        tariff, operator, timestamp, rates = data

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        cost = calculator.calculate_cost(timestamp, tariff, operator, rates)

        # Determine which zone is active
        zone = calculator.get_zone_for_time(timestamp, tariff, operator)

        # Get the rates for the active zone (same logic as calculator)
        if zone in rates:
            zone_rates = rates[zone]
        elif zone == TimeZoneName.WEEKEND and TimeZoneName.POZASZCZYT in rates:
            zone_rates = rates[TimeZoneName.POZASZCZYT]
        else:
            # Fallback to first available zone
            zone_rates = rates[next(iter(rates))]

        # Compute expected sum of all 6 components
        expected = (
            zone_rates.energy_price
            + zone_rates.distribution_variable
            + zone_rates.transition_fee
            + zone_rates.oze_fee
            + zone_rates.capacity_fee
            + zone_rates.cogeneration_fee
        ).quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)

        assert cost == expected

    @PROPERTY_TEST_SETTINGS
    @given(data=tariff_with_matching_rates())
    def test_cost_has_exactly_4_decimal_places(self, data):
        """For any tariff calculation, the result has exactly 4 decimal places.

        **Validates: Requirements 2.3**
        """
        tariff, operator, timestamp, rates = data

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        cost = calculator.calculate_cost(timestamp, tariff, operator, rates)

        # Verify 4 decimal places precision
        assert cost == cost.quantize(_COST_PRECISION)

    @PROPERTY_TEST_SETTINGS
    @given(data=tariff_with_matching_rates())
    def test_zone_used_in_cost_matches_get_zone_for_time(self, data):
        """For any combination, the zone returned by get_zone_for_time matches
        the zone used in cost calculation (verified by component matching).

        **Validates: Requirements 2.2, 2.4**
        """
        tariff, operator, timestamp, rates = data

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        zone = calculator.get_zone_for_time(timestamp, tariff, operator)
        cost = calculator.calculate_cost(timestamp, tariff, operator, rates)

        # Determine which rates were actually used
        if zone in rates:
            expected_rates = rates[zone]
        elif zone == TimeZoneName.WEEKEND and TimeZoneName.POZASZCZYT in rates:
            expected_rates = rates[TimeZoneName.POZASZCZYT]
        else:
            expected_rates = rates[next(iter(rates))]

        # The cost should match the sum of the expected rates
        expected_cost = (
            expected_rates.energy_price
            + expected_rates.distribution_variable
            + expected_rates.transition_fee
            + expected_rates.oze_fee
            + expected_rates.capacity_fee
            + expected_rates.cogeneration_fee
        ).quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)

        assert cost == expected_cost

    @PROPERTY_TEST_SETTINGS
    @given(
        tariff=sampled_from(SINGLE_ZONE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
        rates_data=single_zone_rates_dict(),
    )
    def test_single_zone_tariff_always_uses_single_zone(
        self, tariff, operator, timestamp, rates_data
    ):
        """For single-zone tariffs (G11, C11, C21), the zone is always SINGLE
        regardless of timestamp.

        **Validates: Requirements 2.1**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        zone = calculator.get_zone_for_time(timestamp, tariff, operator)
        assert zone == TimeZoneName.SINGLE

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
        rates_data=g12w_rates_dict(),
    )
    def test_g12w_weekend_uses_weekend_zone(self, operator, timestamp, rates_data):
        """For G12w on weekends, the zone should be WEEKEND.

        **Validates: Requirements 2.1, 2.4**
        """
        # Force timestamp to be a weekend day
        # weekday() >= 5 means Saturday or Sunday
        assume(timestamp.weekday() >= 5)

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        zone = calculator.get_zone_for_time(timestamp, TariffType.G12W, operator)
        assert zone == TimeZoneName.WEEKEND

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
        rates_data=g13_rates_dict(),
    )
    def test_g13_weekend_uses_pozaszczyt(self, operator, timestamp, rates_data):
        """For G13 on weekends, the zone should be POZASZCZYT.

        **Validates: Requirements 2.1, 2.4**
        """
        assume(timestamp.weekday() >= 5)

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        zone = calculator.get_zone_for_time(timestamp, TariffType.G13, operator)
        assert zone == TimeZoneName.POZASZCZYT

    @PROPERTY_TEST_SETTINGS
    @given(data=tariff_with_matching_rates())
    def test_cost_is_positive(self, data):
        """For any valid rates (all components > 0), the cost is always positive.

        **Validates: Requirements 2.3**
        """
        tariff, operator, timestamp, rates = data

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        cost = calculator.calculate_cost(timestamp, tariff, operator, rates)
        assert cost > Decimal("0")

    @PROPERTY_TEST_SETTINGS
    @given(
        tariff=sampled_from(list(TariffType)),
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
        rce_price=valid_tariff_rate_component(),
    )
    def test_rce_price_replaces_energy_in_calculation(
        self, tariff, operator, timestamp, rce_price
    ):
        """When rce_price is provided, it replaces energy_price in the sum.

        **Validates: Requirements 2.3**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        # Build rates dict appropriate for the tariff
        base_rates = TariffRates(
            energy_price=Decimal("0.5000"),
            distribution_variable=Decimal("0.2000"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        )

        if tariff in SINGLE_ZONE_TARIFFS:
            rates = {TimeZoneName.SINGLE: base_rates}
        elif tariff == TariffType.G12W:
            rates = {TimeZoneName.SZCZYT: base_rates, TimeZoneName.POZASZCZYT: base_rates}
        elif tariff == TariffType.G13:
            rates = {
                TimeZoneName.SZCZYT_PORANNY: base_rates,
                TimeZoneName.SZCZYT_POPOLUDNIOWY: base_rates,
                TimeZoneName.POZASZCZYT: base_rates,
            }
        elif tariff == TariffType.C23:
            rates = {
                TimeZoneName.SZCZYT: base_rates,
                TimeZoneName.POZASZCZYT: base_rates,
                TimeZoneName.NOC: base_rates,
            }
        else:
            rates = {TimeZoneName.SZCZYT: base_rates, TimeZoneName.POZASZCZYT: base_rates}

        cost_with_rce = calculator.calculate_cost(
            timestamp, tariff, operator, rates, rce_price=rce_price
        )

        # Expected: rce_price + distribution + transition + oze + capacity + cogeneration
        expected = (
            rce_price
            + base_rates.distribution_variable
            + base_rates.transition_fee
            + base_rates.oze_fee
            + base_rates.capacity_fee
            + base_rates.cogeneration_fee
        ).quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)

        assert cost_with_rce == expected


# --- Property 5 Tests ---


class TestProperty5TariffOSDValidation:
    """Property 5: Walidacja konfiguracji taryfa/OSD.

    For any invalid combination of tariff and OSD operator or missing required rates,
    the system should display a Polish-language validation error and prevent saving
    the configuration.

    **Validates: Requirements 2.9**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        tariff=sampled_from(list(TariffType)),
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
    )
    def test_missing_zone_rates_raises_error(self, tariff, operator, timestamp):
        """For any tariff/operator/timestamp with empty rates dict,
        calculate_cost raises ValueError.

        **Validates: Requirements 2.9**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        # Empty rates dict — no zone rates available
        empty_rates: dict[TimeZoneName, TariffRates] = {}

        with pytest.raises(ValueError) as exc_info:
            calculator.calculate_cost(timestamp, tariff, operator, empty_rates)

        # Verify Polish-language error message
        error_msg = str(exc_info.value)
        assert "Brak stawek" in error_msg or "brak stawek" in error_msg.lower()

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
    )
    def test_g12_missing_szczyt_zone_uses_fallback(self, operator, timestamp):
        """For G12 with only POZASZCZYT rates (missing SZCZYT), during szczyt hours
        the calculator falls back to available rates with a warning.

        **Validates: Requirements 2.9**
        """
        # Force weekday during szczyt hours (06:00-13:00 for most operators)
        assume(timestamp.weekday() < 5)
        assume(6 <= timestamp.hour < 13)

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        # Only provide POZASZCZYT rates, missing SZCZYT
        pozaszczyt_rates = TariffRates(
            energy_price=Decimal("0.5000"),
            distribution_variable=Decimal("0.0756"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        )
        rates = {TimeZoneName.POZASZCZYT: pozaszczyt_rates}

        # The calculator should use fallback rates (first available zone)
        # This tests that the system handles missing zone gracefully
        zone = calculator.get_zone_for_time(timestamp, TariffType.G12, operator)
        assert zone == TimeZoneName.SZCZYT

        # Cost should still be calculable (fallback to available rates)
        cost = calculator.calculate_cost(timestamp, TariffType.G12, operator, rates)
        # It uses the fallback (POZASZCZYT rates)
        expected = (
            pozaszczyt_rates.energy_price
            + pozaszczyt_rates.distribution_variable
            + pozaszczyt_rates.transition_fee
            + pozaszczyt_rates.oze_fee
            + pozaszczyt_rates.capacity_fee
            + pozaszczyt_rates.cogeneration_fee
        ).quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)
        assert cost == expected

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
        tariff=sampled_from(list(TariffType)),
    )
    def test_all_valid_operator_tariff_combinations_load_successfully(
        self, operator, tariff
    ):
        """For all valid operator/tariff combinations, TariffDefinitionLoader
        loads default rates successfully without errors.

        **Validates: Requirements 2.1, 2.2**
        """
        loader = TariffDefinitionLoader()

        # All combinations of operator and tariff should load successfully
        rates = loader.load_default_rates(operator, tariff)

        # Verify the loaded rates have all required components
        assert rates.energy_price > Decimal("0")
        assert rates.distribution_variable >= Decimal("0")
        assert rates.transition_fee >= Decimal("0")
        assert rates.oze_fee >= Decimal("0")
        assert rates.capacity_fee >= Decimal("0")
        assert rates.cogeneration_fee >= Decimal("0")

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
        tariff=sampled_from(list(TariffType)),
    )
    def test_tariff_definition_loads_for_all_combinations(self, operator, tariff):
        """For all valid tariff types, TariffDefinitionLoader loads the tariff
        definition successfully.

        **Validates: Requirements 2.1**
        """
        loader = TariffDefinitionLoader()

        tariff_def = loader.load_tariff(tariff)

        # Verify basic structure
        assert tariff_def.tariff_type == tariff
        assert len(tariff_def.zones) > 0

    @PROPERTY_TEST_SETTINGS
    @given(
        operator=sampled_from(list(OSDOperator)),
    )
    def test_osd_zones_load_for_all_operators(self, operator):
        """For all valid OSD operators, zone definitions load successfully.

        **Validates: Requirements 2.2**
        """
        loader = TariffDefinitionLoader()

        osd_data = loader.load_osd_zones(operator)

        # Verify basic structure
        assert "operator" in osd_data
        assert "zones" in osd_data
        assert osd_data["operator"] == operator.value

    @PROPERTY_TEST_SETTINGS
    @given(
        tariff=sampled_from(list(TariffType)),
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
    )
    def test_loaded_default_rates_produce_valid_cost(self, tariff, operator, timestamp):
        """For any valid tariff/operator combination with default rates,
        the calculator produces a valid positive cost with 4 decimal places.

        **Validates: Requirements 2.1, 2.2, 2.3**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        # Load all zone rates for this tariff/operator from the rates file
        rates = self._load_all_zone_rates(loader, operator, tariff)

        cost = calculator.calculate_cost(timestamp, tariff, operator, rates)

        # Cost should be positive and have 4 decimal places
        assert cost > Decimal("0")
        assert cost == cost.quantize(_COST_PRECISION)

    @PROPERTY_TEST_SETTINGS
    @given(
        tariff=sampled_from(list(TariffType)),
        operator=sampled_from(list(OSDOperator)),
        timestamp=valid_timestamp(),
    )
    def test_error_messages_are_in_polish(self, tariff, operator, timestamp):
        """Validation errors from the loader contain Polish-language messages.

        **Validates: Requirements 2.9**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)

        # Empty rates should produce Polish error
        try:
            calculator.calculate_cost(timestamp, tariff, operator, {})
            # If no error, that's unexpected for empty rates
            pytest.fail("Expected ValueError for empty rates")
        except ValueError as e:
            error_msg = str(e)
            # Check for Polish characters/words in error message
            polish_indicators = ["Brak", "stawek", "strefy", "taryfa", "taryf"]
            assert any(
                indicator in error_msg for indicator in polish_indicators
            ), f"Error message not in Polish: {error_msg}"

    @staticmethod
    def _load_all_zone_rates(
        loader: TariffDefinitionLoader,
        operator: OSDOperator,
        tariff: TariffType,
    ) -> dict[TimeZoneName, TariffRates]:
        """Helper: load all zone rates for a tariff/operator from rates file."""
        import json
        from pathlib import Path

        rates_file = (
            Path(__file__).parent.parent
            / "custom_components"
            / "peo"
            / "data"
            / "defaults"
            / "rates_2024.json"
        )

        with open(rates_file, encoding="utf-8") as f:
            rates_data = json.load(f)

        operator_data = rates_data["operators"][operator.value]
        tariff_data = operator_data[tariff.value]

        result: dict[TimeZoneName, TariffRates] = {}
        for zone_name_str, zone_rates in tariff_data.items():
            try:
                zone_name = TimeZoneName(zone_name_str)
            except ValueError:
                continue

            result[zone_name] = TariffRates(
                energy_price=Decimal(zone_rates["energy_price"]),
                distribution_variable=Decimal(zone_rates["distribution_variable"]),
                transition_fee=Decimal(zone_rates["transition_fee"]),
                oze_fee=Decimal(zone_rates["oze_fee"]),
                capacity_fee=Decimal(zone_rates["capacity_fee"]),
                cogeneration_fee=Decimal(zone_rates["cogeneration_fee"]),
            )

        return result
