"""Testy jednostkowe dla TariffCalculator."""

from datetime import datetime, date
from decimal import Decimal

import pytest

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import HourlyCost, HourlyPrice, TariffRates
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
def g12_rates():
    """Fixture: Stawki G12 (szczyt/pozaszczyt) dla testów."""
    return {
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


@pytest.fixture
def g12w_rates():
    """Fixture: Stawki G12w (szczyt/pozaszczyt/weekend) dla testów."""
    return {
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


@pytest.fixture
def g13_rates():
    """Fixture: Stawki G13 (szczyt_poranny/szczyt_popołudniowy/pozaszczyt)."""
    return {
        TimeZoneName.SZCZYT_PORANNY: TariffRates(
            energy_price=Decimal("0.6221"),
            distribution_variable=Decimal("0.2876"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        ),
        TimeZoneName.SZCZYT_POPOLUDNIOWY: TariffRates(
            energy_price=Decimal("0.6221"),
            distribution_variable=Decimal("0.2876"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        ),
        TimeZoneName.POZASZCZYT: TariffRates(
            energy_price=Decimal("0.6221"),
            distribution_variable=Decimal("0.0654"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        ),
    }


@pytest.fixture
def g11_rates():
    """Fixture: Stawki G11 (jednolita)."""
    return {
        TimeZoneName.SINGLE: TariffRates(
            energy_price=Decimal("0.6221"),
            distribution_variable=Decimal("0.2018"),
            transition_fee=Decimal("0.0009"),
            oze_fee=Decimal("0.0027"),
            capacity_fee=Decimal("0.0762"),
            cogeneration_fee=Decimal("0.0058"),
        ),
    }


class TestGetZoneForTime:
    """Testy get_zone_for_time()."""

    def test_g11_always_single(self, calculator):
        """G11 — zawsze strefa jednolita, niezależnie od godziny."""
        # Weekday morning
        ts = datetime(2024, 1, 15, 8, 0)  # Monday
        assert calculator.get_zone_for_time(ts, TariffType.G11, OSDOperator.TAURON) == TimeZoneName.SINGLE

        # Weekend night
        ts = datetime(2024, 1, 13, 2, 0)  # Saturday
        assert calculator.get_zone_for_time(ts, TariffType.G11, OSDOperator.TAURON) == TimeZoneName.SINGLE

    def test_c11_always_single(self, calculator):
        """C11 — zawsze strefa jednolita."""
        ts = datetime(2024, 1, 15, 12, 0)
        assert calculator.get_zone_for_time(ts, TariffType.C11, OSDOperator.PGE) == TimeZoneName.SINGLE

    def test_g12_szczyt_tauron(self, calculator):
        """G12 Tauron — szczyt 06:00-13:00 i 15:00-22:00."""
        # 08:00 Monday → szczyt
        ts = datetime(2024, 1, 15, 8, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.SZCZYT

        # 16:00 Monday → szczyt
        ts = datetime(2024, 1, 15, 16, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.SZCZYT

    def test_g12_pozaszczyt_tauron(self, calculator):
        """G12 Tauron — pozaszczyt 00:00-06:00, 13:00-15:00, 22:00-24:00."""
        # 03:00 Monday → pozaszczyt
        ts = datetime(2024, 1, 15, 3, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

        # 14:00 Monday → pozaszczyt
        ts = datetime(2024, 1, 15, 14, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

        # 23:00 Monday → pozaszczyt
        ts = datetime(2024, 1, 15, 23, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_g12w_weekend_returns_weekend(self, calculator):
        """G12w — weekend (sobota/niedziela) → strefa WEEKEND."""
        # Saturday 10:00
        ts = datetime(2024, 1, 13, 10, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12W, OSDOperator.TAURON) == TimeZoneName.WEEKEND

        # Sunday 22:00
        ts = datetime(2024, 1, 14, 22, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12W, OSDOperator.TAURON) == TimeZoneName.WEEKEND

    def test_g12w_weekday_uses_standard_zones(self, calculator):
        """G12w — dzień roboczy → standardowe strefy szczyt/pozaszczyt."""
        # Monday 08:00 → szczyt
        ts = datetime(2024, 1, 15, 8, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12W, OSDOperator.TAURON) == TimeZoneName.SZCZYT

        # Monday 03:00 → pozaszczyt
        ts = datetime(2024, 1, 15, 3, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12W, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_g13_weekend_returns_pozaszczyt(self, calculator):
        """G13 — weekend → POZASZCZYT."""
        # Saturday 10:00 (would be szczyt_poranny on weekday)
        ts = datetime(2024, 1, 13, 10, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_g13_winter_szczyt_poranny_tauron(self, calculator):
        """G13 Tauron zima — szczyt poranny 07:00-13:00."""
        # January (winter) Monday 09:00
        ts = datetime(2024, 1, 15, 9, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.SZCZYT_PORANNY

    def test_g13_winter_szczyt_popoludniowy_tauron(self, calculator):
        """G13 Tauron zima — szczyt popołudniowy 16:00-21:00."""
        # January (winter) Monday 18:00
        ts = datetime(2024, 1, 15, 18, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.SZCZYT_POPOLUDNIOWY

    def test_g13_winter_pozaszczyt_tauron(self, calculator):
        """G13 Tauron zima — pozaszczyt (reszta doby)."""
        # January (winter) Monday 03:00
        ts = datetime(2024, 1, 15, 3, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

        # January (winter) Monday 14:00
        ts = datetime(2024, 1, 15, 14, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_g13_summer_szczyt_popoludniowy_tauron(self, calculator):
        """G13 Tauron lato — szczyt popołudniowy 19:00-22:00."""
        # July (summer) Monday 20:00
        ts = datetime(2024, 7, 15, 20, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.SZCZYT_POPOLUDNIOWY

    def test_g13_summer_pozaszczyt_tauron(self, calculator):
        """G13 Tauron lato — pozaszczyt 13:00-19:00."""
        # July (summer) Monday 15:00
        ts = datetime(2024, 7, 15, 15, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G13, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_g12r_zones_tauron(self, calculator):
        """G12r Tauron — szczyt 07:00-13:00, 16:00-21:00."""
        # 10:00 → szczyt
        ts = datetime(2024, 1, 15, 10, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12R, OSDOperator.TAURON) == TimeZoneName.SZCZYT

        # 14:00 → pozaszczyt
        ts = datetime(2024, 1, 15, 14, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12R, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_zone_boundary_start_inclusive(self, calculator):
        """Granica strefy — początek jest inkluzywny."""
        # G12 Tauron: szczyt starts at 06:00
        ts = datetime(2024, 1, 15, 6, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.SZCZYT

    def test_zone_boundary_end_exclusive(self, calculator):
        """Granica strefy — koniec jest ekskluzywny."""
        # G12 Tauron: szczyt ends at 13:00 (exclusive), so 13:00 is pozaszczyt
        ts = datetime(2024, 1, 15, 13, 0)
        assert calculator.get_zone_for_time(ts, TariffType.G12, OSDOperator.TAURON) == TimeZoneName.POZASZCZYT

    def test_different_operators_different_zones(self, calculator):
        """Różni operatorzy mogą mieć różne godziny stref."""
        # G12r: Tauron szczyt 07:00-13:00, PGE szczyt 07:00-13:00
        ts = datetime(2024, 1, 15, 10, 0)
        tauron_zone = calculator.get_zone_for_time(ts, TariffType.G12R, OSDOperator.TAURON)
        pge_zone = calculator.get_zone_for_time(ts, TariffType.G12R, OSDOperator.PGE)
        # Both should be szczyt at 10:00
        assert tauron_zone == TimeZoneName.SZCZYT
        assert pge_zone == TimeZoneName.SZCZYT


class TestCalculateCost:
    """Testy calculate_cost()."""

    def test_g11_cost_sum_of_components(self, calculator, g11_rates):
        """G11 — koszt = suma 6 składników."""
        ts = datetime(2024, 1, 15, 10, 0)
        cost = calculator.calculate_cost(
            ts, TariffType.G11, OSDOperator.TAURON, g11_rates
        )

        expected = (
            Decimal("0.6221")
            + Decimal("0.2018")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_g12_szczyt_cost(self, calculator, g12_rates):
        """G12 szczyt — koszt z wyższą opłatą dystrybucyjną."""
        ts = datetime(2024, 1, 15, 8, 0)  # Monday 08:00 → szczyt
        cost = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        expected = (
            Decimal("0.6221")
            + Decimal("0.2596")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_g12_pozaszczyt_cost(self, calculator, g12_rates):
        """G12 pozaszczyt — koszt z niższą opłatą dystrybucyjną."""
        ts = datetime(2024, 1, 15, 3, 0)  # Monday 03:00 → pozaszczyt
        cost = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        expected = (
            Decimal("0.6221")
            + Decimal("0.0756")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_cost_has_4_decimal_places(self, calculator, g12_rates):
        """Koszt powinien mieć dokładnie 4 miejsca po przecinku."""
        ts = datetime(2024, 1, 15, 8, 0)
        cost = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        # Check that the result has exactly 4 decimal places
        assert cost == cost.quantize(Decimal("0.0001"))

    def test_rce_price_replaces_energy_price(self, calculator, g12_rates):
        """Gdy podano rce_price, zastępuje energy_price w obliczeniu."""
        ts = datetime(2024, 1, 15, 8, 0)  # szczyt
        rce_price = Decimal("0.3500")

        cost = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates, rce_price=rce_price
        )

        expected = (
            Decimal("0.3500")  # RCE instead of 0.6221
            + Decimal("0.2596")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_rce_price_none_uses_energy_price(self, calculator, g12_rates):
        """Gdy rce_price=None, używa energy_price ze stawek."""
        ts = datetime(2024, 1, 15, 8, 0)
        cost_without_rce = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates, rce_price=None
        )
        cost_default = calculator.calculate_cost(
            ts, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        assert cost_without_rce == cost_default

    def test_g12w_weekend_uses_pozaszczyt_rates(self, calculator, g12w_rates):
        """G12w weekend — używa stawek pozaszczyt."""
        ts = datetime(2024, 1, 13, 10, 0)  # Saturday
        cost = calculator.calculate_cost(
            ts, TariffType.G12W, OSDOperator.TAURON, g12w_rates
        )

        # Weekend should use pozaszczyt rates
        expected = (
            Decimal("0.6221")
            + Decimal("0.0756")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_g13_pozaszczyt_weekend(self, calculator, g13_rates):
        """G13 weekend — używa stawek pozaszczyt."""
        ts = datetime(2024, 1, 13, 10, 0)  # Saturday
        cost = calculator.calculate_cost(
            ts, TariffType.G13, OSDOperator.TAURON, g13_rates
        )

        expected = (
            Decimal("0.6221")
            + Decimal("0.0654")
            + Decimal("0.0009")
            + Decimal("0.0027")
            + Decimal("0.0762")
            + Decimal("0.0058")
        )
        assert cost == expected.quantize(Decimal("0.0001"))

    def test_szczyt_more_expensive_than_pozaszczyt(self, calculator, g12_rates):
        """Szczyt powinien być droższy niż pozaszczyt."""
        ts_szczyt = datetime(2024, 1, 15, 8, 0)
        ts_pozaszczyt = datetime(2024, 1, 15, 3, 0)

        cost_szczyt = calculator.calculate_cost(
            ts_szczyt, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        cost_pozaszczyt = calculator.calculate_cost(
            ts_pozaszczyt, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        assert cost_szczyt > cost_pozaszczyt


class TestGetHourlyCosts:
    """Testy get_hourly_costs()."""

    def test_returns_24_hours_by_default(self, calculator, g12_rates):
        """Domyślnie zwraca 24 godziny."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        assert len(result) == 24

    def test_returns_custom_hours(self, calculator, g12_rates):
        """Zwraca podaną liczbę godzin."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates, hours=12
        )

        assert len(result) == 12

    def test_hourly_cost_structure(self, calculator, g12_rates):
        """Każdy HourlyCost ma poprawną strukturę."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        for hourly_cost in result:
            assert isinstance(hourly_cost, HourlyCost)
            assert 0 <= hourly_cost.hour <= 23
            assert isinstance(hourly_cost.timestamp, datetime)
            assert isinstance(hourly_cost.cost_pln_kwh, Decimal)
            assert isinstance(hourly_cost.zone, TimeZoneName)
            assert isinstance(hourly_cost.components, TariffRates)

    def test_timestamps_are_sequential(self, calculator, g12_rates):
        """Timestamps powinny być sekwencyjne co godzinę."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        for i, hourly_cost in enumerate(result):
            expected_ts = start + __import__("datetime").timedelta(hours=i)
            assert hourly_cost.timestamp == expected_ts

    def test_zones_change_during_day(self, calculator, g12_rates):
        """Strefy powinny się zmieniać w ciągu dnia dla G12."""
        start = datetime(2024, 1, 15, 0, 0)  # Monday
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        zones = {hc.zone for hc in result}
        assert TimeZoneName.SZCZYT in zones
        assert TimeZoneName.POZASZCZYT in zones

    def test_g11_all_same_zone(self, calculator, g11_rates):
        """G11 — wszystkie godziny w tej samej strefie."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G11, OSDOperator.TAURON, g11_rates
        )

        zones = {hc.zone for hc in result}
        assert zones == {TimeZoneName.SINGLE}

    def test_rce_prices_applied(self, calculator, g12_rates):
        """Ceny RCE powinny być zastosowane gdy podane."""
        start = datetime(2024, 1, 15, 0, 0)
        rce_prices = [
            HourlyPrice(
                hour=h,
                price_pln_mwh=Decimal("350.00"),
                price_pln_kwh=Decimal("0.3500"),
                date=date(2024, 1, 15),
            )
            for h in range(24)
        ]

        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates,
            rce_prices=rce_prices,
        )

        # All costs should use RCE price (0.35) instead of energy_price (0.6221)
        for hc in result:
            # Cost should be lower than with standard energy price
            standard_cost = calculator.calculate_cost(
                hc.timestamp, TariffType.G12, OSDOperator.TAURON, g12_rates
            )
            assert hc.cost_pln_kwh < standard_cost

    def test_cost_matches_calculate_cost(self, calculator, g12_rates):
        """Koszt z get_hourly_costs powinien zgadzać się z calculate_cost."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        for hc in result:
            expected_cost = calculator.calculate_cost(
                hc.timestamp, TariffType.G12, OSDOperator.TAURON, g12_rates
            )
            assert hc.cost_pln_kwh == expected_cost

    def test_components_match_zone_rates(self, calculator, g12_rates):
        """Komponenty powinny odpowiadać stawkom dla danej strefy."""
        start = datetime(2024, 1, 15, 0, 0)
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates
        )

        for hc in result:
            if hc.zone == TimeZoneName.SZCZYT:
                assert hc.components == g12_rates[TimeZoneName.SZCZYT]
            elif hc.zone == TimeZoneName.POZASZCZYT:
                assert hc.components == g12_rates[TimeZoneName.POZASZCZYT]

    def test_crossing_midnight(self, calculator, g12_rates):
        """Koszty powinny poprawnie przechodzić przez północ."""
        start = datetime(2024, 1, 15, 22, 0)  # Start at 22:00
        result = calculator.get_hourly_costs(
            start, TariffType.G12, OSDOperator.TAURON, g12_rates, hours=6
        )

        assert len(result) == 6
        # First entry: 22:00 (pozaszczyt)
        assert result[0].hour == 22
        # Last entry: 03:00 next day (pozaszczyt)
        assert result[5].hour == 3
