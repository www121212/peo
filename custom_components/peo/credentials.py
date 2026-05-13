"""Zarządzanie poświadczeniami i bezpieczne przechowywanie danych.

Implementuje:
- Bezpieczne przechowywanie tokenów API i haseł via HA credentials
- Separacja danych połączeniowych (ConfigEntry.data) od parametrów runtime (ConfigEntry.options)
- Kompatybilność z Python 3.12+

Requirements: 9.7, 8.5, 8.9
"""

from __future__ import annotations

import logging
from typing import Any, Final, Optional

from .const import (
    DOMAIN,
    CONF_SOLAR_API_KEY,
    CONF_CHARGERS,
)

_LOGGER = logging.getLogger(__name__)

# Keys that contain sensitive data and should be stored in ConfigEntry.data
SENSITIVE_KEYS: Final[set[str]] = {
    CONF_SOLAR_API_KEY,
    "api_key",
    "password",
    "token",
    "secret",
}

# Keys that are connection data (stored in ConfigEntry.data)
CONNECTION_DATA_KEYS: Final[set[str]] = {
    "modules_enabled",
    "tariff_type",
    "osd_operator",
    "solar_provider",
    CONF_SOLAR_API_KEY,
    CONF_CHARGERS,
}

# Keys that are runtime parameters (stored in ConfigEntry.options)
RUNTIME_OPTION_KEYS: Final[set[str]] = {
    "tariff_rates",
    "ev_vehicles",
    "loads",
    "grid_limit_kw",
    "pv",
    "price_threshold_cheap",
    "update_intervals",
}


def mask_sensitive_value(value: str) -> str:
    """Zamaskuj wrażliwą wartość do wyświetlenia w logach.

    Pokazuje pierwsze 4 znaki i maskuje resztę gwiazdkami.

    Args:
        value: Wartość do zamaskowania.

    Returns:
        Zamaskowana wartość (np. "abcd****").
    """
    if not value or len(value) <= 4:
        return "****"
    return value[:4] + "*" * (len(value) - 4)


def is_sensitive_key(key: str) -> bool:
    """Sprawdź czy klucz zawiera wrażliwe dane.

    Args:
        key: Nazwa klucza konfiguracyjnego.

    Returns:
        True jeśli klucz zawiera dane wrażliwe.
    """
    key_lower = key.lower()
    return any(sensitive in key_lower for sensitive in SENSITIVE_KEYS)


def separate_config_data(
    user_input: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rozdziel dane wejściowe na connection data i runtime options.

    Connection data (ConfigEntry.data):
    - Dane wymagane do połączenia z zewnętrznymi usługami
    - Tokeny API, klucze, adresy hostów
    - Nie zmieniane w runtime bez przeładowania

    Runtime options (ConfigEntry.options):
    - Parametry modyfikowalne w runtime
    - Stawki taryfowe, konfiguracja pojazdów, odbiorników
    - Zmieniane przez Options Flow bez restartu

    Args:
        user_input: Pełne dane wejściowe z Config Flow.

    Returns:
        Tuple (data, options) — rozdzielone dane.
    """
    data: dict[str, Any] = {}
    options: dict[str, Any] = {}

    for key, value in user_input.items():
        if key in CONNECTION_DATA_KEYS:
            data[key] = value
        elif key in RUNTIME_OPTION_KEYS:
            options[key] = value
        else:
            # Unknown keys go to data by default
            data[key] = value

    return data, options


def get_credential(
    config_data: dict[str, Any],
    key: str,
    default: Optional[str] = None,
) -> Optional[str]:
    """Pobierz poświadczenie z danych konfiguracyjnych.

    Bezpiecznie pobiera wartość klucza z ConfigEntry.data.
    Loguje dostęp na poziomie DEBUG (bez wartości).

    Args:
        config_data: Dane z ConfigEntry.data.
        key: Klucz poświadczenia.
        default: Wartość domyślna jeśli klucz nie istnieje.

    Returns:
        Wartość poświadczenia lub default.
    """
    value = config_data.get(key, default)
    if value is not None:
        _LOGGER.debug(
            "Pobrano poświadczenie '%s' (zamaskowane: %s)",
            key,
            mask_sensitive_value(str(value)) if value else "None",
        )
    return value


def get_charger_credentials(
    config_data: dict[str, Any],
    charger_id: str,
) -> dict[str, Optional[str]]:
    """Pobierz poświadczenia ładowarki.

    Args:
        config_data: Dane z ConfigEntry.data.
        charger_id: ID ładowarki.

    Returns:
        Słownik z host, api_key, protocol dla danej ładowarki.
    """
    chargers = config_data.get(CONF_CHARGERS, [])
    for charger in chargers:
        if charger.get("id") == charger_id:
            return {
                "host": charger.get("host"),
                "api_key": charger.get("api_key"),
                "protocol": charger.get("protocol"),
            }
    return {"host": None, "api_key": None, "protocol": None}


def get_solar_api_key(config_data: dict[str, Any]) -> Optional[str]:
    """Pobierz klucz API dostawcy prognoz solarnych.

    Args:
        config_data: Dane z ConfigEntry.data.

    Returns:
        Klucz API lub None.
    """
    return get_credential(config_data, CONF_SOLAR_API_KEY)


def validate_credentials_present(
    config_data: dict[str, Any],
    required_keys: list[str],
) -> list[str]:
    """Sprawdź czy wymagane poświadczenia są obecne.

    Args:
        config_data: Dane z ConfigEntry.data.
        required_keys: Lista wymaganych kluczy.

    Returns:
        Lista brakujących kluczy (pusta jeśli wszystkie obecne).
    """
    missing = []
    for key in required_keys:
        value = config_data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    return missing


def sanitize_config_for_diagnostics(
    config_data: dict[str, Any],
) -> dict[str, Any]:
    """Przygotuj dane konfiguracyjne do diagnostyki (zamaskuj wrażliwe).

    Tworzy kopię danych z zamaskowanymi wartościami wrażliwymi.
    Bezpieczne do wyświetlenia w logach i diagnostyce.

    Args:
        config_data: Oryginalne dane konfiguracyjne.

    Returns:
        Kopia z zamaskowanymi wartościami wrażliwymi.
    """
    sanitized: dict[str, Any] = {}

    for key, value in config_data.items():
        if is_sensitive_key(key):
            if isinstance(value, str):
                sanitized[key] = mask_sensitive_value(value)
            else:
                sanitized[key] = "****"
        elif key == CONF_CHARGERS and isinstance(value, list):
            # Mask API keys in charger configs
            sanitized_chargers = []
            for charger in value:
                sanitized_charger = dict(charger)
                if "api_key" in sanitized_charger:
                    sanitized_charger["api_key"] = mask_sensitive_value(
                        str(sanitized_charger["api_key"])
                    )
                sanitized_chargers.append(sanitized_charger)
            sanitized[key] = sanitized_chargers
        else:
            sanitized[key] = value

    return sanitized
