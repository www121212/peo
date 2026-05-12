"""Adaptery ładowarek EV dla Polish Energy Optimizer (PEO).

Moduł implementuje abstrakcyjną klasę ChargerAdapter oraz konkretne adaptery
dla protokołów: OCPP 1.6/2.0, Tesla Wall Connector, Wallbox Pulsar, OpenEVSE.

Każdy adapter obsługuje logikę retry: 3 próby z 10-sekundowymi interwałami
przy niepowodzeniu komendy sterującej.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Optional

from .const import CHARGER_RETRY_COUNT, CHARGER_RETRY_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass
class ChargerStatus:
    """Status ładowarki EV."""

    is_charging: bool
    current_power_kw: float
    temperature: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ChargerLimits:
    """Limity mocy i prądu ładowarki."""

    max_power_kw: float
    max_current_a: float
    min_power_kw: float


def with_retry(func: Callable) -> Callable:
    """Dekorator retry: 3 próby z CHARGER_RETRY_INTERVAL (10s) między nimi.

    Stosowany do metod adapterów ładowarek, które mogą zakończyć się
    niepowodzeniem z powodu problemów komunikacyjnych.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exception: Optional[Exception] = None
        for attempt in range(1, CHARGER_RETRY_COUNT + 1):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exception = exc
                _LOGGER.warning(
                    "Próba %d/%d nieudana dla %s: %s",
                    attempt,
                    CHARGER_RETRY_COUNT,
                    func.__name__,
                    exc,
                )
                if attempt < CHARGER_RETRY_COUNT:
                    await asyncio.sleep(CHARGER_RETRY_INTERVAL)
        _LOGGER.error(
            "Wszystkie %d próby nieudane dla %s: %s",
            CHARGER_RETRY_COUNT,
            func.__name__,
            last_exception,
        )
        raise last_exception  # type: ignore[misc]

    return wrapper


class ChargerAdapter(ABC):
    """Abstrakcyjny adapter ładowarki EV.

    Definiuje interfejs komunikacji z ładowarkami różnych producentów.
    Każda implementacja musi obsługiwać: start/stop ładowania,
    odczyt statusu i limitów mocy.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja adaptera.

        Args:
            host: Adres hosta ładowarki (IP lub hostname).
            api_key: Klucz API do uwierzytelnienia.
            entity_id: ID encji Home Assistant powiązanej z ładowarką.
        """
        self.host = host
        self.api_key = api_key
        self.entity_id = entity_id

    @abstractmethod
    async def start_charging(self, power_kw: float) -> bool:
        """Rozpocznij ładowanie z zadaną mocą.

        Args:
            power_kw: Żądana moc ładowania w kW.

        Returns:
            True jeśli komenda została przyjęta, False w przeciwnym razie.
        """

    @abstractmethod
    async def stop_charging(self) -> bool:
        """Zatrzymaj ładowanie.

        Returns:
            True jeśli komenda została przyjęta, False w przeciwnym razie.
        """

    @abstractmethod
    async def get_status(self) -> ChargerStatus:
        """Pobierz aktualny status ładowarki.

        Returns:
            ChargerStatus z informacjami o stanie ładowania.
        """

    @abstractmethod
    async def get_limits(self) -> ChargerLimits:
        """Pobierz limity mocy i prądu ładowarki.

        Returns:
            ChargerLimits z maksymalnymi/minimalnymi wartościami.
        """


class OCPPChargerAdapter(ChargerAdapter):
    """Adapter ładowarki OCPP 1.6/2.0.

    Komunikacja przez protokół OCPP (WebSocket).
    Obsługuje komendy RemoteStartTransaction/RemoteStopTransaction (1.6)
    oraz RequestStartTransaction/RequestStopTransaction (2.0).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja adaptera OCPP."""
        super().__init__(host=host, api_key=api_key, entity_id=entity_id)
        _LOGGER.debug("Inicjalizacja OCPPChargerAdapter: host=%s", host)

    @with_retry
    async def start_charging(self, power_kw: float) -> bool:
        """Rozpocznij ładowanie przez OCPP RemoteStartTransaction.

        Args:
            power_kw: Żądana moc ładowania w kW.

        Returns:
            True jeśli ładowarka zaakceptowała komendę.
        """
        _LOGGER.info(
            "OCPP: Wysyłanie RemoteStartTransaction z mocą %.1f kW", power_kw
        )
        # Stub: rzeczywista implementacja wyśle komendę OCPP przez WebSocket
        raise NotImplementedError(
            "OCPPChargerAdapter.start_charging wymaga połączenia WebSocket z ładowarką"
        )

    @with_retry
    async def stop_charging(self) -> bool:
        """Zatrzymaj ładowanie przez OCPP RemoteStopTransaction.

        Returns:
            True jeśli ładowarka zaakceptowała komendę.
        """
        _LOGGER.info("OCPP: Wysyłanie RemoteStopTransaction")
        raise NotImplementedError(
            "OCPPChargerAdapter.stop_charging wymaga połączenia WebSocket z ładowarką"
        )

    @with_retry
    async def get_status(self) -> ChargerStatus:
        """Pobierz status przez OCPP StatusNotification.

        Returns:
            ChargerStatus z danymi z ładowarki OCPP.
        """
        _LOGGER.debug("OCPP: Pobieranie statusu ładowarki")
        raise NotImplementedError(
            "OCPPChargerAdapter.get_status wymaga połączenia WebSocket z ładowarką"
        )

    @with_retry
    async def get_limits(self) -> ChargerLimits:
        """Pobierz limity mocy z konfiguracji OCPP.

        Returns:
            ChargerLimits odczytane z ładowarki.
        """
        _LOGGER.debug("OCPP: Pobieranie limitów mocy")
        raise NotImplementedError(
            "OCPPChargerAdapter.get_limits wymaga połączenia WebSocket z ładowarką"
        )


class TeslaChargerAdapter(ChargerAdapter):
    """Adapter Tesla Wall Connector.

    Komunikacja przez Tesla API (REST).
    Obsługuje sterowanie mocą ładowania i odczyt statusu.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja adaptera Tesla."""
        super().__init__(host=host, api_key=api_key, entity_id=entity_id)
        _LOGGER.debug("Inicjalizacja TeslaChargerAdapter: host=%s", host)

    @with_retry
    async def start_charging(self, power_kw: float) -> bool:
        """Rozpocznij ładowanie przez Tesla API.

        Args:
            power_kw: Żądana moc ładowania w kW.

        Returns:
            True jeśli Tesla API zaakceptowało komendę.
        """
        _LOGGER.info(
            "Tesla: Wysyłanie komendy start_charging z mocą %.1f kW", power_kw
        )
        raise NotImplementedError(
            "TeslaChargerAdapter.start_charging wymaga aktywnego tokenu Tesla API"
        )

    @with_retry
    async def stop_charging(self) -> bool:
        """Zatrzymaj ładowanie przez Tesla API.

        Returns:
            True jeśli Tesla API zaakceptowało komendę.
        """
        _LOGGER.info("Tesla: Wysyłanie komendy stop_charging")
        raise NotImplementedError(
            "TeslaChargerAdapter.stop_charging wymaga aktywnego tokenu Tesla API"
        )

    @with_retry
    async def get_status(self) -> ChargerStatus:
        """Pobierz status z Tesla API.

        Returns:
            ChargerStatus z danymi z Tesla Wall Connector.
        """
        _LOGGER.debug("Tesla: Pobieranie statusu ładowarki")
        raise NotImplementedError(
            "TeslaChargerAdapter.get_status wymaga aktywnego tokenu Tesla API"
        )

    @with_retry
    async def get_limits(self) -> ChargerLimits:
        """Pobierz limity mocy z Tesla API.

        Returns:
            ChargerLimits odczytane z Tesla Wall Connector.
        """
        _LOGGER.debug("Tesla: Pobieranie limitów mocy")
        raise NotImplementedError(
            "TeslaChargerAdapter.get_limits wymaga aktywnego tokenu Tesla API"
        )


class WallboxChargerAdapter(ChargerAdapter):
    """Adapter Wallbox Pulsar.

    Komunikacja przez Wallbox Cloud API (REST).
    Obsługuje sterowanie mocą ładowania i odczyt statusu.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja adaptera Wallbox."""
        super().__init__(host=host, api_key=api_key, entity_id=entity_id)
        _LOGGER.debug("Inicjalizacja WallboxChargerAdapter: host=%s", host)

    @with_retry
    async def start_charging(self, power_kw: float) -> bool:
        """Rozpocznij ładowanie przez Wallbox API.

        Args:
            power_kw: Żądana moc ładowania w kW.

        Returns:
            True jeśli Wallbox API zaakceptowało komendę.
        """
        _LOGGER.info(
            "Wallbox: Wysyłanie komendy start_charging z mocą %.1f kW", power_kw
        )
        raise NotImplementedError(
            "WallboxChargerAdapter.start_charging wymaga uwierzytelnienia Wallbox API"
        )

    @with_retry
    async def stop_charging(self) -> bool:
        """Zatrzymaj ładowanie przez Wallbox API.

        Returns:
            True jeśli Wallbox API zaakceptowało komendę.
        """
        _LOGGER.info("Wallbox: Wysyłanie komendy stop_charging")
        raise NotImplementedError(
            "WallboxChargerAdapter.stop_charging wymaga uwierzytelnienia Wallbox API"
        )

    @with_retry
    async def get_status(self) -> ChargerStatus:
        """Pobierz status z Wallbox API.

        Returns:
            ChargerStatus z danymi z Wallbox Pulsar.
        """
        _LOGGER.debug("Wallbox: Pobieranie statusu ładowarki")
        raise NotImplementedError(
            "WallboxChargerAdapter.get_status wymaga uwierzytelnienia Wallbox API"
        )

    @with_retry
    async def get_limits(self) -> ChargerLimits:
        """Pobierz limity mocy z Wallbox API.

        Returns:
            ChargerLimits odczytane z Wallbox Pulsar.
        """
        _LOGGER.debug("Wallbox: Pobieranie limitów mocy")
        raise NotImplementedError(
            "WallboxChargerAdapter.get_limits wymaga uwierzytelnienia Wallbox API"
        )


class OpenEVSEChargerAdapter(ChargerAdapter):
    """Adapter OpenEVSE.

    Komunikacja przez OpenEVSE REST API (lokalne HTTP).
    Obsługuje sterowanie mocą ładowania i odczyt statusu.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> None:
        """Inicjalizacja adaptera OpenEVSE."""
        super().__init__(host=host, api_key=api_key, entity_id=entity_id)
        _LOGGER.debug("Inicjalizacja OpenEVSEChargerAdapter: host=%s", host)

    @with_retry
    async def start_charging(self, power_kw: float) -> bool:
        """Rozpocznij ładowanie przez OpenEVSE REST API.

        Args:
            power_kw: Żądana moc ładowania w kW.

        Returns:
            True jeśli OpenEVSE zaakceptowało komendę.
        """
        _LOGGER.info(
            "OpenEVSE: Wysyłanie komendy start_charging z mocą %.1f kW", power_kw
        )
        raise NotImplementedError(
            "OpenEVSEChargerAdapter.start_charging wymaga połączenia HTTP z OpenEVSE"
        )

    @with_retry
    async def stop_charging(self) -> bool:
        """Zatrzymaj ładowanie przez OpenEVSE REST API.

        Returns:
            True jeśli OpenEVSE zaakceptowało komendę.
        """
        _LOGGER.info("OpenEVSE: Wysyłanie komendy stop_charging")
        raise NotImplementedError(
            "OpenEVSEChargerAdapter.stop_charging wymaga połączenia HTTP z OpenEVSE"
        )

    @with_retry
    async def get_status(self) -> ChargerStatus:
        """Pobierz status z OpenEVSE REST API.

        Returns:
            ChargerStatus z danymi z OpenEVSE.
        """
        _LOGGER.debug("OpenEVSE: Pobieranie statusu ładowarki")
        raise NotImplementedError(
            "OpenEVSEChargerAdapter.get_status wymaga połączenia HTTP z OpenEVSE"
        )

    @with_retry
    async def get_limits(self) -> ChargerLimits:
        """Pobierz limity mocy z OpenEVSE REST API.

        Returns:
            ChargerLimits odczytane z OpenEVSE.
        """
        _LOGGER.debug("OpenEVSE: Pobieranie limitów mocy")
        raise NotImplementedError(
            "OpenEVSEChargerAdapter.get_limits wymaga połączenia HTTP z OpenEVSE"
        )
