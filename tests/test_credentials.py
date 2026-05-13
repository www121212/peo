"""Unit tests for credentials module.

Tests credential encryption, storage, and separation logic.
Requirements: 9.7, 8.5, 8.9
"""

import pytest

from custom_components.peo.credentials import (
    mask_sensitive_value,
    is_sensitive_key,
    separate_config_data,
    get_credential,
    get_charger_credentials,
    get_solar_api_key,
    validate_credentials_present,
    sanitize_config_for_diagnostics,
    SENSITIVE_KEYS,
    CONNECTION_DATA_KEYS,
    RUNTIME_OPTION_KEYS,
)


class TestMaskSensitiveValue:
    """Tests for mask_sensitive_value function."""

    def test_masks_long_value(self):
        """Long values show first 4 chars and mask the rest."""
        result = mask_sensitive_value("abcdefghij")
        assert result == "abcd******"

    def test_masks_short_value(self):
        """Values <= 4 chars are fully masked."""
        assert mask_sensitive_value("abc") == "****"
        assert mask_sensitive_value("ab") == "****"
        assert mask_sensitive_value("a") == "****"

    def test_masks_empty_value(self):
        """Empty string is fully masked."""
        assert mask_sensitive_value("") == "****"

    def test_masks_exactly_4_chars(self):
        """Exactly 4 chars are fully masked."""
        assert mask_sensitive_value("abcd") == "****"

    def test_masks_5_chars(self):
        """5 chars show first 4 and mask 1."""
        assert mask_sensitive_value("abcde") == "abcd*"


class TestIsSensitiveKey:
    """Tests for is_sensitive_key function."""

    def test_api_key_is_sensitive(self):
        """Keys containing 'api_key' are sensitive."""
        assert is_sensitive_key("solar_api_key") is True
        assert is_sensitive_key("api_key") is True

    def test_password_is_sensitive(self):
        """Keys containing 'password' are sensitive."""
        assert is_sensitive_key("password") is True
        assert is_sensitive_key("user_password") is True

    def test_token_is_sensitive(self):
        """Keys containing 'token' are sensitive."""
        assert is_sensitive_key("token") is True
        assert is_sensitive_key("access_token") is True

    def test_secret_is_sensitive(self):
        """Keys containing 'secret' are sensitive."""
        assert is_sensitive_key("secret") is True
        assert is_sensitive_key("client_secret") is True

    def test_regular_key_not_sensitive(self):
        """Regular keys are not sensitive."""
        assert is_sensitive_key("tariff_type") is False
        assert is_sensitive_key("modules_enabled") is False
        assert is_sensitive_key("grid_limit_kw") is False


class TestSeparateConfigData:
    """Tests for separate_config_data function."""

    def test_connection_data_goes_to_data(self):
        """Connection keys go to ConfigEntry.data."""
        user_input = {
            "modules_enabled": ["prices", "ev"],
            "tariff_type": "G12",
            "osd_operator": "tauron",
        }
        data, options = separate_config_data(user_input)

        assert "modules_enabled" in data
        assert "tariff_type" in data
        assert "osd_operator" in data
        assert len(options) == 0

    def test_runtime_options_go_to_options(self):
        """Runtime parameter keys go to ConfigEntry.options."""
        user_input = {
            "tariff_rates": {"energy": "0.75"},
            "grid_limit_kw": 12.0,
            "price_threshold_cheap": "0.40",
        }
        data, options = separate_config_data(user_input)

        assert "tariff_rates" in options
        assert "grid_limit_kw" in options
        assert "price_threshold_cheap" in options
        assert len(data) == 0

    def test_mixed_input_separated_correctly(self):
        """Mixed input is correctly separated."""
        user_input = {
            "modules_enabled": ["prices"],
            "tariff_type": "G12",
            "osd_operator": "tauron",
            "tariff_rates": {"energy": "0.75"},
            "grid_limit_kw": 12.0,
            "ev_vehicles": [],
        }
        data, options = separate_config_data(user_input)

        assert "modules_enabled" in data
        assert "tariff_type" in data
        assert "osd_operator" in data
        assert "tariff_rates" in options
        assert "grid_limit_kw" in options
        assert "ev_vehicles" in options

    def test_unknown_keys_go_to_data(self):
        """Unknown keys default to ConfigEntry.data."""
        user_input = {"unknown_key": "value"}
        data, options = separate_config_data(user_input)

        assert "unknown_key" in data
        assert len(options) == 0


class TestGetCredential:
    """Tests for get_credential function."""

    def test_returns_existing_credential(self):
        """Returns value when key exists."""
        config = {"solar_api_key": "my_secret_key_123"}
        result = get_credential(config, "solar_api_key")
        assert result == "my_secret_key_123"

    def test_returns_default_when_missing(self):
        """Returns default when key is missing."""
        config = {}
        result = get_credential(config, "solar_api_key", default="fallback")
        assert result == "fallback"

    def test_returns_none_when_missing_no_default(self):
        """Returns None when key is missing and no default."""
        config = {}
        result = get_credential(config, "solar_api_key")
        assert result is None


class TestGetChargerCredentials:
    """Tests for get_charger_credentials function."""

    def test_returns_charger_credentials(self):
        """Returns credentials for matching charger."""
        config = {
            "chargers": [
                {
                    "id": "charger_1",
                    "host": "192.168.1.100",
                    "api_key": "secret123",
                    "protocol": "ocpp16",
                }
            ]
        }
        result = get_charger_credentials(config, "charger_1")
        assert result["host"] == "192.168.1.100"
        assert result["api_key"] == "secret123"
        assert result["protocol"] == "ocpp16"

    def test_returns_none_for_unknown_charger(self):
        """Returns None values for unknown charger ID."""
        config = {"chargers": []}
        result = get_charger_credentials(config, "unknown")
        assert result["host"] is None
        assert result["api_key"] is None
        assert result["protocol"] is None

    def test_returns_none_when_no_chargers(self):
        """Returns None values when no chargers configured."""
        config = {}
        result = get_charger_credentials(config, "charger_1")
        assert result["host"] is None


class TestGetSolarApiKey:
    """Tests for get_solar_api_key function."""

    def test_returns_solar_api_key(self):
        """Returns solar API key when present."""
        config = {"solar_api_key": "solcast_key_abc"}
        result = get_solar_api_key(config)
        assert result == "solcast_key_abc"

    def test_returns_none_when_missing(self):
        """Returns None when solar API key is missing."""
        config = {}
        result = get_solar_api_key(config)
        assert result is None


class TestValidateCredentialsPresent:
    """Tests for validate_credentials_present function."""

    def test_all_present_returns_empty(self):
        """Returns empty list when all required keys are present."""
        config = {"solar_api_key": "key123", "osd_operator": "tauron"}
        result = validate_credentials_present(config, ["solar_api_key", "osd_operator"])
        assert result == []

    def test_missing_keys_returned(self):
        """Returns list of missing keys."""
        config = {"osd_operator": "tauron"}
        result = validate_credentials_present(config, ["solar_api_key", "osd_operator"])
        assert result == ["solar_api_key"]

    def test_empty_string_treated_as_missing(self):
        """Empty string values are treated as missing."""
        config = {"solar_api_key": "  ", "osd_operator": "tauron"}
        result = validate_credentials_present(config, ["solar_api_key"])
        assert result == ["solar_api_key"]

    def test_none_value_treated_as_missing(self):
        """None values are treated as missing."""
        config = {"solar_api_key": None}
        result = validate_credentials_present(config, ["solar_api_key"])
        assert result == ["solar_api_key"]


class TestSanitizeConfigForDiagnostics:
    """Tests for sanitize_config_for_diagnostics function."""

    def test_masks_sensitive_keys(self):
        """Sensitive keys are masked in output."""
        config = {
            "solar_api_key": "my_secret_key_12345",
            "osd_operator": "tauron",
        }
        result = sanitize_config_for_diagnostics(config)
        assert result["solar_api_key"] == "my_s***************"
        assert result["osd_operator"] == "tauron"

    def test_masks_charger_api_keys(self):
        """API keys in charger configs are masked."""
        config = {
            "chargers": [
                {"id": "c1", "api_key": "secret_key_abc", "host": "192.168.1.1"}
            ]
        }
        result = sanitize_config_for_diagnostics(config)
        assert result["chargers"][0]["host"] == "192.168.1.1"
        assert "secret_key_abc" not in str(result["chargers"][0]["api_key"])
        assert result["chargers"][0]["api_key"].startswith("secr")

    def test_preserves_non_sensitive_data(self):
        """Non-sensitive data is preserved unchanged."""
        config = {
            "modules_enabled": ["prices", "ev"],
            "tariff_type": "G12",
            "grid_limit_kw": 12.0,
        }
        result = sanitize_config_for_diagnostics(config)
        assert result == config
