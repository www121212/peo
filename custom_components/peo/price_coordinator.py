"""Koordynator danych cenowych (PriceDataCoordinator) dla Polish Energy Optimizer (PEO).

Odpowiedzialny za cykliczne pobieranie cen z API RCE PSE, walidację,
przechowywanie w historii oraz udostępnianie danych cenowych jako PriceData.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_PRICE_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_PRICES_UPDATED,
    HOURS_PER_DAY,
)
from .enums import PriceDataStatus
from .models import HourlyPrice, PriceData, PriceStats
from .price_store import PriceHistoryStore
from .price_validator import PriceValidator
from .rce_client import RCEApiClient, RCEApiError

_LOGGER = logging.getLogger(__name__)

# Interwał skrócony do 15 minut gdy oczekujemy na ceny jutrzejsze
_WAITING_UPDATE_INTERVAL = timedelta(minutes=15)

# Standardowy interwał aktualizacji
_DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_PRICE_UPDATE_INTERVAL)

# Godzina po której oczekujemy cen na jutro (13:30 czasu lokalnego)
_TOMORROW_PRICES_EXPECTED_HOUR = 13
_TOMORROW_PRICES_EXPECTED_MINUTE = 30

# Próg czasu bez pomyślnego pobrania danych (24h) -> status NO_DATA
_NO_DATA_THRESHOLD = timedelta(hours=24)

# Strefa czasowa Polski (CET/CEST)
_POLAND_TZ_OFFSET_WINTER = timezone(timedelta(hours=1))


def _get_poland_now() -> datetime:
    """Pobierz aktualny czas w strefie czasowej Polski (uproszczony UTC+1/+2).

    W produkcji powinno używać zoneinfo.ZoneInfo('Europe/Warsaw'),
    ale dla uproszczenia używamy UTC+1 (CET).
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Warsaw"))
    except ImportError:
        return datetime.now(_POLAND_TZ_OFFSET_WINTER)


class PriceDataCoordinator(DataUpdateCoordinator[PriceData]):
    """Koordynator pobierania cen z RCE PSE.

    Rozszerza DataUpdateCoordinator z 60-minutowym interwałem aktualizacji.
    Po 13:30, gdy ceny na jutro są niedostępne, skraca interwał do 15 minut.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        rce_client: RCEApiClient,
        price_validator: PriceValidator,
        price_store: PriceHistoryStore,
    ) -> None:
        """Inicjalizacja koordynatora cen.

        Args:
            hass: Instancja Home Assistant.
            rce_client: Klient API RCE PSE.
            price_validator: Walidator danych cenowych.
            price_store: Magazyn historii cen.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_price_coordinator",
            update_interval=_DEFAULT_UPDATE_INTERVAL,
        )
        self._rce_client = rce_client
        self._validator = price_validator
        self._store = price_store

        # Stan wewnętrzny
        self._last_successful_fetch: datetime | None = None
        self._today_prices: list[HourlyPrice] | None = None
        self._tomorrow_prices: list[HourlyPrice] | None = None
        self._status: PriceDataStatus = PriceDataStatus.NO_DATA

    @property
    def last_successful_fetch(self) -> datetime | None:
        """Timestamp ostatniego pomyślnego pobrania danych."""
        return self._last_successful_fetch

    @property
    def status(self) -> PriceDataStatus:
        """Aktualny status danych cenowych."""
        return self._status

    async def _async_update_data(self) -> PriceData:
        """Pobierz, zwaliduj i zapisz ceny energii.

        Returns:
            Obiekt PriceData z cenami na dziś, jutro, statusem i statystykami.

        Raises:
            UpdateFailed: Gdy nie ma żadnych danych (ani bieżących, ani historycznych).
        """
        now = _get_poland_now()
        today = now.date()
        tomorrow = today + timedelta(days=1)

        # Próba pobrania cen na dziś
        today_fetch_success = await self._fetch_and_validate_prices(today)

        # Próba pobrania cen na jutro (po 13:30)
        tomorrow_available = False
        if self._is_after_tomorrow_expected_time(now):
            tomorrow_available = await self._fetch_and_validate_prices(
                tomorrow, is_tomorrow=True
            )

        # Aktualizacja statusu
        self._update_status(now, today_fetch_success, tomorrow_available)

        # Aktualizacja interwału
        self._adjust_update_interval(now, tomorrow_available)

        # Wyzwolenie zdarzenia przy sukcesie
        if today_fetch_success:
            self._fire_prices_updated_event(today)

        # Budowanie odpowiedzi
        if self._today_prices is None:
            raise UpdateFailed(
                "Brak danych cenowych — nie udało się pobrać cen na dziś"
            )

        stats = self._compute_stats(self._today_prices)

        return PriceData(
            today=self._today_prices,
            tomorrow=self._tomorrow_prices,
            status=self._status,
            last_successful_fetch=self._last_successful_fetch or now,
            stats=stats,
        )

    async def _fetch_and_validate_prices(
        self, target_date: date, is_tomorrow: bool = False
    ) -> bool:
        """Pobierz i zwaliduj ceny na podany dzień.

        Args:
            target_date: Data, dla której pobieramy ceny.
            is_tomorrow: Czy to ceny na jutro (True) czy na dziś (False).

        Returns:
            True jeśli pobranie i walidacja zakończyły się sukcesem.
        """
        try:
            prices = await self._rce_client.fetch_prices(target_date)
        except RCEApiError as err:
            _LOGGER.warning(
                "Błąd pobierania cen RCE na dzień %s: %s",
                target_date.isoformat(),
                err,
            )
            return False

        # Walidacja
        if not self._validator.validate(prices):
            _LOGGER.warning(
                "Walidacja cen na dzień %s nie powiodła się — dane odrzucone",
                target_date.isoformat(),
            )
            return False

        # Zapis do magazynu
        try:
            await self._store.store(target_date, prices)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Błąd zapisu cen do magazynu dla daty %s: %s",
                target_date.isoformat(),
                err,
            )
            # Kontynuujemy mimo błędu zapisu — dane są w pamięci

        # Aktualizacja stanu wewnętrznego
        if is_tomorrow:
            self._tomorrow_prices = prices
        else:
            self._today_prices = prices
            self._last_successful_fetch = _get_poland_now()

        return True

    def _is_after_tomorrow_expected_time(self, now: datetime) -> bool:
        """Sprawdź czy jest po 13:30 (czas oczekiwania na ceny jutrzejsze).

        Args:
            now: Aktualny czas w strefie polskiej.

        Returns:
            True jeśli jest po 13:30.
        """
        return (
            now.hour > _TOMORROW_PRICES_EXPECTED_HOUR
            or (
                now.hour == _TOMORROW_PRICES_EXPECTED_HOUR
                and now.minute >= _TOMORROW_PRICES_EXPECTED_MINUTE
            )
        )

    def _update_status(
        self,
        now: datetime,
        today_success: bool,
        tomorrow_available: bool,
    ) -> None:
        """Aktualizuj status danych cenowych.

        Args:
            now: Aktualny czas.
            today_success: Czy pobranie cen na dziś się powiodło.
            tomorrow_available: Czy ceny na jutro są dostępne.
        """
        if today_success:
            if (
                self._is_after_tomorrow_expected_time(now)
                and not tomorrow_available
                and self._tomorrow_prices is None
            ):
                self._status = PriceDataStatus.WAITING
            else:
                self._status = PriceDataStatus.OK
        elif self._today_prices is not None:
            # Mamy stare dane — sprawdź czy nie minęło 24h
            if self._last_successful_fetch is not None:
                elapsed = now - self._last_successful_fetch
                if elapsed >= _NO_DATA_THRESHOLD:
                    self._status = PriceDataStatus.NO_DATA
                else:
                    self._status = PriceDataStatus.STALE
            else:
                self._status = PriceDataStatus.STALE
        else:
            self._status = PriceDataStatus.NO_DATA

    def _adjust_update_interval(
        self, now: datetime, tomorrow_available: bool
    ) -> None:
        """Dostosuj interwał aktualizacji.

        Po 13:30, gdy ceny na jutro niedostępne — skróć do 15 min.
        W przeciwnym razie — standardowe 60 min.

        Args:
            now: Aktualny czas.
            tomorrow_available: Czy ceny na jutro są dostępne.
        """
        if (
            self._is_after_tomorrow_expected_time(now)
            and not tomorrow_available
            and self._tomorrow_prices is None
        ):
            self.update_interval = _WAITING_UPDATE_INTERVAL
        else:
            self.update_interval = _DEFAULT_UPDATE_INTERVAL

    def _fire_prices_updated_event(self, target_date: date) -> None:
        """Wyzwól zdarzenie peo_prices_updated.

        Args:
            target_date: Data, dla której pobrano ceny.
        """
        self.hass.bus.async_fire(
            EVENT_PRICES_UPDATED,
            {
                "date": target_date.isoformat(),
                "source": "rce_pse",
            },
        )
        _LOGGER.info(
            "Wyzwolono zdarzenie %s dla daty %s",
            EVENT_PRICES_UPDATED,
            target_date.isoformat(),
        )

    @staticmethod
    def _compute_stats(prices: list[HourlyPrice]) -> PriceStats:
        """Oblicz statystyki cenowe (min, max, avg, min_hour, max_hour).

        Args:
            prices: Lista 24 obiektów HourlyPrice.

        Returns:
            Obiekt PriceStats ze statystykami.
        """
        if not prices:
            return PriceStats(
                min_price=Decimal("0"),
                max_price=Decimal("0"),
                avg_price=Decimal("0"),
                min_hour=0,
                max_hour=0,
            )

        min_price = prices[0].price_pln_mwh
        max_price = prices[0].price_pln_mwh
        min_hour = prices[0].hour
        max_hour = prices[0].hour
        total = Decimal("0")

        for p in prices:
            total += p.price_pln_mwh
            if p.price_pln_mwh < min_price:
                min_price = p.price_pln_mwh
                min_hour = p.hour
            if p.price_pln_mwh > max_price:
                max_price = p.price_pln_mwh
                max_hour = p.hour

        avg_price = (total / len(prices)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        return PriceStats(
            min_price=min_price,
            max_price=max_price,
            avg_price=avg_price,
            min_hour=min_hour,
            max_hour=max_hour,
        )

    # --- Public API methods ---

    def get_current_price(self) -> Decimal | None:
        """Pobierz bieżącą cenę PLN/MWh na aktualną godzinę.

        Returns:
            Cena PLN/MWh lub None jeśli dane niedostępne.
        """
        if self._today_prices is None:
            return None
        now = _get_poland_now()
        current_hour = now.hour
        for price in self._today_prices:
            if price.hour == current_hour:
                return price.price_pln_mwh
        return None

    def get_today_prices(self) -> list[HourlyPrice] | None:
        """Pobierz 24 ceny na dziś.

        Returns:
            Lista HourlyPrice lub None jeśli dane niedostępne.
        """
        return self._today_prices

    def get_tomorrow_prices(self) -> list[HourlyPrice] | None:
        """Pobierz ceny na jutro (jeśli dostępne).

        Returns:
            Lista HourlyPrice lub None jeśli niedostępne.
        """
        return self._tomorrow_prices

    def get_price_stats(self) -> PriceStats | None:
        """Pobierz statystyki cenowe na dziś.

        Returns:
            Obiekt PriceStats lub None jeśli dane niedostępne.
        """
        if self._today_prices is None:
            return None
        return self._compute_stats(self._today_prices)

    def is_data_stale(self) -> bool:
        """Sprawdź czy dane cenowe są nieaktualne.

        Returns:
            True jeśli status to STALE lub NO_DATA.
        """
        return self._status in (PriceDataStatus.STALE, PriceDataStatus.NO_DATA)
