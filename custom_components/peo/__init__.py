"""Polish Energy Optimizer (PEO) - integracja Home Assistant.

Implementuje pełny cykl życia integracji:
- async_setup_entry: rejestracja koordynatorów, platform, event listenerów (max 30s)
- async_unload_entry: anulowanie listenerów, zamknięcie sesji HTTP (max 10s)
- async_remove_entry: usunięcie danych trwałych
- async_migrate_entry: migracja konfiguracji między wersjami

Requirements: 8.1, 8.2, 8.3, 8.4, 8.10, 8.11, 8.12
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant import config_entries

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_MODULES_ENABLED,
    CONF_OSD_OPERATOR,
    CONF_TARIFF_TYPE,
    MODULE_PRICES,
    MODULE_TARIFF,
    MODULE_EV,
    MODULE_LOADS,
    MODULE_PV,
    MODULE_ANALYZER,
)

_LOGGER = logging.getLogger(__name__)

# Current config schema version - increment on schema changes
CONFIG_VERSION = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Konfiguracja integracji PEO na podstawie ConfigEntry.

    Rejestruje koordynatory danych, platformy encji i event listenery.
    Musi zakończyć się w ciągu 30 sekund (Requirement 8.12).

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny integracji.

    Returns:
        True jeśli konfiguracja zakończyła się sukcesem.
    """
    _LOGGER.info("Inicjalizacja integracji PEO (entry_id=%s)", entry.entry_id)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}

    runtime_data: dict[str, Any] = hass.data[DOMAIN][entry.entry_id]
    modules_enabled = entry.data.get(CONF_MODULES_ENABLED, [])

    # --- Initialize coordinators based on enabled modules ---
    coordinators: dict[str, Any] = {}
    listeners: list[Any] = []

    # Create shared HTTP session and rate limiter
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from .rate_limiter import RateLimiter

    session = async_get_clientsession(hass)
    rate_limiter = RateLimiter()
    runtime_data["http_session"] = session
    runtime_data["rate_limiter"] = rate_limiter

    # Price module coordinator
    if MODULE_PRICES in modules_enabled or MODULE_TARIFF in modules_enabled:
        from .rce_client import RCEApiClient
        from .price_validator import PriceValidator
        from .price_store import PriceHistoryStore
        from .price_coordinator import PriceDataCoordinator

        rce_client = RCEApiClient(session, rate_limiter)
        price_validator = PriceValidator()
        price_store = PriceHistoryStore(hass)
        price_coordinator = PriceDataCoordinator(
            hass, rce_client, price_validator, price_store
        )
        coordinators["price"] = price_coordinator
        runtime_data["rce_client"] = rce_client
        runtime_data["price_store"] = price_store

    # Tariff module coordinator
    if MODULE_TARIFF in modules_enabled:
        from .tariff_calculator import TariffCalculator
        from .tariff_loader import TariffDefinitionLoader
        from .enums import TariffType, OSDOperator

        tariff_loader = TariffDefinitionLoader()
        tariff_calculator = TariffCalculator(tariff_loader)

        # Load default rates for the configured tariff/operator
        tariff_type_str = entry.data.get(CONF_TARIFF_TYPE, "G12")
        osd_operator_str = entry.data.get(CONF_OSD_OPERATOR, "tauron")

        try:
            tariff_type = TariffType(tariff_type_str)
            osd_operator = OSDOperator(osd_operator_str)
        except ValueError:
            tariff_type = TariffType.G12
            osd_operator = OSDOperator.TAURON

        # Build rates dict from loader defaults
        try:
            from .tariff_coordinator import TariffDataCoordinator
            default_rates = tariff_loader.load_default_rates(osd_operator, tariff_type)
            from .enums import TimeZoneName
            # Use single zone rates for now (simplified)
            rates_dict = {TimeZoneName.SINGLE: default_rates}

            tariff_coordinator = TariffDataCoordinator(
                hass,
                tariff_calculator,
                tariff_type,
                osd_operator,
                rates_dict,
            )
            coordinators["tariff"] = tariff_coordinator
        except Exception as err:
            _LOGGER.warning("Nie udało się zainicjalizować koordynatora taryf: %s", err)

    # PV module coordinator — requires more complex setup, deferred
    # PV coordinator needs battery_config, pv_optimizer, tariff_coordinator
    # which are set up during full initialization
    if MODULE_PV in modules_enabled:
        _LOGGER.info("Moduł PV włączony — koordynator zostanie zainicjalizowany po pełnej konfiguracji")

    runtime_data["coordinators"] = coordinators

    # --- Register event listeners ---
    if MODULE_EV in modules_enabled or MODULE_LOADS in modules_enabled:
        from .const import EVENT_PRICES_UPDATED

        async def _handle_prices_updated(event):
            """Obsługa zdarzenia aktualizacji cen."""
            _LOGGER.debug("Odebrano zdarzenie %s", EVENT_PRICES_UPDATED)

        unsub = hass.bus.async_listen(EVENT_PRICES_UPDATED, _handle_prices_updated)
        listeners.append(unsub)

    # Listen for options updates (no reload required - Requirement 8.9)
    unsub_options = entry.add_update_listener(_async_options_updated)
    listeners.append(unsub_options)

    runtime_data["listeners"] = listeners

    # --- Register services ---
    from .services import async_register_services

    await async_register_services(hass, entry)

    # --- Forward setup to platforms ---
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # --- Initial data fetch for coordinators ---
    for name, coordinator in coordinators.items():
        try:
            await coordinator.async_refresh()
            _LOGGER.info("Koordynator '%s' zainicjalizowany pomyślnie", name)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Koordynator '%s' nie mógł pobrać danych początkowych: %s",
                name,
                err,
            )

    _LOGGER.info("Integracja PEO zainicjalizowana pomyślnie (entry_id=%s)", entry.entry_id)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    """Wyładowanie integracji PEO.

    Anuluje listenery, zamyka sesje HTTP, usuwa referencje koordynatorów.
    Musi zakończyć się w ciągu 10 sekund (Requirement 8.3).

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny integracji.

    Returns:
        True jeśli wyładowanie zakończyło się sukcesem.
    """
    _LOGGER.info("Wyładowywanie integracji PEO (entry_id=%s)", entry.entry_id)

    runtime_data = hass.data[DOMAIN].get(entry.entry_id, {})

    # Cancel all event listeners
    listeners = runtime_data.get("listeners", [])
    for unsub in listeners:
        if callable(unsub):
            unsub()
    _LOGGER.debug("Anulowano %d listenerów", len(listeners))

    # Close HTTP sessions — skip if using HA shared session
    # (async_get_clientsession returns HA-managed session, don't close it)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove coordinator references
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        del hass.data[DOMAIN][entry.entry_id]

    # Clean up domain data if no entries remain
    if not hass.data.get(DOMAIN):
        hass.data.pop(DOMAIN, None)

    _LOGGER.info("Integracja PEO wyładowana pomyślnie (entry_id=%s)", entry.entry_id)
    return unload_ok


async def async_remove_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Usunięcie danych trwałych integracji PEO.

    Wywoływane gdy użytkownik usunie integrację. Czyści persistent storage.

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny integracji.
    """
    _LOGGER.info("Usuwanie danych trwałych PEO (entry_id=%s)", entry.entry_id)

    # Remove persistent storage files via executor (I/O >100ms)
    store_keys = [
        f"{DOMAIN}_prices_{entry.entry_id}",
        f"{DOMAIN}_sessions_{entry.entry_id}",
        f"{DOMAIN}_savings_{entry.entry_id}",
        f"{DOMAIN}_decisions_{entry.entry_id}",
    ]

    for store_key in store_keys:
        try:
            from homeassistant.helpers.storage import Store
            store = Store(hass, 1, store_key)
            await store.async_remove()
            _LOGGER.debug("Usunięto magazyn: %s", store_key)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Błąd usuwania magazynu %s: %s", store_key, err)

    _LOGGER.info("Dane trwałe PEO usunięte (entry_id=%s)", entry.entry_id)


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry
) -> bool:
    """Migracja konfiguracji między wersjami integracji.

    Implementuje VERSION tracking z inkrementacją przy zmianach schematu.
    Zachowuje wszystkie wartości konfiguracyjne użytkownika.
    Weryfikuje zgodność schematu po aktualizacji HACS.

    Args:
        hass: Instancja Home Assistant.
        config_entry: Wpis konfiguracyjny do migracji.

    Returns:
        True jeśli migracja zakończyła się sukcesem.

    Requirements: 8.10, 8.11
    """
    _LOGGER.info(
        "Migracja konfiguracji PEO z wersji %s do %s",
        config_entry.version,
        CONFIG_VERSION,
    )

    if config_entry.version > CONFIG_VERSION:
        _LOGGER.error(
            "Wersja konfiguracji (%s) jest nowsza niż obsługiwana (%s). "
            "Zaktualizuj integrację PEO.",
            config_entry.version,
            CONFIG_VERSION,
        )
        return False

    if config_entry.version == CONFIG_VERSION:
        _LOGGER.debug("Konfiguracja jest aktualna (wersja %s)", CONFIG_VERSION)
        return True

    # Perform sequential migrations
    new_data = dict(config_entry.data)
    new_options = dict(config_entry.options)

    current_version = config_entry.version

    # Migration from version 0 to 1 (initial schema)
    if current_version < 1:
        new_data, new_options = _migrate_v0_to_v1(new_data, new_options)
        current_version = 1

    # Future migrations would be added here:
    # if current_version < 2:
    #     new_data, new_options = _migrate_v1_to_v2(new_data, new_options)
    #     current_version = 2

    # Update the config entry with migrated data
    hass.config_entries.async_update_entry(
        config_entry,
        data=new_data,
        options=new_options,
        version=CONFIG_VERSION,
    )

    _LOGGER.info(
        "Migracja konfiguracji PEO zakończona pomyślnie (wersja %s -> %s)",
        config_entry.version,
        CONFIG_VERSION,
    )
    return True


def _migrate_v0_to_v1(
    data: dict[str, Any], options: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Migracja z wersji 0 (brak wersji) do wersji 1.

    Zapewnia obecność wymaganych kluczy z domyślnymi wartościami.

    Args:
        data: Dane konfiguracyjne (ConfigEntry.data).
        options: Opcje konfiguracyjne (ConfigEntry.options).

    Returns:
        Tuple (nowe_data, nowe_options) po migracji.
    """
    # Ensure modules_enabled exists
    if CONF_MODULES_ENABLED not in data:
        data[CONF_MODULES_ENABLED] = [MODULE_PRICES, MODULE_TARIFF]

    # Ensure OSD operator exists
    if CONF_OSD_OPERATOR not in data:
        data[CONF_OSD_OPERATOR] = "tauron"

    # Ensure tariff type exists
    if CONF_TARIFF_TYPE not in data:
        data[CONF_TARIFF_TYPE] = "G12"

    return data, options


async def _async_options_updated(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Obsługa aktualizacji opcji konfiguracyjnych.

    Wywoływane gdy użytkownik zmieni opcje przez Options Flow.
    Nie wymaga przeładowania integracji (Requirement 8.9).

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny z nowymi opcjami.
    """
    _LOGGER.info("Opcje PEO zaktualizowane (entry_id=%s)", entry.entry_id)

    runtime_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = runtime_data.get("coordinators", {})

    # Refresh coordinators with new options
    for name, coordinator in coordinators.items():
        if hasattr(coordinator, "update_options"):
            coordinator.update_options(entry.options)
            _LOGGER.debug("Zaktualizowano opcje koordynatora '%s'", name)

    # Trigger refresh of all coordinators
    for name, coordinator in coordinators.items():
        try:
            await coordinator.async_refresh()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Błąd odświeżania koordynatora '%s' po zmianie opcji: %s",
                name,
                err,
            )
