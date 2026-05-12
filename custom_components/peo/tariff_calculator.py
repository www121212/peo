"""Kalkulator taryf energetycznych dla Polish Energy Optimizer (PEO).

Oblicza rzeczywisty koszt kWh z uwzględnieniem taryfy, operatora OSD
i wszystkich składników opłat regulowanych.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .enums import OSDOperator, TariffType, TimeZoneName
from .models import HourlyCost, HourlyPrice, TariffDefinition, TariffRates
from .tariff_loader import TariffDefinitionLoader

_LOGGER = logging.getLogger(__name__)

# Precision for cost calculations (4 decimal places)
_COST_PRECISION = Decimal("0.0001")


class TariffCalculator:
    """Kalkulator kosztów energii z uwzględnieniem taryf i OSD.

    Oblicza pełny koszt kWh jako sumę 6 składników:
    - cena energii (stała lub RCE)
    - opłata dystrybucyjna zmienna (per OSD/strefa)
    - opłata przejściowa
    - opłata OZE
    - opłata mocowa
    - opłata kogeneracyjna
    """

    def __init__(self, loader: TariffDefinitionLoader) -> None:
        """Inicjalizacja kalkulatora.

        Args:
            loader: Instancja TariffDefinitionLoader do ładowania definicji taryf.
        """
        self._loader = loader

    def get_zone_for_time(
        self,
        timestamp: datetime,
        tariff: TariffType,
        operator: OSDOperator,
    ) -> TimeZoneName:
        """Określ aktywną strefę czasową dla danego momentu.

        Args:
            timestamp: Moment w czasie do sprawdzenia.
            tariff: Typ taryfy.
            operator: Operator OSD.

        Returns:
            Nazwa strefy czasowej obowiązującej w danym momencie.
        """
        # Single-zone tariffs: G11, C11, C21
        if tariff in (TariffType.G11, TariffType.C11, TariffType.C21):
            return TimeZoneName.SINGLE

        # G12w: weekend check first
        if tariff == TariffType.G12W:
            if self._is_weekend(timestamp):
                return TimeZoneName.WEEKEND

        # G13: weekend/holiday → POZASZCZYT, then seasonal zones
        if tariff == TariffType.G13:
            if self._is_weekend(timestamp):
                return TimeZoneName.POZASZCZYT
            return self._get_g13_zone(timestamp, operator)

        # Standard multi-zone tariffs: G12, G12w (weekday), G12r, C12a, C12b, C22a, C22b, C23
        return self._get_standard_zone(timestamp, tariff, operator)

    def calculate_cost(
        self,
        timestamp: datetime,
        tariff: TariffType,
        operator: OSDOperator,
        rates: dict[TimeZoneName, TariffRates],
        rce_price: Optional[Decimal] = None,
    ) -> Decimal:
        """Oblicz pełny koszt kWh z dokładnością do 4 miejsc po przecinku.

        Formuła: energy_price + distribution_variable + transition_fee
                 + oze_fee + capacity_fee + cogeneration_fee

        Args:
            timestamp: Moment w czasie.
            tariff: Typ taryfy.
            operator: Operator OSD.
            rates: Słownik stawek per strefa czasowa.
            rce_price: Opcjonalna cena RCE (PLN/kWh) — zastępuje energy_price
                       dla taryf dynamicznych (np. G12r).

        Returns:
            Pełny koszt kWh z 4 miejscami po przecinku.
        """
        zone = self.get_zone_for_time(timestamp, tariff, operator)

        # Get rates for the active zone
        zone_rates = self._get_rates_for_zone(zone, rates, tariff)

        # Calculate total cost
        energy = rce_price if rce_price is not None else zone_rates.energy_price
        total = (
            energy
            + zone_rates.distribution_variable
            + zone_rates.transition_fee
            + zone_rates.oze_fee
            + zone_rates.capacity_fee
            + zone_rates.cogeneration_fee
        )

        return total.quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)

    def get_hourly_costs(
        self,
        start: datetime,
        tariff: TariffType,
        operator: OSDOperator,
        rates: dict[TimeZoneName, TariffRates],
        hours: int = 24,
        rce_prices: Optional[list[HourlyPrice]] = None,
    ) -> list[HourlyCost]:
        """Zwróć koszty na N godzin do przodu.

        Args:
            start: Początek zakresu czasowego.
            tariff: Typ taryfy.
            operator: Operator OSD.
            rates: Słownik stawek per strefa czasowa.
            hours: Liczba godzin (domyślnie 24).
            rce_prices: Opcjonalna lista cen RCE (dla taryf dynamicznych).

        Returns:
            Lista HourlyCost dla każdej godziny w zakresie.
        """
        # Build RCE price lookup if provided
        rce_lookup: dict[int, Decimal] = {}
        if rce_prices:
            for price in rce_prices:
                rce_lookup[price.hour] = price.price_pln_kwh

        result: list[HourlyCost] = []
        for i in range(hours):
            ts = start + timedelta(hours=i)
            hour = ts.hour

            # Get RCE price for this hour if available
            rce_price = rce_lookup.get(hour)

            zone = self.get_zone_for_time(ts, tariff, operator)
            zone_rates = self._get_rates_for_zone(zone, rates, tariff)

            cost = self.calculate_cost(ts, tariff, operator, rates, rce_price)

            result.append(
                HourlyCost(
                    hour=hour,
                    timestamp=ts,
                    cost_pln_kwh=cost,
                    zone=zone,
                    components=zone_rates,
                )
            )

        return result

    def _get_g13_zone(
        self, timestamp: datetime, operator: OSDOperator
    ) -> TimeZoneName:
        """Określ strefę G13 na podstawie sezonu i godziny.

        G13 ma strefy sezonowe (zima: paź-mar, lato: kwi-wrz)
        z różnymi godzinami szczytu porannego i popołudniowego.
        """
        osd_data = self._loader.load_osd_zones(operator)
        g13_data = osd_data.get("zones", {}).get("G13", {})
        seasonal_data = g13_data.get("seasonal", {})

        if not seasonal_data:
            # Fallback: no seasonal data, return POZASZCZYT
            _LOGGER.warning(
                "Brak danych sezonowych G13 dla operatora %s", operator
            )
            return TimeZoneName.POZASZCZYT

        # Determine season based on month
        month = timestamp.month
        season_key = self._get_season_key(month, seasonal_data)

        if season_key is None:
            _LOGGER.warning(
                "Nie znaleziono sezonu dla miesiąca %d, operator %s",
                month,
                operator,
            )
            return TimeZoneName.POZASZCZYT

        season_data = seasonal_data[season_key]
        hour_str = timestamp.strftime("%H:%M")

        # Check szczyt_poranny
        if self._time_in_ranges(
            hour_str, season_data.get("szczyt_poranny", [])
        ):
            return TimeZoneName.SZCZYT_PORANNY

        # Check szczyt_popołudniowy
        if self._time_in_ranges(
            hour_str, season_data.get("szczyt_popołudniowy", [])
        ):
            return TimeZoneName.SZCZYT_POPOLUDNIOWY

        # Default: pozaszczyt
        return TimeZoneName.POZASZCZYT

    def _get_standard_zone(
        self, timestamp: datetime, tariff: TariffType, operator: OSDOperator
    ) -> TimeZoneName:
        """Określ strefę dla standardowych taryf wielostrefowych.

        Sprawdza godziny stref zdefiniowane w pliku OSD.
        """
        osd_data = self._loader.load_osd_zones(operator)
        tariff_key = tariff.value
        tariff_zones = osd_data.get("zones", {}).get(tariff_key, {})

        hour_str = timestamp.strftime("%H:%M")

        # Check each zone in order (skip special keys)
        for zone_name_str, hours_data in tariff_zones.items():
            if zone_name_str in ("seasonal", "weekend"):
                continue

            if hours_data == "full_day":
                # This shouldn't be reached for standard zones on weekdays
                continue

            if isinstance(hours_data, list):
                if self._time_in_ranges(hour_str, hours_data):
                    try:
                        return TimeZoneName(zone_name_str)
                    except ValueError:
                        _LOGGER.debug(
                            "Nieznana strefa '%s' dla %s/%s",
                            zone_name_str,
                            operator,
                            tariff,
                        )
                        continue

        # Fallback: for multi-zone tariffs, default to POZASZCZYT
        _LOGGER.debug(
            "Nie znaleziono strefy dla %s o %s (%s/%s), domyślnie pozaszczyt",
            hour_str,
            timestamp,
            tariff,
            operator,
        )
        return TimeZoneName.POZASZCZYT

    def _get_rates_for_zone(
        self,
        zone: TimeZoneName,
        rates: dict[TimeZoneName, TariffRates],
        tariff: TariffType,
    ) -> TariffRates:
        """Pobierz stawki dla danej strefy.

        Dla strefy WEEKEND w G12w, używa stawek POZASZCZYT (weekend
        jest traktowany jak pozaszczyt cenowo).
        """
        if zone in rates:
            return rates[zone]

        # G12w WEEKEND uses POZASZCZYT rates
        if zone == TimeZoneName.WEEKEND and TimeZoneName.POZASZCZYT in rates:
            return rates[TimeZoneName.POZASZCZYT]

        # G13 POZASZCZYT fallback for weekends
        if zone == TimeZoneName.POZASZCZYT and TimeZoneName.POZASZCZYT in rates:
            return rates[TimeZoneName.POZASZCZYT]

        # Fallback: use first available zone rates
        if rates:
            first_zone = next(iter(rates))
            _LOGGER.warning(
                "Brak stawek dla strefy %s (taryfa %s), używam stawek strefy %s",
                zone,
                tariff,
                first_zone,
            )
            return rates[first_zone]

        # This should never happen if rates are properly configured
        raise ValueError(
            f"Brak stawek taryfowych dla strefy {zone} (taryfa {tariff})"
        )

    @staticmethod
    def _is_weekend(timestamp: datetime) -> bool:
        """Sprawdź czy dany dzień to weekend (sobota=5, niedziela=6)."""
        return timestamp.weekday() >= 5

    @staticmethod
    def _get_season_key(
        month: int, seasonal_data: dict
    ) -> Optional[str]:
        """Określ klucz sezonu na podstawie miesiąca."""
        for season_key, season_info in seasonal_data.items():
            if isinstance(season_info, dict) and "months" in season_info:
                if month in season_info["months"]:
                    return season_key
        return None

    @staticmethod
    def _time_in_ranges(
        time_str: str, ranges: list[list[str]]
    ) -> bool:
        """Sprawdź czy czas mieści się w podanych zakresach.

        Args:
            time_str: Czas w formacie "HH:MM".
            ranges: Lista par ["HH:MM", "HH:MM"] definiujących zakresy.

        Returns:
            True jeśli czas mieści się w którymkolwiek zakresie.
        """
        for time_range in ranges:
            if len(time_range) != 2:
                continue
            start_str, end_str = time_range[0], time_range[1]
            if start_str <= time_str < end_str:
                return True
        return False
