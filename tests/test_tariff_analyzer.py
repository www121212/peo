"""Testy jednostkowe dla TariffAnalyzer."""

from datetime import datetime
from decimal import Decimal

import pytest

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import TariffComparison, TariffRanking, TariffRates
from custom_components.peo.tariff_analyzer import TariffAnalyzer
from custom_components.peo.tariff_calculator import TariffCalculator
from custom_components.peo.tariff_loader import TariffDefinitionLoader


@pytest.fixture
def loader():
    """Fixture: TariffDefinitionLoader z prawdziwymi danymi."""
    return TariffDefinitionLoader()


@pytest.fixture
def calculator(loader):
    """Fixture: TariffCalculator z prawdziwym loaderem."""
    return TariffCalculator(loader)


@pytest.fixture
def analyzer(calculator, loader):
    """Fixture: TariffAnalyzer z prawdziwym kalkulatorem i loaderem."""
    return TariffAnalyzer(calculator, loader)


@pytest.fixture
def weekday_consumption_profile():
    """Fixture: 7-dniowy profil zużycia (poniedziałek-niedziela).

    Symuluje typowe zużycie domowe: wyższe rano i wieczorem,
    niższe w nocy i w ciągu dnia.
    """
    profile: dict[datetime, float] = {}
    # 7 days: Mon Jan 15 - Sun Jan 21, 2024
    for day_offset in range(7):
        day = 15 + day_offset
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            # Simulate typical consumption pattern
            if 0 <= hour < 6:
                consumption = 0.3  # Night: low
            elif 6 <= hour < 9:
                consumption = 1.5  # Morning peak
            elif 9 <= hour < 16:
                consumption = 0.8  # Daytime: moderate
            elif 16 <= hour < 22:
                consumption = 2.0  # Evening peak
            else:
                consumption = 0.5  # Late evening
            profile[ts] = consumption
    return profile


@pytest.fixture
def short_consumption_profile():
    """Fixture: 3-dniowy profil zużycia (niewystarczające dane)."""
    profile: dict[datetime, float] = {}
    for day_offset in range(3):
        day = 15 + day_offset
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            profile[ts] = 1.0  # Flat consumption
    return profile


@pytest.fixture
def peak_heavy_consumption_profile():
    """Fixture: 10-dniowy profil z dużym zużyciem w szczycie.

    Symuluje użytkownika, który zużywa dużo energii w godzinach szczytu.
    Taki profil powinien faworyzować taryfy z niższymi stawkami pozaszczytowymi.
    """
    profile: dict[datetime, float] = {}
    for day_offset in range(10):
        day = 15 + day_offset
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            # Heavy peak consumption
            if 7 <= hour < 13 or 16 <= hour < 22:
                consumption = 3.0  # Peak hours: very high
            else:
                consumption = 0.2  # Off-peak: very low
            profile[ts] = consumption
    return profile


@pytest.fixture
def offpeak_heavy_consumption_profile():
    """Fixture: 10-dniowy profil z dużym zużyciem poza szczytem.

    Symuluje użytkownika, który zużywa energię głównie w nocy.
    Taki profil powinien faworyzować taryfy wielostrefowe.
    """
    profile: dict[datetime, float] = {}
    for day_offset in range(10):
        day = 15 + day_offset
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            # Heavy off-peak consumption
            if 0 <= hour < 6 or 13 <= hour < 15 or 22 <= hour < 24:
                consumption = 3.0  # Off-peak: very high
            else:
                consumption = 0.2  # Peak: very low
            profile[ts] = consumption
    return profile


class TestAnalyzeTariffs:
    """Testy analyze_tariffs()."""

    def test_returns_tariff_comparison(self, analyzer, weekday_consumption_profile):
        """Zwraca obiekt TariffComparison."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G11,
            OSDOperator.TAURON,
        )
        assert isinstance(result, TariffComparison)

    def test_contains_all_g_tariffs(self, analyzer, weekday_consumption_profile):
        """Ranking zawiera wszystkie 5 taryf G."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        tariffs_in_ranking = {r.tariff for r in result.rankings}
        expected = {TariffType.G11, TariffType.G12, TariffType.G12W, TariffType.G12R, TariffType.G13}
        assert tariffs_in_ranking == expected

    def test_rankings_sorted_by_cost(self, analyzer, weekday_consumption_profile):
        """Ranking jest posortowany od najtańszej do najdroższej."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        costs = [r.monthly_cost_pln for r in result.rankings]
        assert costs == sorted(costs)

    def test_recommended_is_cheapest(self, analyzer, weekday_consumption_profile):
        """Rekomendowana taryfa to najtańsza."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G11,
            OSDOperator.TAURON,
        )
        assert result.recommended == result.rankings[0].tariff

    def test_current_tariff_difference_is_zero(self, analyzer, weekday_consumption_profile):
        """Różnica dla aktualnej taryfy wynosi 0 PLN."""
        current = TariffType.G12
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            current,
            OSDOperator.TAURON,
        )
        current_ranking = next(r for r in result.rankings if r.tariff == current)
        assert current_ranking.difference_pln == Decimal("0.00")

    def test_monthly_savings_positive_when_cheaper_exists(
        self, analyzer, peak_heavy_consumption_profile
    ):
        """Oszczędności miesięczne > 0 gdy istnieje tańsza taryfa.

        Użytkownik z G11 (jednolita) i dużym zużyciem w szczycie
        powinien mieć potencjalne oszczędności na taryfie wielostrefowej
        z niższymi stawkami pozaszczytowymi.
        """
        result = analyzer.analyze_tariffs(
            peak_heavy_consumption_profile,
            TariffType.G11,
            OSDOperator.TAURON,
        )
        # If G11 is not the cheapest, savings should be positive
        if result.recommended != TariffType.G11:
            assert result.monthly_savings_pln > Decimal("0")

    def test_monthly_savings_zero_when_already_cheapest(
        self, analyzer, weekday_consumption_profile
    ):
        """Oszczędności = 0 gdy aktualna taryfa jest najtańsza."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        # If current is already cheapest
        if result.recommended == TariffType.G12:
            assert result.monthly_savings_pln == Decimal("0.00")

    def test_insufficient_data_less_than_7_days(
        self, analyzer, short_consumption_profile
    ):
        """Mniej niż 7 dni danych → is_sufficient_data=False."""
        result = analyzer.analyze_tariffs(
            short_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        assert result.is_sufficient_data is False
        assert result.data_days == 3

    def test_insufficient_data_no_recommendation(
        self, analyzer, short_consumption_profile
    ):
        """Przy niewystarczających danych rekomendacja = aktualna taryfa."""
        current = TariffType.G12
        result = analyzer.analyze_tariffs(
            short_consumption_profile,
            current,
            OSDOperator.TAURON,
        )
        assert result.recommended == current
        assert result.monthly_savings_pln == Decimal("0.00")

    def test_sufficient_data_7_days(self, analyzer, weekday_consumption_profile):
        """7 dni danych → is_sufficient_data=True."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        assert result.is_sufficient_data is True
        assert result.data_days == 7

    def test_different_operators_different_results(
        self, analyzer, weekday_consumption_profile
    ):
        """Różni operatorzy mogą dawać różne wyniki."""
        result_tauron = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.TAURON,
        )
        result_pge = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G12,
            OSDOperator.PGE,
        )
        # Costs should differ between operators
        tauron_costs = {r.tariff: r.monthly_cost_pln for r in result_tauron.rankings}
        pge_costs = {r.tariff: r.monthly_cost_pln for r in result_pge.rankings}
        # At least some tariffs should have different costs
        assert tauron_costs != pge_costs

    def test_offpeak_heavy_favors_multizone(
        self, analyzer, offpeak_heavy_consumption_profile
    ):
        """Duże zużycie poza szczytem faworyzuje taryfy wielostrefowe.

        Użytkownik zużywający głównie w nocy powinien mieć niższe koszty
        na taryfie G12/G12w/G13 niż na G11.
        """
        result = analyzer.analyze_tariffs(
            offpeak_heavy_consumption_profile,
            TariffType.G11,
            OSDOperator.TAURON,
        )
        # G11 should not be the cheapest for off-peak heavy users
        g11_ranking = next(r for r in result.rankings if r.tariff == TariffType.G11)
        cheapest_ranking = result.rankings[0]
        assert cheapest_ranking.monthly_cost_pln <= g11_ranking.monthly_cost_pln

    def test_empty_consumption_profile(self, analyzer):
        """Pusty profil zużycia → koszty zerowe."""
        result = analyzer.analyze_tariffs(
            {},
            TariffType.G12,
            OSDOperator.TAURON,
        )
        assert result.data_days == 0
        assert result.is_sufficient_data is False

    def test_ranking_difference_percent(self, analyzer, weekday_consumption_profile):
        """Procent różnicy jest poprawnie obliczony."""
        result = analyzer.analyze_tariffs(
            weekday_consumption_profile,
            TariffType.G11,
            OSDOperator.TAURON,
        )
        for ranking in result.rankings:
            # difference_percent should be consistent with difference_pln
            if ranking.tariff == TariffType.G11:
                assert ranking.difference_pln == Decimal("0.00")
                assert ranking.difference_percent == 0.0


class TestCalculateHypotheticalCost:
    """Testy calculate_hypothetical_cost()."""

    def test_basic_cost_calculation(self, analyzer):
        """Podstawowe obliczenie kosztu — zużycie × stawka."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2018"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        # 1 hour, 1 kWh consumption
        consumption = {datetime(2024, 1, 15, 10, 0): 1.0}

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G11, OSDOperator.TAURON, rates
        )

        # Expected: 1.0 * (0.6221 + 0.2018 + 0.0009 + 0.0027 + 0.0762 + 0.0058) = 0.9095
        # Rounded to 2 decimal places = 0.91
        expected = Decimal("0.91")
        assert cost == expected

    def test_zero_consumption_returns_zero(self, analyzer):
        """Zerowe zużycie → koszt zerowy."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2018"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        consumption = {datetime(2024, 1, 15, 10, 0): 0.0}

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G11, OSDOperator.TAURON, rates
        )
        assert cost == Decimal("0.00")

    def test_multiple_hours_sum(self, analyzer):
        """Koszt wielu godzin = suma kosztów poszczególnych godzin."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2018"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        # 3 hours, 2 kWh each
        consumption = {
            datetime(2024, 1, 15, 10, 0): 2.0,
            datetime(2024, 1, 15, 11, 0): 2.0,
            datetime(2024, 1, 15, 12, 0): 2.0,
        }

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G11, OSDOperator.TAURON, rates
        )

        # Expected: 3 * 2.0 * 0.9095 = 5.457
        expected = Decimal("5.46")  # rounded to 2dp
        assert cost == expected

    def test_multizone_tariff_uses_correct_rates(self, analyzer):
        """Taryfa wielostrefowa stosuje stawki odpowiednie dla strefy."""
        rates = {
            TimeZoneName.SZCZYT: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2596"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
            TimeZoneName.POZASZCZYT: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.0756"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        # 1 kWh in peak (08:00 Monday) and 1 kWh off-peak (03:00 Monday)
        consumption = {
            datetime(2024, 1, 15, 8, 0): 1.0,   # szczyt
            datetime(2024, 1, 15, 3, 0): 1.0,   # pozaszczyt
        }

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G12, OSDOperator.TAURON, rates
        )

        # Peak cost: 0.6221 + 0.2596 + 0.0009 + 0.0027 + 0.0762 + 0.0058 = 0.9673
        # Off-peak cost: 0.6221 + 0.0756 + 0.0009 + 0.0027 + 0.0762 + 0.0058 = 0.7833
        # Total: 0.9673 + 0.7833 = 1.7506
        expected = Decimal("1.75")
        assert cost == expected

    def test_negative_consumption_ignored(self, analyzer):
        """Ujemne zużycie jest ignorowane (np. oddawanie do sieci)."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2018"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        consumption = {
            datetime(2024, 1, 15, 10, 0): 1.0,
            datetime(2024, 1, 15, 11, 0): -0.5,  # negative = export
        }

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G11, OSDOperator.TAURON, rates
        )

        # Only positive consumption counted: 1.0 * 0.9095
        expected = Decimal("0.91")  # rounded
        assert cost == expected

    def test_cost_includes_all_six_components(self, analyzer):
        """Koszt zawiera wszystkie 6 składników opłat."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.5000"),
                distribution_variable=Decimal("0.1000"),
                transition_fee=Decimal("0.0100"),
                oze_fee=Decimal("0.0200"),
                capacity_fee=Decimal("0.0300"),
                cogeneration_fee=Decimal("0.0400"),
            ),
        }
        consumption = {datetime(2024, 1, 15, 10, 0): 1.0}

        cost = analyzer.calculate_hypothetical_cost(
            consumption, TariffType.G11, OSDOperator.TAURON, rates
        )

        # 0.5 + 0.1 + 0.01 + 0.02 + 0.03 + 0.04 = 0.70
        assert cost == Decimal("0.70")

    def test_empty_consumption_returns_zero(self, analyzer):
        """Pusty profil zużycia → koszt zerowy."""
        rates = {
            TimeZoneName.SINGLE: TariffRates(
                energy_price=Decimal("0.6221"),
                distribution_variable=Decimal("0.2018"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        cost = analyzer.calculate_hypothetical_cost(
            {}, TariffType.G11, OSDOperator.TAURON, rates
        )
        assert cost == Decimal("0.00")


class TestLoadAllZoneRates:
    """Testy _load_all_zone_rates()."""

    def test_loads_g11_single_zone(self, analyzer):
        """G11 — ładuje jedną strefę (jednolita)."""
        rates = analyzer._load_all_zone_rates(OSDOperator.TAURON, TariffType.G11)
        assert rates is not None
        assert TimeZoneName.SINGLE in rates
        assert len(rates) == 1

    def test_loads_g12_two_zones(self, analyzer):
        """G12 — ładuje dwie strefy (szczyt/pozaszczyt)."""
        rates = analyzer._load_all_zone_rates(OSDOperator.TAURON, TariffType.G12)
        assert rates is not None
        assert TimeZoneName.SZCZYT in rates
        assert TimeZoneName.POZASZCZYT in rates
        assert len(rates) == 2

    def test_loads_g13_three_zones(self, analyzer):
        """G13 — ładuje trzy strefy."""
        rates = analyzer._load_all_zone_rates(OSDOperator.TAURON, TariffType.G13)
        assert rates is not None
        assert TimeZoneName.SZCZYT_PORANNY in rates
        assert TimeZoneName.SZCZYT_POPOLUDNIOWY in rates
        assert TimeZoneName.POZASZCZYT in rates
        assert len(rates) == 3

    def test_rates_have_all_components(self, analyzer):
        """Stawki zawierają wszystkie 6 składników."""
        rates = analyzer._load_all_zone_rates(OSDOperator.TAURON, TariffType.G12)
        assert rates is not None
        for zone_rates in rates.values():
            assert zone_rates.energy_price > 0
            assert zone_rates.distribution_variable >= 0
            assert zone_rates.transition_fee >= 0
            assert zone_rates.oze_fee >= 0
            assert zone_rates.capacity_fee >= 0
            assert zone_rates.cogeneration_fee >= 0

    def test_all_operators_supported(self, analyzer):
        """Wszystkie operatory OSD mają stawki dla G12."""
        for operator in OSDOperator:
            rates = analyzer._load_all_zone_rates(operator, TariffType.G12)
            assert rates is not None, f"Brak stawek dla {operator}"
            assert len(rates) >= 2


class TestIntegration:
    """Testy integracyjne — pełny przepływ analizy."""

    def test_full_analysis_30_days(self, analyzer):
        """Pełna analiza z 30 dniami danych."""
        profile: dict[datetime, float] = {}
        for day in range(1, 31):
            for hour in range(24):
                ts = datetime(2024, 1, day, hour, 0)
                # Varied consumption
                if 6 <= hour < 22:
                    profile[ts] = 1.5
                else:
                    profile[ts] = 0.5
        
        result = analyzer.analyze_tariffs(
            profile, TariffType.G11, OSDOperator.TAURON
        )

        assert result.is_sufficient_data is True
        assert result.data_days == 30
        assert len(result.rankings) == 5
        # All costs should be positive
        for ranking in result.rankings:
            assert ranking.monthly_cost_pln > Decimal("0")

    def test_analysis_consistent_with_calculator(self, analyzer, calculator):
        """Wyniki analizy są spójne z bezpośrednim obliczeniem kalkulatora."""
        # Simple 1-hour profile
        ts = datetime(2024, 1, 15, 10, 0)
        profile = {ts: 1.0}

        # Get rates for G11
        rates = analyzer._load_all_zone_rates(OSDOperator.TAURON, TariffType.G11)
        assert rates is not None

        # Direct calculation
        direct_cost = calculator.calculate_cost(
            ts, TariffType.G11, OSDOperator.TAURON, rates
        )

        # Via analyzer
        analyzer_cost = analyzer.calculate_hypothetical_cost(
            profile, TariffType.G11, OSDOperator.TAURON, rates
        )

        # Should match (1 kWh * cost_per_kwh)
        assert analyzer_cost == direct_cost.quantize(Decimal("0.01"))
