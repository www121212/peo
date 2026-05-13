"""Property-based tests for Config Flow validation.

**Validates: Requirements 7.3**

Property 20: Walidacja danych wejściowych Config Flow
Dla dowolnych nieprawidłowych danych wejściowych w Config Flow (wartości liczbowe
poza zakresem, puste wymagane pola, SoC spoza 0–100%, moc spoza 0–100 kW,
stawki spoza 0–5 PLN/kWh), walidator powinien odrzucić dane i wyświetlić
komunikat błędu w języku polskim.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    floats,
    integers,
    text,
    composite,
    one_of,
    just,
    sampled_from,
    none,
)

from custom_components.peo.config_flow import (
    _validate_tariff_config,
    _validate_ev_config,
    _validate_load_config,
    _validate_pv_config,
    _validate_modules,
)
from custom_components.peo.validators import InputValidator
from custom_components.peo.const import (
    SOC_MIN,
    SOC_MAX,
    POWER_MIN_KW,
    POWER_MAX_KW,
    RATE_MIN_PLN_KWH,
    RATE_MAX_PLN_KWH,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies for invalid inputs ---


@composite
def invalid_soc_values(draw):
    """Generate SoC values outside valid range 0-100."""
    return draw(one_of(
        integers(min_value=-1000, max_value=-1),
        integers(min_value=101, max_value=1000),
    ))


@composite
def invalid_power_values(draw):
    """Generate power values outside valid range 0-100 kW."""
    return draw(one_of(
        floats(min_value=-1000.0, max_value=-0.01, allow_nan=False, allow_infinity=False),
        floats(min_value=100.01, max_value=10000.0, allow_nan=False, allow_infinity=False),
    ))


@composite
def invalid_rate_values(draw):
    """Generate rate values outside valid range 0-5 PLN/kWh."""
    return draw(one_of(
        floats(min_value=-100.0, max_value=-0.01, allow_nan=False, allow_infinity=False),
        floats(min_value=5.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    ))


@composite
def non_numeric_strings(draw):
    """Generate strings that cannot be parsed as numbers."""
    return draw(sampled_from([
        "abc", "xyz", "!@#", "not_a_number", "NaN_text",
        "1.2.3", "12abc", "--5", "++3", "e10",
        "jeden", "dwa", "trzy", "sto",
    ]))


# --- Property 20: Config Flow Input Validation ---


class TestProperty20ConfigFlowValidation:
    """Property 20: Walidacja danych wejściowych Config Flow.

    For any invalid input (out-of-range values, empty required fields,
    invalid SoC/power/rate), the Config Flow displays Polish error messages
    and prevents proceeding.
    """

    @given(soc=invalid_soc_values())
    @PROPERTY_TEST_SETTINGS
    def test_invalid_soc_produces_polish_error(self, soc):
        """Invalid SoC values (< 0 or > 100) produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_soc(soc)

        error_msg = str(exc_info.value)
        # Error message must be in Polish
        assert any(
            polish_word in error_msg
            for polish_word in ["zakresie", "poza", "SoC", "dozwolonym"]
        ), f"Error message not in Polish: {error_msg}"

    @given(power=invalid_power_values())
    @PROPERTY_TEST_SETTINGS
    def test_invalid_power_produces_polish_error(self, power):
        """Invalid power values (< 0 or > 100 kW) produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_power(power)

        error_msg = str(exc_info.value)
        # Error message must be in Polish
        assert any(
            polish_word in error_msg
            for polish_word in ["zakresie", "poza", "Moc", "dozwolonym"]
        ), f"Error message not in Polish: {error_msg}"

    @given(rate=invalid_rate_values())
    @PROPERTY_TEST_SETTINGS
    def test_invalid_rate_produces_polish_error(self, rate):
        """Invalid rate values (< 0 or > 5 PLN/kWh) produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_rate(rate)

        error_msg = str(exc_info.value)
        # Error message must be in Polish
        assert any(
            polish_word in error_msg
            for polish_word in ["zakresie", "poza", "Stawka", "dozwolonym", "taryfowa"]
        ), f"Error message not in Polish: {error_msg}"

    @given(rate=invalid_rate_values())
    @PROPERTY_TEST_SETTINGS
    def test_tariff_config_rejects_invalid_rates(self, rate):
        """Tariff config validation rejects out-of-range rate values.

        **Validates: Requirements 7.3**
        """
        rate_str = str(round(rate, 4))
        user_input = {
            "osd_operator": "tauron",
            "tariff_type": "G12",
            "energy_price": rate_str,
        }
        errors = _validate_tariff_config(user_input)
        assert "energy_price" in errors, (
            f"Rate {rate_str} should be rejected but was accepted"
        )

    @given(soc=invalid_soc_values())
    @PROPERTY_TEST_SETTINGS
    def test_ev_config_rejects_invalid_soc(self, soc):
        """EV config validation rejects out-of-range SoC values.

        **Validates: Requirements 7.3**
        """
        # target_soc must be >= 10 in EV config, but we test the underlying
        # validator which checks 0-100 range
        user_input = {
            "vehicle_name": "Test EV",
            "soc_entity_id": "sensor.ev_soc",
            "target_soc": str(soc),
        }
        errors = _validate_ev_config(user_input)
        assert "target_soc" in errors, (
            f"SoC {soc} should be rejected but was accepted"
        )

    @given(power=invalid_power_values())
    @PROPERTY_TEST_SETTINGS
    def test_ev_config_rejects_invalid_power(self, power):
        """EV config validation rejects out-of-range power values.

        **Validates: Requirements 7.3**
        """
        user_input = {
            "vehicle_name": "Test EV",
            "soc_entity_id": "sensor.ev_soc",
            "max_charging_power_kw": str(power),
        }
        errors = _validate_ev_config(user_input)
        assert "max_charging_power_kw" in errors, (
            f"Power {power} should be rejected but was accepted"
        )

    @given(rate=invalid_rate_values())
    @PROPERTY_TEST_SETTINGS
    def test_load_config_rejects_invalid_threshold(self, rate):
        """Load config validation rejects out-of-range threshold values.

        **Validates: Requirements 7.3**
        """
        rate_str = str(round(rate, 4))
        user_input = {
            "load_name": "Test Load",
            "entity_id": "switch.test",
            "threshold_on": rate_str,
        }
        errors = _validate_load_config(user_input)
        assert "threshold_on" in errors, (
            f"Threshold {rate_str} should be rejected but was accepted"
        )

    @given(value=non_numeric_strings())
    @PROPERTY_TEST_SETTINGS
    def test_non_numeric_soc_produces_polish_error(self, value):
        """Non-numeric SoC values produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_soc(value)

        error_msg = str(exc_info.value)
        assert any(
            polish_word in error_msg
            for polish_word in ["Nieprawidłowa", "wartość", "SoC", "wymagana"]
        ), f"Error message not in Polish: {error_msg}"

    @given(value=non_numeric_strings())
    @PROPERTY_TEST_SETTINGS
    def test_non_numeric_power_produces_polish_error(self, value):
        """Non-numeric power values produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_power(value)

        error_msg = str(exc_info.value)
        assert any(
            polish_word in error_msg
            for polish_word in ["Nieprawidłowa", "wartość", "mocy", "wymagana"]
        ), f"Error message not in Polish: {error_msg}"

    @given(value=non_numeric_strings())
    @PROPERTY_TEST_SETTINGS
    def test_non_numeric_rate_produces_polish_error(self, value):
        """Non-numeric rate values produce Polish error messages.

        **Validates: Requirements 7.3**
        """
        with pytest.raises(ValueError) as exc_info:
            InputValidator.validate_rate(value)

        error_msg = str(exc_info.value)
        assert any(
            polish_word in error_msg
            for polish_word in ["Nieprawidłowa", "wartość", "stawki", "wymagana"]
        ), f"Error message not in Polish: {error_msg}"

    def test_empty_modules_produces_polish_error(self):
        """Empty module selection produces Polish error message.

        **Validates: Requirements 7.3**
        """
        result = _validate_modules([])
        assert result is not None
        assert any(
            polish_word in result
            for polish_word in ["Musisz", "wybrać", "moduł"]
        ), f"Error message not in Polish: {result}"

    def test_empty_required_fields_tariff(self):
        """Empty required fields in tariff config produce Polish errors.

        **Validates: Requirements 7.3**
        """
        errors = _validate_tariff_config({})
        assert "osd_operator" in errors
        assert "tariff_type" in errors
        # Verify Polish language
        for field, msg in errors.items():
            assert any(
                polish_word in msg
                for polish_word in ["wymagany", "wymagana", "Operator", "Typ"]
            ), f"Error for {field} not in Polish: {msg}"

    def test_empty_required_fields_ev(self):
        """Empty required fields in EV config produce Polish errors.

        **Validates: Requirements 7.3**
        """
        errors = _validate_ev_config({})
        assert "vehicle_name" in errors
        assert "soc_entity_id" in errors
        for field, msg in errors.items():
            assert any(
                polish_word in msg
                for polish_word in ["wymagana", "wymagany", "Nazwa", "Encja"]
            ), f"Error for {field} not in Polish: {msg}"

    def test_empty_required_fields_load(self):
        """Empty required fields in load config produce Polish errors.

        **Validates: Requirements 7.3**
        """
        errors = _validate_load_config({})
        assert "load_name" in errors
        assert "entity_id" in errors
        for field, msg in errors.items():
            assert any(
                polish_word in msg
                for polish_word in ["wymagana", "wymagany", "Nazwa", "Encja"]
            ), f"Error for {field} not in Polish: {msg}"

    def test_empty_required_fields_pv(self):
        """Empty required fields in PV config produce Polish errors.

        **Validates: Requirements 7.3**
        """
        errors = _validate_pv_config({})
        assert "solar_provider" in errors
        assert "solar_api_key" in errors
        for field, msg in errors.items():
            assert any(
                polish_word in msg
                for polish_word in ["wymagany", "wymagana", "Dostawca", "Klucz"]
            ), f"Error for {field} not in Polish: {msg}"
