"""Analizator i porównywarka taryf dla Polish Energy Optimizer (PEO).

Porównuje koszty energii dla różnych taryf na podstawie rzeczywistego
godzinowego profilu zużycia użytkownika z ostatnich 30 dni.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .enums import OSDOperator, TariffType, TimeZoneName
from .models import TariffComparison, TariffRanking, TariffRates
from .tariff_calculator import TariffCalculator
from .tariff_loader import TariffDefinitionLoader

_LOGGER = logging.getLogger(__name__)

# Tariffs available for comparison (residential G-tariffs)
_COMPARABLE_TARIFFS: list[TariffType] = [
    TariffType.G11,
    TariffType.G12,
    TariffType.G12W,
    TariffType.G12R,
    TariffType.G13,
]

# Minimum days of data required for valid analysis
_MIN_DATA_DAYS = 7

# Precision for cost calculations
_COST_PRECISION = Decimal("0.01")


class TariffAnalyzer:
    """Analizator i porównywarka taryf.

    Oblicza hipotetyczny koszt energii dla każdej dostępnej taryfy
    na podstawie rzeczywistego profilu zużycia użytkownika i rankinguje
    taryfy od najtańszej do najdroższej.
    """

    def __init__(
        self,
        calculator: TariffCalculator,
        loader: TariffDefinitionLoader,
    ) -> None:
        """Inicjalizacja analizatora taryf.

        Args:
            calculator: Instancja TariffCalculator do obliczania kosztów.
            loader: Instancja TariffDefinitionLoader do ładowania stawek.
        """
        self._calculator = calculator
        self._loader = loader

    def analyze_tariffs(
        self,
        consumption_profile: dict[datetime, float],
        current_tariff: TariffType,
        operator: OSDOperator,
    ) -> TariffComparison:
        """Porównaj koszty dla wszystkich taryf G na podstawie profilu zużycia.

        Oblicza hipotetyczny koszt dla każdej taryfy (G11, G12, G12w, G12r, G13)
        na podstawie rzeczywistego godzinowego zużycia z ostatnich 30 dni.

        Args:
            consumption_profile: Słownik datetime -> zużycie kWh na godzinę.
            current_tariff: Aktualna taryfa użytkownika.
            operator: Operator OSD użytkownika.

        Returns:
            TariffComparison z rankingiem, rekomendacją i oszczędnościami.
        """
        # Determine number of unique days in the profile
        unique_days = len({dt.date() for dt in consumption_profile.keys()})
        is_sufficient = unique_days >= _MIN_DATA_DAYS

        _LOGGER.debug(
            "Analizator taryf: profil zużycia zawiera %d godzin (%d dni)",
            len(consumption_profile),
            unique_days,
        )

        # Calculate hypothetical cost for each tariff
        tariff_costs: dict[TariffType, Decimal] = {}
        for tariff in _COMPARABLE_TARIFFS:
            rates = self._load_all_zone_rates(operator, tariff)
            if rates is None:
                _LOGGER.warning(
                    "Analizator taryf: brak stawek dla %s/%s, pomijam",
                    operator,
                    tariff,
                )
                continue

            cost = self.calculate_hypothetical_cost(
                consumption_profile, tariff, operator, rates
            )
            tariff_costs[tariff] = cost

        if not tariff_costs:
            _LOGGER.error("Analizator taryf: nie udało się obliczyć kosztów dla żadnej taryfy")
            return TariffComparison(
                current_tariff=current_tariff,
                rankings=[],
                recommended=current_tariff,
                monthly_savings_pln=Decimal("0.00"),
                data_days=unique_days,
                is_sufficient_data=False,
            )

        # Get current tariff cost for comparison
        current_cost = tariff_costs.get(current_tariff, Decimal("0"))

        # Scale costs to monthly estimate (30 days)
        # If we have N days of data, scale to 30 days
        scale_factor = Decimal("30") / Decimal(str(max(unique_days, 1)))

        # Build rankings sorted by cost (cheapest first)
        rankings: list[TariffRanking] = []
        for tariff, total_cost in sorted(tariff_costs.items(), key=lambda x: x[1]):
            monthly_cost = (total_cost * scale_factor).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )
            current_monthly = (current_cost * scale_factor).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )
            difference = (monthly_cost - current_monthly).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )
            if current_monthly > 0:
                difference_percent = float(
                    (difference / current_monthly * Decimal("100")).quantize(
                        Decimal("0.1"), rounding=ROUND_HALF_UP
                    )
                )
            else:
                difference_percent = 0.0

            rankings.append(
                TariffRanking(
                    tariff=tariff,
                    monthly_cost_pln=monthly_cost,
                    difference_pln=difference,
                    difference_percent=difference_percent,
                )
            )

        # Recommended tariff is the cheapest one
        recommended = rankings[0].tariff if rankings else current_tariff

        # Monthly savings = current cost - cheapest cost (positive = savings)
        if rankings:
            current_monthly = (current_cost * scale_factor).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )
            cheapest_monthly = rankings[0].monthly_cost_pln
            monthly_savings = (current_monthly - cheapest_monthly).quantize(
                _COST_PRECISION, rounding=ROUND_HALF_UP
            )
        else:
            monthly_savings = Decimal("0.00")

        # If insufficient data, don't recommend changes
        if not is_sufficient:
            _LOGGER.info(
                "Analizator taryf: niewystarczające dane (%d dni < %d wymaganych)",
                unique_days,
                _MIN_DATA_DAYS,
            )
            recommended = current_tariff
            monthly_savings = Decimal("0.00")

        return TariffComparison(
            current_tariff=current_tariff,
            rankings=rankings,
            recommended=recommended,
            monthly_savings_pln=monthly_savings,
            data_days=unique_days,
            is_sufficient_data=is_sufficient,
        )

    def calculate_hypothetical_cost(
        self,
        hourly_consumption: dict[datetime, float],
        tariff: TariffType,
        operator: OSDOperator,
        rates: dict[TimeZoneName, TariffRates],
    ) -> Decimal:
        """Oblicz hipotetyczny koszt dla danej taryfy.

        Dla każdej godziny w profilu zużycia oblicza koszt jako:
        zużycie_kWh × koszt_kWh (suma 6 składników).

        Args:
            hourly_consumption: Słownik datetime -> zużycie kWh na godzinę.
            tariff: Typ taryfy do obliczenia.
            operator: Operator OSD.
            rates: Słownik stawek per strefa czasowa.

        Returns:
            Łączny koszt w PLN (2 miejsca po przecinku).
        """
        total_cost = Decimal("0")

        for timestamp, consumption_kwh in hourly_consumption.items():
            if consumption_kwh <= 0:
                continue

            # Calculate cost per kWh for this hour using TariffCalculator
            cost_per_kwh = self._calculator.calculate_cost(
                timestamp, tariff, operator, rates
            )

            # Hourly cost = consumption × cost_per_kwh
            hourly_cost = Decimal(str(consumption_kwh)) * cost_per_kwh
            total_cost += hourly_cost

        return total_cost.quantize(_COST_PRECISION, rounding=ROUND_HALF_UP)

    def _load_all_zone_rates(
        self,
        operator: OSDOperator,
        tariff: TariffType,
    ) -> dict[TimeZoneName, TariffRates] | None:
        """Załaduj stawki dla wszystkich stref danej taryfy/operatora.

        Args:
            operator: Operator OSD.
            tariff: Typ taryfy.

        Returns:
            Słownik TimeZoneName -> TariffRates lub None w przypadku błędu.
        """
        try:
            rates_data = self._loader._load_rates_file()
        except Exception as exc:
            _LOGGER.error(
                "Analizator taryf: błąd ładowania pliku stawek: %s", exc
            )
            return None

        operators = rates_data.get("operators", {})
        operator_data = operators.get(operator.value)
        if operator_data is None:
            return None

        tariff_data = operator_data.get(tariff.value)
        if tariff_data is None:
            return None

        result: dict[TimeZoneName, TariffRates] = {}
        for zone_name_str, zone_rates in tariff_data.items():
            try:
                zone_name = TimeZoneName(zone_name_str)
            except ValueError:
                _LOGGER.debug(
                    "Analizator taryf: pomijam nieznaną strefę '%s'",
                    zone_name_str,
                )
                continue

            try:
                result[zone_name] = TariffRates(
                    energy_price=Decimal(zone_rates["energy_price"]),
                    distribution_variable=Decimal(zone_rates["distribution_variable"]),
                    transition_fee=Decimal(zone_rates["transition_fee"]),
                    oze_fee=Decimal(zone_rates["oze_fee"]),
                    capacity_fee=Decimal(zone_rates["capacity_fee"]),
                    cogeneration_fee=Decimal(zone_rates["cogeneration_fee"]),
                )
            except (KeyError, ValueError) as exc:
                _LOGGER.warning(
                    "Analizator taryf: błąd parsowania stawek strefy %s: %s",
                    zone_name_str,
                    exc,
                )
                continue

        return result if result else None
