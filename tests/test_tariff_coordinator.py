"""Testy jednostkowe dla TariffDataCoordinator."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import HourlyCost, HourlyPrice, TariffRates
from custom_components.peo.tariff_calculator import TariffCalculator
from custom_components.peo.tariff_coordinator import (
    TariffDataCoordinator,
    TariffData,
    _DEFAULT_TARIFF_UPDATE_INTERVAL,
    _get_poland_now,
)
from custom_components.peo.tariff_loader import TariffDefinitionLoader


@pytest.fixture
def mock_hass():
    """Fixture: mock Home Assistant."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    return hass


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


@pytest.fixture
def coordinator(mock_hass, calculator, g12_rates):
    """Fixture: TariffDataCoordinator z G12/Tauron."""
    return TariffDataCoordinator(
        hass=mock_hass,
        tariff_calculator=calculator,
        tariff_type=TariffType.G12,
        osd_operator=OSDOperator.TAURON,
        rates=g12_rates,
    )


@pytest.fixture
def mock_price_coordinator():
    """Fixture: mock PriceDataCoordinator."""
    pc = MagicMock()
    pc.get_today_prices = MagicMock(return_value=None)
    return pc


class TestTariffDataCoordinatorInit:
    """Testy inicjalizacji koordynatora."""

    def test_initial_update_interval(self, coordinator):
        """Początkowy interwał to 15 minut."""
        assert coordinator.update_interval == _DEFAULT_TARIFF_UPDATE_INTERVAL

    def test_update_interval_is_15_minutes(self, coordinator):
        """Interwał aktualizacji wynosi dokładnie 15 minut."""
        assert coordinator.update_interval == timedelta(minutes=15)

    def test_initial_data_is_none(self, coordinator):
        """Początkowe dane to None."""
        assert coordinator.data is None

    def test_tariff_type_property(self, coordinator):
        """Właściwość tariff_type zwraca poprawny typ."""
        assert coordinator.tariff_type == TariffType.G12

    def test_osd_operator_property(self, coordinator):
        """Właściwość osd_operator zwraca poprawnego operatora."""
        assert coordinator.osd_operator == OSDOperator.TAURON

    def test_coordinator_name(self, coordinator):
        """Nazwa koordynatora zawiera domenę."""
        assert "peo" in coordinator.name


class TestAsyncUpdateData:
    """Testy _async_update_data()."""

    @pytest.mark.asyncio
    async def test_returns_tariff_data(self, coordinator):
        """Aktualizacja zwraca obiekt TariffData."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        assert isinstance(result, TariffData)

    @pytest.mark.asyncio
    async def test_current_cost_has_4_decimal_places(self, coordinator):
        """Bieżący koszt ma 4 miejsca po przecinku."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        assert result.current_cost == result.current_cost.quantize(Decimal("0.0001"))

    @pytest.mark.asyncio
    async def test_current_zone_szczyt_during_peak(self, coordinator):
        """Strefa SZCZYT w godzinach szczytu G12 Tauron."""
        # Monday 10:00 → szczyt for G12 Tauron
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        assert result.current_zone == TimeZoneName.SZCZYT

    @pytest.mark.asyncio
    async def test_current_zone_pozaszczyt_during_offpeak(self, coordinator):
        """Strefa POZASZCZYT w godzinach pozaszczytu G12 Tauron."""
        # Monday 03:00 → pozaszczyt for G12 Tauron
        fake_now = datetime(2024, 1, 15, 3, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        assert result.current_zone == TimeZoneName.POZASZCZYT

    @pytest.mark.asyncio
    async def test_hourly_costs_has_24_entries(self, coordinator):
        """Prognoza kosztów zawiera 24 godziny."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        assert len(result.hourly_costs) == 24

    @pytest.mark.asyncio
    async def test_hourly_costs_are_hourlycost_objects(self, coordinator):
        """Elementy prognozy to obiekty HourlyCost."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        for hc in result.hourly_costs:
            assert isinstance(hc, HourlyCost)

    @pytest.mark.asyncio
    async def test_cost_matches_calculator(self, coordinator, calculator, g12_rates):
        """Koszt z koordynatora zgadza się z bezpośrednim obliczeniem."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        expected_cost = calculator.calculate_cost(
            fake_now, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        assert result.current_cost == expected_cost


class TestZoneChangeTracking:
    """Testy śledzenia zmian stref."""

    @pytest.mark.asyncio
    async def test_zone_change_logged(self, coordinator, caplog):
        """Zmiana strefy jest logowana na poziomie INFO."""
        import logging

        # First update: szczyt (10:00)
        fake_now_1 = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now_1,
        ):
            await coordinator._async_update_data()

        # Second update: pozaszczyt (03:00)
        fake_now_2 = datetime(2024, 1, 15, 3, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now_2,
        ), caplog.at_level(logging.INFO):
            await coordinator._async_update_data()

        assert "Zmiana strefy taryfowej" in caplog.text

    @pytest.mark.asyncio
    async def test_no_log_when_zone_unchanged(self, coordinator, caplog):
        """Brak logu gdy strefa się nie zmienia."""
        import logging

        # Two updates in same zone (szczyt)
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator._async_update_data()

        fake_now_2 = datetime(2024, 1, 15, 11, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now_2,
        ), caplog.at_level(logging.INFO):
            caplog.clear()
            await coordinator._async_update_data()

        assert "Zmiana strefy taryfowej" not in caplog.text

    @pytest.mark.asyncio
    async def test_first_update_no_zone_change_log(self, coordinator, caplog):
        """Pierwsza aktualizacja nie loguje zmiany strefy."""
        import logging

        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ), caplog.at_level(logging.INFO):
            await coordinator._async_update_data()

        assert "Zmiana strefy taryfowej" not in caplog.text


class TestUpdateRates:
    """Testy aktualizacji stawek bez restartu."""

    @pytest.mark.asyncio
    async def test_update_rates_changes_cost(self, coordinator):
        """Aktualizacja stawek zmienia obliczany koszt."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))

        # Oblicz koszt z oryginalnymi stawkami
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result_before = await coordinator._async_update_data()

        # Zmień stawki (wyższa cena energii)
        new_rates = {
            TimeZoneName.SZCZYT: TariffRates(
                energy_price=Decimal("0.9000"),
                distribution_variable=Decimal("0.2596"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
            TimeZoneName.POZASZCZYT: TariffRates(
                energy_price=Decimal("0.9000"),
                distribution_variable=Decimal("0.0756"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }
        coordinator.update_rates(new_rates)

        # Oblicz koszt z nowymi stawkami
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result_after = await coordinator._async_update_data()

        assert result_after.current_cost > result_before.current_cost

    @pytest.mark.asyncio
    async def test_update_rates_logs_info(self, coordinator, caplog):
        """Aktualizacja stawek loguje INFO."""
        import logging

        new_rates = {
            TimeZoneName.SZCZYT: TariffRates(
                energy_price=Decimal("0.9000"),
                distribution_variable=Decimal("0.2596"),
                transition_fee=Decimal("0.0009"),
                oze_fee=Decimal("0.0027"),
                capacity_fee=Decimal("0.0762"),
                cogeneration_fee=Decimal("0.0058"),
            ),
        }

        with caplog.at_level(logging.INFO):
            coordinator.update_rates(new_rates)

        assert "Zaktualizowano stawki taryfowe" in caplog.text


class TestRCEPriceIntegration:
    """Testy integracji z PriceDataCoordinator."""

    @pytest.mark.asyncio
    async def test_uses_rce_price_when_available(
        self, mock_hass, calculator, g12_rates, mock_price_coordinator
    ):
        """Używa ceny RCE gdy PriceDataCoordinator dostępny."""
        # Setup RCE prices
        rce_prices = [
            HourlyPrice(
                hour=h,
                price_pln_mwh=Decimal("350.00"),
                price_pln_kwh=Decimal("0.3500"),
                date=date(2024, 1, 15),
            )
            for h in range(24)
        ]
        mock_price_coordinator.get_today_prices.return_value = rce_prices

        coord = TariffDataCoordinator(
            hass=mock_hass,
            tariff_calculator=calculator,
            tariff_type=TariffType.G12,
            osd_operator=OSDOperator.TAURON,
            rates=g12_rates,
            price_coordinator=mock_price_coordinator,
        )

        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coord._async_update_data()

        # Cost should use RCE price (0.35) instead of energy_price (0.6221)
        # So total should be lower
        cost_without_rce = calculator.calculate_cost(
            fake_now, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        assert result.current_cost < cost_without_rce

    @pytest.mark.asyncio
    async def test_no_rce_price_when_coordinator_none(self, coordinator, g12_rates, calculator):
        """Bez PriceDataCoordinator używa standardowej ceny energii."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        expected = calculator.calculate_cost(
            fake_now, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        assert result.current_cost == expected

    @pytest.mark.asyncio
    async def test_no_rce_price_when_today_prices_none(
        self, mock_hass, calculator, g12_rates, mock_price_coordinator
    ):
        """Gdy ceny RCE niedostępne, używa standardowej ceny."""
        mock_price_coordinator.get_today_prices.return_value = None

        coord = TariffDataCoordinator(
            hass=mock_hass,
            tariff_calculator=calculator,
            tariff_type=TariffType.G12,
            osd_operator=OSDOperator.TAURON,
            rates=g12_rates,
            price_coordinator=mock_price_coordinator,
        )

        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coord._async_update_data()

        expected = calculator.calculate_cost(
            fake_now, TariffType.G12, OSDOperator.TAURON, g12_rates
        )
        assert result.current_cost == expected


class TestPublicAPI:
    """Testy publicznego API koordynatora."""

    @pytest.mark.asyncio
    async def test_get_current_cost_returns_decimal(self, coordinator):
        """get_current_cost() zwraca Decimal."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator.async_refresh()

        cost = coordinator.get_current_cost()
        assert isinstance(cost, Decimal)

    @pytest.mark.asyncio
    async def test_get_current_cost_zero_when_no_data(self, coordinator):
        """get_current_cost() zwraca 0.0000 gdy brak danych."""
        assert coordinator.get_current_cost() == Decimal("0.0000")

    @pytest.mark.asyncio
    async def test_get_current_zone_returns_timezone_name(self, coordinator):
        """get_current_zone() zwraca TimeZoneName."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator.async_refresh()

        zone = coordinator.get_current_zone()
        assert isinstance(zone, TimeZoneName)
        assert zone == TimeZoneName.SZCZYT

    @pytest.mark.asyncio
    async def test_get_current_zone_single_when_no_data(self, coordinator):
        """get_current_zone() zwraca SINGLE gdy brak danych."""
        assert coordinator.get_current_zone() == TimeZoneName.SINGLE

    @pytest.mark.asyncio
    async def test_get_hourly_costs_returns_list(self, coordinator):
        """get_hourly_costs() zwraca listę HourlyCost."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator.async_refresh()

        costs = coordinator.get_hourly_costs()
        assert isinstance(costs, list)
        assert len(costs) == 24
        for hc in costs:
            assert isinstance(hc, HourlyCost)

    @pytest.mark.asyncio
    async def test_get_hourly_costs_empty_when_no_data(self, coordinator):
        """get_hourly_costs() zwraca pustą listę gdy brak danych."""
        assert coordinator.get_hourly_costs() == []


class TestG11SingleZone:
    """Testy z taryfą G11 (jednolita strefa)."""

    @pytest.mark.asyncio
    async def test_g11_always_single_zone(self, mock_hass, calculator, g11_rates):
        """G11 zawsze zwraca strefę SINGLE."""
        coord = TariffDataCoordinator(
            hass=mock_hass,
            tariff_calculator=calculator,
            tariff_type=TariffType.G11,
            osd_operator=OSDOperator.TAURON,
            rates=g11_rates,
        )

        # Test at different times
        for hour in [0, 6, 12, 18, 23]:
            fake_now = datetime(2024, 1, 15, hour, 0, tzinfo=timezone(timedelta(hours=1)))
            with patch(
                "custom_components.peo.tariff_coordinator._get_poland_now",
                return_value=fake_now,
            ):
                result = await coord._async_update_data()

            assert result.current_zone == TimeZoneName.SINGLE

    @pytest.mark.asyncio
    async def test_g11_constant_cost(self, mock_hass, calculator, g11_rates):
        """G11 ma stały koszt niezależnie od godziny."""
        coord = TariffDataCoordinator(
            hass=mock_hass,
            tariff_calculator=calculator,
            tariff_type=TariffType.G11,
            osd_operator=OSDOperator.TAURON,
            rates=g11_rates,
        )

        costs = []
        for hour in [0, 6, 12, 18, 23]:
            fake_now = datetime(2024, 1, 15, hour, 0, tzinfo=timezone(timedelta(hours=1)))
            with patch(
                "custom_components.peo.tariff_coordinator._get_poland_now",
                return_value=fake_now,
            ):
                result = await coord._async_update_data()
            costs.append(result.current_cost)

        # All costs should be the same
        assert len(set(costs)) == 1


class TestCostPrecision:
    """Testy precyzji kosztów (4 miejsca po przecinku)."""

    @pytest.mark.asyncio
    async def test_current_cost_4_decimal_places(self, coordinator):
        """Bieżący koszt ma dokładnie 4 miejsca po przecinku."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        # Verify 4 decimal places
        cost_str = str(result.current_cost)
        decimal_part = cost_str.split(".")[1] if "." in cost_str else ""
        assert len(decimal_part) == 4

    @pytest.mark.asyncio
    async def test_hourly_costs_4_decimal_places(self, coordinator):
        """Koszty godzinowe mają 4 miejsca po przecinku."""
        fake_now = datetime(2024, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))
        with patch(
            "custom_components.peo.tariff_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            result = await coordinator._async_update_data()

        for hc in result.hourly_costs:
            assert hc.cost_pln_kwh == hc.cost_pln_kwh.quantize(Decimal("0.0001"))
