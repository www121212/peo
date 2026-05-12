"""Monitor heartbeat z mechanizmem failsafe dla Polish Energy Optimizer (PEO).

Moduł odpowiada za wykrywanie sytuacji, w której integracja przestaje
odpowiadać (brak aktualizacji heartbeat przez 5 minut) i przełączanie
sterowanych urządzeń w tryb domyślny zdefiniowany w konfiguracji.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from homeassistant.components.persistent_notification import async_create
from homeassistant.core import HomeAssistant

from .const import DOMAIN, FAILSAFE_TIMEOUT, HEARTBEAT_INTERVAL
from .models import LoadConfig

_LOGGER = logging.getLogger(__name__)


class HeartbeatMonitor:
    """Monitor heartbeat z mechanizmem failsafe.

    Sprawdza regularnie, czy integracja jest aktywna. Jeśli heartbeat
    nie zostanie zaktualizowany przez FAILSAFE_TIMEOUT (5 minut),
    aktywuje mechanizm awaryjny — przełącza urządzenia w tryb domyślny
    i powiadamia użytkownika.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        load_configs: list[LoadConfig],
    ) -> None:
        """Inicjalizacja monitora heartbeat.

        Args:
            hass: Instancja Home Assistant.
            load_configs: Lista konfiguracji odbiorników odraczalnych
                z informacją o stanie failsafe (failsafe_state).
        """
        self._hass = hass
        self._load_configs = load_configs
        self._last_heartbeat: datetime = datetime.now()
        self._failsafe_active: bool = False
        self._heartbeat_interval = timedelta(seconds=HEARTBEAT_INTERVAL)
        self._failsafe_timeout = timedelta(seconds=FAILSAFE_TIMEOUT)

        _LOGGER.debug(
            "HeartbeatMonitor zainicjalizowany: interwał=%ss, timeout=%ss, "
            "liczba odbiorników=%d",
            HEARTBEAT_INTERVAL,
            FAILSAFE_TIMEOUT,
            len(load_configs),
        )

    @property
    def last_heartbeat(self) -> datetime:
        """Zwróć timestamp ostatniego heartbeat."""
        return self._last_heartbeat

    @property
    def is_failsafe_active(self) -> bool:
        """Czy mechanizm failsafe jest aktywny."""
        return self._failsafe_active

    async def pulse(self) -> None:
        """Aktualizuj timestamp heartbeat.

        Wywoływane cyklicznie co HEARTBEAT_INTERVAL (60s) przez
        koordynator integracji, aby potwierdzić że system działa.
        """
        self._last_heartbeat = datetime.now()
        _LOGGER.debug("Heartbeat pulse: %s", self._last_heartbeat.isoformat())

        # Jeśli failsafe był aktywny i heartbeat wrócił, resetujemy
        if self._failsafe_active:
            self._failsafe_active = False
            _LOGGER.info(
                "Heartbeat przywrócony — mechanizm failsafe dezaktywowany"
            )

    async def check_failsafe(self) -> bool:
        """Sprawdź czy nie minął timeout failsafe.

        Porównuje bieżący czas z ostatnim heartbeat. Jeśli upłynęło
        więcej niż FAILSAFE_TIMEOUT (5 minut), aktywuje mechanizm awaryjny.

        Returns:
            True jeśli timeout został przekroczony (failsafe aktywowany
            lub już aktywny), False jeśli heartbeat jest w normie.
        """
        now = datetime.now()
        elapsed = now - self._last_heartbeat

        if elapsed > self._failsafe_timeout:
            if not self._failsafe_active:
                _LOGGER.warning(
                    "Heartbeat timeout! Ostatni heartbeat: %s "
                    "(%.1f s temu, limit: %s s). Aktywacja failsafe.",
                    self._last_heartbeat.isoformat(),
                    elapsed.total_seconds(),
                    FAILSAFE_TIMEOUT,
                )
                await self.activate_failsafe()
            return True

        _LOGGER.debug(
            "Heartbeat OK: ostatni %s (%.1f s temu)",
            self._last_heartbeat.isoformat(),
            elapsed.total_seconds(),
        )
        return False

    async def activate_failsafe(self) -> None:
        """Przełącz urządzenia w tryb domyślny i powiadom użytkownika.

        Iteruje po skonfigurowanych odbiornikach i ustawia każdy
        w stan failsafe_state (True=ON, False=OFF). Wysyła trwałe
        powiadomienie przez mechanizm powiadomień Home Assistant.
        """
        self._failsafe_active = True
        _LOGGER.error(
            "Aktywacja mechanizmu failsafe — przełączanie %d urządzeń "
            "w tryb domyślny",
            len(self._load_configs),
        )

        failed_loads: list[str] = []

        for load in self._load_configs:
            service = "turn_on" if load.failsafe_state else "turn_off"
            domain = load.entity_id.split(".")[0] if "." in load.entity_id else "switch"

            try:
                await self._hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": load.entity_id},
                    blocking=True,
                )
                _LOGGER.info(
                    "Failsafe: %s → %s (entity: %s)",
                    load.name,
                    "ON" if load.failsafe_state else "OFF",
                    load.entity_id,
                )
            except Exception:  # noqa: BLE001
                failed_loads.append(load.name)
                _LOGGER.error(
                    "Failsafe: nie udało się przełączyć %s (entity: %s)",
                    load.name,
                    load.entity_id,
                    exc_info=True,
                )

        # Powiadomienie użytkownika
        notification_message = (
            "⚠️ **Mechanizm awaryjny PEO aktywowany**\n\n"
            "Integracja Polish Energy Optimizer nie odpowiadała przez "
            f"{FAILSAFE_TIMEOUT // 60} minut. Wszystkie sterowane urządzenia "
            "zostały przełączone w tryb domyślny (failsafe).\n\n"
        )

        if failed_loads:
            notification_message += (
                "**Urządzenia, których nie udało się przełączyć:**\n"
                + "\n".join(f"- {name}" for name in failed_loads)
                + "\n\n"
            )

        notification_message += (
            "Sprawdź stan integracji i urządzeń. "
            "Automatyczne sterowanie zostanie wznowione po przywróceniu "
            "heartbeat."
        )

        async_create(
            self._hass,
            notification_message,
            title="PEO — Mechanizm awaryjny",
            notification_id=f"{DOMAIN}_failsafe_activated",
        )

        _LOGGER.warning(
            "Failsafe zakończony: %d urządzeń przełączonych, %d błędów",
            len(self._load_configs) - len(failed_loads),
            len(failed_loads),
        )
