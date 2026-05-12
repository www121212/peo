"""Koordynator danych taryfowych (TariffDataCoordinator) dla Polish Energy Optimizer (PEO).

Odpowiedzialny za cykliczne obliczanie bieżącego kosztu energii,
śledzenie zmian stref czasowych i udostępnianie prognoz kosztów na 24h.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_TARIFF_UPDATE_INTERVAL, DOMAIN
from .enums import OSDOperator, TariffType, TimeZoneName
from .models import HourlyCost, TariffRates
from .tariff_calculator import TariffCalculator

_LOGGER = logging.getLogger(__name__)

# Standardowy interwał aktualizacji (15 minut)
_DEFAULT_TARIFF_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_TARIFF_UPDATE_INTERVAL)


def _get_poland_now() -> datetime:
    """Pobierz aktualny czas w strefie czasowej Polski.

    W produkcji używa zoneinfo.ZoneInfo('Europe/Warsaw'),
    fallback na UTC+1 (CET).
    """
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Warsaw"))
    except ImportError:
        return datetime.now(timezone(timedelta(hours=1)))


@dataclass
class TariffData:
    """Dane taryfowe zwracane przez koordynator."""

    current_cost: Decimal  # PLN/kWh z 4 miejscami po przecinku
    current_zone: TimeZoneName  # aktywna strefa czasowa
    hourly_costs: list[HourlyCost]  # koszty na następne 24h


class TariffDataCoordinator(DataUpdateCoordinator[TariffData]):
    """Koordynator obliczania kosztów taryfowych.

    Rozszerza DataUpdateCoordinator z 15-minutowym interwałem aktualizacji.
    Śledzi zmiany stref czasowych i udostępnia bieżący koszt energii.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        tariff_calculator: TariffCalculator,
        tariff_type: TariffType,
        osd_operator: OSDOperator,
        rates: dict[TimeZoneName, TariffRates],
        price_coordinator: Optional[Any] = None,
    ) -> None:
        """Inicjalizacja koordynatora taryf.

        Args:
            hass: Instancja Home Assistant.
            tariff_calculator: Kalkulator taryf.
            tariff_type: Typ taryfy użytkownika.
            osd_operator: Operator OSD użytkownika.
            rates: Słownik stawek per strefa czasowa.
            price_coordinator: Opcjonalny PriceDataCoordinator (dla taryf dynamicznych z RCE).
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_tariff_coordinator",
            update_interval=_DEFAULT_TARIFF_UPDATE_INTERVAL,
        )
        self._calculator = tariff_calculator
        self._tariff_type = tariff_type
        self._osd_operator = osd_operator
        self._rates = rates
        self._price_coordinator = price_coordinator

        # Stan wewnętrzny
        self._last_zone: Optional[TimeZoneName] = None

    @property
    def tariff_type(self) -> TariffType:
        """Aktualny typ taryfy."""
        return self._tariff_type

    @property
    def osd_operator(self) -> OSDOperator:
        """Aktualny operator OSD."""
        return self._osd_operator

    def update_rates(self, rates: dict[TimeZoneName, TariffRates]) -> None:
        """Aktualizuj stawki taryfowe bez restartu.

        Umożliwia zmianę stawek z ConfigEntry.options bez ponownej
        instalacji integracji.

        Args:
            rates: Nowy słownik stawek per strefa czasowa.
        """
        self._rates = rates
        _LOGGER.info(
            "Zaktualizowano stawki taryfowe dla %s/%s",
            self._tariff_type,
            self._osd_operator,
        )

    async def _async_update_data(self) -> TariffData:
        """Oblicz bieżący koszt energii i prognozę na 24h.

        Returns:
            Obiekt TariffData z bieżącym kosztem, strefą i prognozą.
        """
        now = _get_poland_now()

        # Określ aktywną strefę
        current_zone = self._calculator.get_zone_for_time(
            now, self._tariff_type, self._osd_operator
        )

        # Sprawdź zmianę strefy
        if self._last_zone is not None and current_zone != self._last_zone:
            _LOGGER.info(
                "Zmiana strefy taryfowej: %s → %s (taryfa %s, OSD %s)",
                self._last_zone,
                current_zone,
                self._tariff_type,
                self._osd_operator,
            )
        self._last_zone = current_zone

        # Pobierz cenę RCE jeśli dostępna (dla taryf dynamicznych)
        rce_price = self._get_current_rce_price(now)

        # Oblicz bieżący koszt
        current_cost = self._calculator.calculate_cost(
            now,
            self._tariff_type,
            self._osd_operator,
            self._rates,
            rce_price=rce_price,
        )

        # Oblicz koszty na następne 24h
        rce_prices = self._get_rce_prices_for_forecast()
        hourly_costs = self._calculator.get_hourly_costs(
            now,
            self._tariff_type,
            self._osd_operator,
            self._rates,
            hours=24,
            rce_prices=rce_prices,
        )

        return TariffData(
            current_cost=current_cost,
            current_zone=current_zone,
            hourly_costs=hourly_costs,
        )

    def _get_current_rce_price(self, now: datetime) -> Optional[Decimal]:
        """Pobierz bieżącą cenę RCE z PriceDataCoordinator.

        Args:
            now: Aktualny czas.

        Returns:
            Cena PLN/kWh z RCE lub None jeśli niedostępna.
        """
        if self._price_coordinator is None:
            return None

        today_prices = self._price_coordinator.get_today_prices()
        if today_prices is None:
            return None

        current_hour = now.hour
        for price in today_prices:
            if price.hour == current_hour:
                return price.price_pln_kwh

        return None

    def _get_rce_prices_for_forecast(self) -> Optional[list]:
        """Pobierz ceny RCE do prognozy 24h.

        Returns:
            Lista HourlyPrice lub None jeśli niedostępna.
        """
        if self._price_coordinator is None:
            return None

        return self._price_coordinator.get_today_prices()

    # --- Public API ---

    def get_current_cost(self) -> Decimal:
        """Pobierz bieżący koszt PLN/kWh.

        Returns:
            Bieżący koszt z 4 miejscami po przecinku.
            Decimal("0.0000") jeśli dane niedostępne.
        """
        if self.data is None:
            return Decimal("0.0000")
        return self.data.current_cost

    def get_current_zone(self) -> TimeZoneName:
        """Pobierz aktywną strefę czasową.

        Returns:
            Nazwa bieżącej strefy czasowej.
            TimeZoneName.SINGLE jeśli dane niedostępne.
        """
        if self.data is None:
            return TimeZoneName.SINGLE
        return self.data.current_zone

    def get_hourly_costs(self) -> list[HourlyCost]:
        """Pobierz koszty na następne 24h.

        Returns:
            Lista HourlyCost (24 elementy) lub pusta lista jeśli dane niedostępne.
        """
        if self.data is None:
            return []
        return self.data.hourly_costs
