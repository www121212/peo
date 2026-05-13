"""Rejestracja usług (services) Home Assistant dla PEO.

Implementuje usługi:
- peo.start_ev_charging: rozpocznij ładowanie EV
- peo.stop_ev_charging: zatrzymaj ładowanie EV
- peo.set_load_threshold: ustaw próg cenowy odbiornika
- peo.force_load_on: wymuś włączenie odbiornika
- peo.force_load_off: wymuś wyłączenie odbiornika
- peo.recalculate_schedule: przelicz harmonogramy (max 30s)

Każda usługa definiuje schemat parametrów walidowany przy wywołaniu.
Nieprawidłowe parametry zwracają ServiceValidationError bez zmiany stanu.

Requirements: 12.1, 12.3, 12.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant import config_entries

from .const import (
    DOMAIN,
    SERVICE_START_EV_CHARGING,
    SERVICE_STOP_EV_CHARGING,
    SERVICE_SET_LOAD_THRESHOLD,
    SERVICE_FORCE_LOAD_ON,
    SERVICE_FORCE_LOAD_OFF,
    SERVICE_RECALCULATE_SCHEDULE,
    EVENT_SCHEDULE_UPDATED,
)

_LOGGER = logging.getLogger(__name__)


class ServiceValidationError(Exception):
    """Błąd walidacji parametrów usługi.

    Zwracany gdy parametry wywołania usługi są nieprawidłowe.
    Nie powoduje zmiany stanu systemu.
    """

    def __init__(self, message: str) -> None:
        """Inicjalizacja błędu walidacji.

        Args:
            message: Komunikat opisujący przyczynę błędu.
        """
        super().__init__(message)
        self.message = message


# --- Service parameter schemas ---

SCHEMA_START_EV_CHARGING = vol.Schema({
    vol.Required("vehicle_id"): str,
    vol.Optional("power_kw"): vol.All(
        vol.Coerce(float), vol.Range(min=1.4, max=22.0)
    ),
    vol.Optional("target_soc"): vol.All(
        vol.Coerce(int), vol.Range(min=10, max=100)
    ),
})

SCHEMA_STOP_EV_CHARGING = vol.Schema({
    vol.Required("vehicle_id"): str,
})

SCHEMA_SET_LOAD_THRESHOLD = vol.Schema({
    vol.Required("load_id"): str,
    vol.Required("threshold_on"): vol.All(
        vol.Coerce(float), vol.Range(min=0.01, max=5.0)
    ),
    vol.Optional("threshold_off"): vol.All(
        vol.Coerce(float), vol.Range(min=0.01, max=5.0)
    ),
})

SCHEMA_FORCE_LOAD_ON = vol.Schema({
    vol.Required("load_id"): str,
    vol.Optional("duration_minutes"): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=1440)
    ),
})

SCHEMA_FORCE_LOAD_OFF = vol.Schema({
    vol.Required("load_id"): str,
    vol.Optional("duration_minutes"): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=1440)
    ),
})

SCHEMA_RECALCULATE_SCHEDULE = vol.Schema({
    vol.Optional("modules"): vol.All(
        list, [vol.In(["ev", "loads", "pv", "all"])]
    ),
})


async def async_register_services(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    """Rejestracja usług PEO w Home Assistant.

    Args:
        hass: Instancja Home Assistant.
        entry: Wpis konfiguracyjny integracji.
    """
    # Only register services once (first entry)
    if hass.services.has_service(DOMAIN, SERVICE_START_EV_CHARGING):
        return

    async def handle_start_ev_charging(call: ServiceCall) -> None:
        """Obsługa usługi start_ev_charging."""
        try:
            params = SCHEMA_START_EV_CHARGING(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry start_ev_charging: {err}"
            ) from err

        vehicle_id = params["vehicle_id"]
        power_kw = params.get("power_kw")
        target_soc = params.get("target_soc")

        _LOGGER.info(
            "Usługa start_ev_charging: vehicle=%s, power=%s kW, target_soc=%s%%",
            vehicle_id,
            power_kw,
            target_soc,
        )

        # Find the entry runtime data
        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        # Delegate to EV scheduler if available
        coordinators = runtime_data.get("coordinators", {})
        ev_scheduler = runtime_data.get("ev_scheduler")
        if ev_scheduler and hasattr(ev_scheduler, "start_charging"):
            await ev_scheduler.start_charging(vehicle_id, power_kw, target_soc)
        else:
            _LOGGER.warning(
                "Moduł EV nie jest aktywny — nie można rozpocząć ładowania"
            )
            raise ServiceValidationError(
                "Moduł EV nie jest aktywny. Włącz moduł EV w konfiguracji."
            )

    async def handle_stop_ev_charging(call: ServiceCall) -> None:
        """Obsługa usługi stop_ev_charging."""
        try:
            params = SCHEMA_STOP_EV_CHARGING(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry stop_ev_charging: {err}"
            ) from err

        vehicle_id = params["vehicle_id"]
        _LOGGER.info("Usługa stop_ev_charging: vehicle=%s", vehicle_id)

        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        ev_scheduler = runtime_data.get("ev_scheduler")
        if ev_scheduler and hasattr(ev_scheduler, "stop_charging"):
            await ev_scheduler.stop_charging(vehicle_id)
        else:
            raise ServiceValidationError(
                "Moduł EV nie jest aktywny. Włącz moduł EV w konfiguracji."
            )

    async def handle_set_load_threshold(call: ServiceCall) -> None:
        """Obsługa usługi set_load_threshold."""
        try:
            params = SCHEMA_SET_LOAD_THRESHOLD(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry set_load_threshold: {err}"
            ) from err

        load_id = params["load_id"]
        threshold_on = params["threshold_on"]
        threshold_off = params.get("threshold_off")

        _LOGGER.info(
            "Usługa set_load_threshold: load=%s, on=%s, off=%s",
            load_id,
            threshold_on,
            threshold_off,
        )

        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        load_manager = runtime_data.get("load_manager")
        if load_manager and hasattr(load_manager, "set_threshold"):
            await load_manager.set_threshold(load_id, threshold_on, threshold_off)
        else:
            raise ServiceValidationError(
                "Moduł odbiorników nie jest aktywny. "
                "Włącz moduł loads w konfiguracji."
            )

    async def handle_force_load_on(call: ServiceCall) -> None:
        """Obsługa usługi force_load_on."""
        try:
            params = SCHEMA_FORCE_LOAD_ON(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry force_load_on: {err}"
            ) from err

        load_id = params["load_id"]
        duration = params.get("duration_minutes")

        _LOGGER.info(
            "Usługa force_load_on: load=%s, duration=%s min",
            load_id,
            duration,
        )

        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        load_manager = runtime_data.get("load_manager")
        if load_manager and hasattr(load_manager, "force_on"):
            await load_manager.force_on(load_id, duration)
        else:
            raise ServiceValidationError(
                "Moduł odbiorników nie jest aktywny. "
                "Włącz moduł loads w konfiguracji."
            )

    async def handle_force_load_off(call: ServiceCall) -> None:
        """Obsługa usługi force_load_off."""
        try:
            params = SCHEMA_FORCE_LOAD_OFF(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry force_load_off: {err}"
            ) from err

        load_id = params["load_id"]
        duration = params.get("duration_minutes")

        _LOGGER.info(
            "Usługa force_load_off: load=%s, duration=%s min",
            load_id,
            duration,
        )

        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        load_manager = runtime_data.get("load_manager")
        if load_manager and hasattr(load_manager, "force_off"):
            await load_manager.force_off(load_id, duration)
        else:
            raise ServiceValidationError(
                "Moduł odbiorników nie jest aktywny. "
                "Włącz moduł loads w konfiguracji."
            )

    async def handle_recalculate_schedule(call: ServiceCall) -> None:
        """Obsługa usługi recalculate_schedule.

        Przelicza harmonogramy wszystkich modułów w ciągu 30 sekund
        i wyzwala zdarzenie peo_schedule_updated.
        """
        try:
            params = SCHEMA_RECALCULATE_SCHEDULE(dict(call.data))
        except vol.Invalid as err:
            raise ServiceValidationError(
                f"Nieprawidłowe parametry recalculate_schedule: {err}"
            ) from err

        modules_to_recalculate = params.get("modules", ["all"])

        _LOGGER.info(
            "Usługa recalculate_schedule: modules=%s", modules_to_recalculate
        )

        runtime_data = _get_runtime_data(hass)
        if runtime_data is None:
            raise ServiceValidationError("Integracja PEO nie jest zainicjalizowana")

        coordinators = runtime_data.get("coordinators", {})

        # Refresh relevant coordinators
        recalculated = []
        for name, coordinator in coordinators.items():
            if "all" in modules_to_recalculate or name in modules_to_recalculate:
                try:
                    await coordinator.async_refresh()
                    recalculated.append(name)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning(
                        "Błąd przeliczania koordynatora '%s': %s", name, err
                    )

        # Fire peo_schedule_updated event
        hass.bus.async_fire(
            EVENT_SCHEDULE_UPDATED,
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "modules_recalculated": recalculated,
                "source": "service_call",
            },
        )

        _LOGGER.info(
            "Przeliczono harmonogramy: %s", ", ".join(recalculated) or "brak"
        )

    # Register all services
    hass.services.async_register(
        DOMAIN, SERVICE_START_EV_CHARGING, handle_start_ev_charging,
        schema=SCHEMA_START_EV_CHARGING,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_EV_CHARGING, handle_stop_ev_charging,
        schema=SCHEMA_STOP_EV_CHARGING,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_LOAD_THRESHOLD, handle_set_load_threshold,
        schema=SCHEMA_SET_LOAD_THRESHOLD,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_LOAD_ON, handle_force_load_on,
        schema=SCHEMA_FORCE_LOAD_ON,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_LOAD_OFF, handle_force_load_off,
        schema=SCHEMA_FORCE_LOAD_OFF,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RECALCULATE_SCHEDULE, handle_recalculate_schedule,
        schema=SCHEMA_RECALCULATE_SCHEDULE,
    )

    _LOGGER.info("Zarejestrowano %d usług PEO", 6)


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Wyrejestrowanie usług PEO.

    Args:
        hass: Instancja Home Assistant.
    """
    services = [
        SERVICE_START_EV_CHARGING,
        SERVICE_STOP_EV_CHARGING,
        SERVICE_SET_LOAD_THRESHOLD,
        SERVICE_FORCE_LOAD_ON,
        SERVICE_FORCE_LOAD_OFF,
        SERVICE_RECALCULATE_SCHEDULE,
    ]
    for service in services:
        hass.services.async_remove(DOMAIN, service)

    _LOGGER.info("Wyrejestrowano usługi PEO")


def _get_runtime_data(hass: HomeAssistant) -> dict[str, Any] | None:
    """Pobierz dane runtime pierwszego aktywnego wpisu PEO.

    Args:
        hass: Instancja Home Assistant.

    Returns:
        Słownik danych runtime lub None jeśli brak aktywnych wpisów.
    """
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id, data in domain_data.items():
        if isinstance(data, dict):
            return data
    return None
