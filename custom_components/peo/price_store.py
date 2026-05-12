"""Magazyn historii cen (PriceHistoryStore) dla Polish Energy Optimizer (PEO).

Przechowuje historię cen z ostatnich 30 dni w pamięci trwałej
z wykorzystaniem mechanizmu Store Home Assistant.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PRICE_HISTORY_DAYS
from .models import HourlyPrice

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_price_history"
STORAGE_VERSION = 1


class PriceHistoryStore:
    """Magazyn historii cen (30 dni).

    Wykorzystuje Home Assistant Store helper do trwałego przechowywania
    danych cenowych w formacie JSON.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Inicjalizacja magazynu historii cen.

        Args:
            hass: Instancja Home Assistant.
        """
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, list[dict[str, Any]]] | None = None

    async def _async_load(self) -> dict[str, list[dict[str, Any]]]:
        """Załaduj dane z trwałego magazynu.

        Returns:
            Słownik z danymi cenowymi (klucz: data ISO, wartość: lista cen).
        """
        if self._data is None:
            stored = await self._store.async_load()
            if stored is None:
                self._data = {}
                _LOGGER.debug("Magazyn historii cen: brak zapisanych danych, inicjalizacja pustego magazynu")
            else:
                self._data = stored
                _LOGGER.debug(
                    "Magazyn historii cen: załadowano %d dni danych",
                    len(self._data),
                )
        return self._data

    async def _async_save(self) -> None:
        """Zapisz dane do trwałego magazynu."""
        await self._store.async_save(self._data)
        _LOGGER.debug("Magazyn historii cen: zapisano dane (%d dni)", len(self._data) if self._data else 0)

    @staticmethod
    def _serialize_price(price: HourlyPrice) -> dict[str, Any]:
        """Serializuj HourlyPrice do słownika JSON-kompatybilnego.

        Args:
            price: Obiekt HourlyPrice do serializacji.

        Returns:
            Słownik z danymi ceny.
        """
        return {
            "hour": price.hour,
            "price_pln_mwh": str(price.price_pln_mwh),
            "price_pln_kwh": str(price.price_pln_kwh),
            "date": price.date.isoformat(),
        }

    @staticmethod
    def _deserialize_price(data: dict[str, Any]) -> HourlyPrice:
        """Deserializuj słownik do obiektu HourlyPrice.

        Args:
            data: Słownik z danymi ceny.

        Returns:
            Obiekt HourlyPrice.
        """
        return HourlyPrice(
            hour=data["hour"],
            price_pln_mwh=Decimal(data["price_pln_mwh"]),
            price_pln_kwh=Decimal(data["price_pln_kwh"]),
            date=date.fromisoformat(data["date"]),
        )

    async def store(self, target_date: date, prices: list[HourlyPrice]) -> None:
        """Zapisz ceny dzienne do magazynu trwałego.

        Args:
            target_date: Data, dla której zapisywane są ceny.
            prices: Lista 24 obiektów HourlyPrice.
        """
        data = await self._async_load()
        date_key = target_date.isoformat()
        serialized = [self._serialize_price(p) for p in prices]
        data[date_key] = serialized
        await self._async_save()
        _LOGGER.debug(
            "Magazyn historii cen: zapisano %d cen dla daty %s",
            len(prices),
            date_key,
        )

    async def get_history(self, days: int = 30) -> dict[date, list[HourlyPrice]]:
        """Pobierz historię cen z ostatnich N dni.

        Args:
            days: Liczba dni historii do pobrania (domyślnie 30).

        Returns:
            Słownik: data -> lista HourlyPrice.
        """
        data = await self._async_load()
        cutoff = date.today() - timedelta(days=days)
        result: dict[date, list[HourlyPrice]] = {}

        for date_key, price_list in data.items():
            try:
                entry_date = date.fromisoformat(date_key)
            except (ValueError, TypeError):
                _LOGGER.debug(
                    "Magazyn historii cen: pominięto nieprawidłowy klucz daty: %s",
                    date_key,
                )
                continue

            if entry_date >= cutoff:
                try:
                    result[entry_date] = [
                        self._deserialize_price(p) for p in price_list
                    ]
                except (KeyError, TypeError, ValueError) as exc:
                    _LOGGER.debug(
                        "Magazyn historii cen: błąd deserializacji danych dla %s: %s",
                        date_key,
                        exc,
                    )
                    continue

        _LOGGER.debug(
            "Magazyn historii cen: pobrano historię %d dni (żądano %d)",
            len(result),
            days,
        )
        return result

    async def cleanup_old(self) -> None:
        """Usuń wpisy starsze niż PRICE_HISTORY_DAYS (30 dni)."""
        data = await self._async_load()
        cutoff = date.today() - timedelta(days=PRICE_HISTORY_DAYS)
        keys_to_remove = []

        for date_key in list(data.keys()):
            try:
                entry_date = date.fromisoformat(date_key)
            except (ValueError, TypeError):
                # Usuń nieprawidłowe klucze
                keys_to_remove.append(date_key)
                continue

            if entry_date < cutoff:
                keys_to_remove.append(date_key)

        if keys_to_remove:
            for key in keys_to_remove:
                del data[key]
            await self._async_save()
            _LOGGER.debug(
                "Magazyn historii cen: usunięto %d starych wpisów (cutoff: %s)",
                len(keys_to_remove),
                cutoff.isoformat(),
            )
        else:
            _LOGGER.debug("Magazyn historii cen: brak starych wpisów do usunięcia")
