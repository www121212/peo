"""Testy jednostkowe dla PriceDataCoordinator."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.peo.enums import PriceDataStatus
from custom_components.peo.models import HourlyPrice, PriceData, PriceStats
from custom_components.peo.price_coordinator import (
    PriceDataCoordinator,
    _DEFAULT_UPDATE_INTERVAL,
    _WAITING_UPDATE_INTERVAL,
    _get_poland_now,
)
from custom_components.peo.price_validator import PriceValidator
from custom_components.peo.rce_client import (
    RCEApiClient,
    RCEApiConnectionError,
    RCEApiError,
    RCEApiTimeoutError,
)


def _make_hourly_prices(
    target_date: date | None = None,
    base_price: Decimal = Decimal("200"),
    count: int = 24,
) -> list[HourlyPrice]:
    """Generuj listę HourlyPrice do testów.

    Args:
        target_date: Data cen (domyślnie: dziś).
        base_price: Bazowa cena PLN/MWh.
        count: Liczba godzin.

    Returns:
        Lista obiektów HourlyPrice.
    """
    if target_date is None:
        target_date = date.today()
    prices = []
    for h in range(count):
        price_mwh = base_price + Decimal(str(h * 10))
        price_kwh = price_mwh / Decimal("1000")
        prices.append(
            HourlyPrice(
                hour=h,
                price_pln_mwh=price_mwh,
                price_pln_kwh=price_kwh,
                date=target_date,
            )
        )
    return prices


@pytest.fixture
def mock_hass():
    """Fixture: mock Home Assistant."""
    hass = MagicMock()
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    return hass


@pytest.fixture
def mock_rce_client():
    """Fixture: mock RCEApiClient."""
    client = AsyncMock(spec=RCEApiClient)
    return client


@pytest.fixture
def mock_validator():
    """Fixture: mock PriceValidator."""
    validator = MagicMock(spec=PriceValidator)
    validator.validate = MagicMock(return_value=True)
    return validator


@pytest.fixture
def mock_store():
    """Fixture: mock PriceHistoryStore."""
    store = AsyncMock()
    store.store = AsyncMock()
    return store


@pytest.fixture
def coordinator(mock_hass, mock_rce_client, mock_validator, mock_store):
    """Fixture: instancja PriceDataCoordinator z mockami."""
    return PriceDataCoordinator(
        hass=mock_hass,
        rce_client=mock_rce_client,
        price_validator=mock_validator,
        price_store=mock_store,
    )


class TestPriceDataCoordinatorInit:
    """Testy inicjalizacji koordynatora."""

    def test_initial_status_is_no_data(self, coordinator):
        """Początkowy status to NO_DATA."""
        assert coordinator.status == PriceDataStatus.NO_DATA

    def test_initial_update_interval(self, coordinator):
        """Początkowy interwał to 60 minut."""
        assert coordinator.update_interval == _DEFAULT_UPDATE_INTERVAL

    def test_initial_last_successful_fetch_is_none(self, coordinator):
        """Początkowy last_successful_fetch to None."""
        assert coordinator.last_successful_fetch is None

    def test_initial_today_prices_is_none(self, coordinator):
        """Początkowe ceny na dziś to None."""
        assert coordinator.get_today_prices() is None

    def test_initial_tomorrow_prices_is_none(self, coordinator):
        """Początkowe ceny na jutro to None."""
        assert coordinator.get_tomorrow_prices() is None


class TestAsyncUpdateDataSuccess:
    """Testy pomyślnego pobrania danych."""

    @pytest.mark.asyncio
    async def test_successful_fetch_today(
        self, coordinator, mock_rce_client, mock_validator, mock_store, mock_hass
    ):
        """Pomyślne pobranie cen na dziś — status OK."""
        today = date.today()
        prices = _make_hourly_prices(today)
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)
        mock_validator.validate.return_value = True

        # Symuluj czas przed 13:30
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        assert result.status == PriceDataStatus.OK
        assert result.today == prices
        assert result.tomorrow is None
        assert coordinator.status == PriceDataStatus.OK

    @pytest.mark.asyncio
    async def test_successful_fetch_stores_prices(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Pomyślne pobranie zapisuje ceny do magazynu."""
        target_date = date(2024, 6, 15)
        prices = _make_hourly_prices(target_date)
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        mock_store.store.assert_called_once_with(target_date, prices)

    @pytest.mark.asyncio
    async def test_successful_fetch_fires_event(
        self, coordinator, mock_rce_client, mock_validator, mock_store, mock_hass
    ):
        """Pomyślne pobranie wyzwala zdarzenie peo_prices_updated."""
        target_date = date(2024, 6, 15)
        prices = _make_hourly_prices(target_date)
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        mock_hass.bus.async_fire.assert_called_once_with(
            "peo_prices_updated",
            {"date": target_date.isoformat(), "source": "rce_pse"},
        )

    @pytest.mark.asyncio
    async def test_successful_fetch_updates_last_successful_fetch(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Pomyślne pobranie aktualizuje last_successful_fetch."""
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        fake_now = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator._async_update_data()

        assert coordinator.last_successful_fetch == fake_now


class TestAsyncUpdateDataTomorrow:
    """Testy pobierania cen na jutro."""

    @pytest.mark.asyncio
    async def test_fetches_tomorrow_after_1330(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Po 13:30 próbuje pobrać ceny na jutro."""
        today = date(2024, 6, 15)
        tomorrow = date(2024, 6, 16)
        today_prices = _make_hourly_prices(today)
        tomorrow_prices = _make_hourly_prices(tomorrow, base_price=Decimal("300"))

        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, tomorrow_prices]
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        assert result.tomorrow == tomorrow_prices
        assert result.status == PriceDataStatus.OK

    @pytest.mark.asyncio
    async def test_does_not_fetch_tomorrow_before_1330(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Przed 13:30 nie próbuje pobrać cen na jutro."""
        today_prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=today_prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        # Powinno być tylko jedno wywołanie (dziś)
        assert mock_rce_client.fetch_prices.call_count == 1

    @pytest.mark.asyncio
    async def test_waiting_status_when_tomorrow_unavailable_after_1330(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Status WAITING gdy po 13:30 ceny na jutro niedostępne."""
        today = date(2024, 6, 15)
        today_prices = _make_hourly_prices(today)

        # Dziś OK, jutro błąd
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, RCEApiConnectionError("timeout")]
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        assert result.status == PriceDataStatus.WAITING
        assert coordinator.status == PriceDataStatus.WAITING

    @pytest.mark.asyncio
    async def test_shorter_interval_when_waiting(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Interwał 15 min gdy oczekujemy na ceny jutrzejsze."""
        today_prices = _make_hourly_prices()

        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, RCEApiConnectionError("timeout")]
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.update_interval == _WAITING_UPDATE_INTERVAL


class TestAsyncUpdateDataFailure:
    """Testy obsługi błędów pobierania."""

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_old_data(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Błąd pobierania zachowuje ostatnie poprawne dane."""
        today_prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=today_prices)

        # Pierwsze pobranie — sukces
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        # Drugie pobranie — błąd
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=RCEApiTimeoutError("timeout")
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 11, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        assert result.today == today_prices
        assert result.status == PriceDataStatus.STALE

    @pytest.mark.asyncio
    async def test_stale_status_on_fetch_failure(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Status STALE po nieudanym pobraniu (gdy mamy stare dane)."""
        today_prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=today_prices)

        # Sukces
        fake_now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator._async_update_data()

        # Błąd (w ciągu 24h)
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=RCEApiError("error")
        )
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=fake_now + timedelta(hours=2),
        ):
            result = await coordinator._async_update_data()

        assert result.status == PriceDataStatus.STALE

    @pytest.mark.asyncio
    async def test_no_data_status_after_24h_without_success(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Status NO_DATA po 24h bez pomyślnego pobrania."""
        today_prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=today_prices)

        # Sukces
        fake_now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=fake_now,
        ):
            await coordinator._async_update_data()

        # Błąd po 24h+
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=RCEApiError("error")
        )
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=fake_now + timedelta(hours=25),
        ):
            result = await coordinator._async_update_data()

        assert result.status == PriceDataStatus.NO_DATA

    @pytest.mark.asyncio
    async def test_update_failed_when_no_data_at_all(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """UpdateFailed gdy brak jakichkolwiek danych."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=RCEApiError("error")
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()


class TestAsyncUpdateDataValidation:
    """Testy walidacji danych."""

    @pytest.mark.asyncio
    async def test_invalid_data_rejected(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Dane niespełniające walidacji są odrzucane."""
        from homeassistant.helpers.update_coordinator import UpdateFailed

        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)
        mock_validator.validate.return_value = False

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            with pytest.raises(UpdateFailed):
                await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_invalid_data_keeps_old_valid_data(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Odrzucone dane nie nadpisują starych poprawnych danych."""
        today_prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=today_prices)
        mock_validator.validate.return_value = True

        # Pierwsze pobranie — sukces
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        # Drugie pobranie — walidacja odrzuca
        mock_validator.validate.return_value = False
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 11, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        # Stare dane zachowane
        assert result.today == today_prices
        assert result.status == PriceDataStatus.STALE


class TestComputeStats:
    """Testy obliczania statystyk cenowych."""

    def test_stats_min_max_avg(self):
        """Poprawne obliczenie min, max, avg."""
        prices = _make_hourly_prices(base_price=Decimal("100"))
        stats = PriceDataCoordinator._compute_stats(prices)

        # min = 100 (hour 0), max = 100 + 23*10 = 330 (hour 23)
        assert stats.min_price == Decimal("100")
        assert stats.max_price == Decimal("330")
        assert stats.min_hour == 0
        assert stats.max_hour == 23

        # avg = (100 + 110 + ... + 330) / 24 = (100*24 + 10*(0+1+...+23)) / 24
        # = (2400 + 10*276) / 24 = (2400 + 2760) / 24 = 5160 / 24 = 215
        assert stats.avg_price == Decimal("215.00")

    def test_stats_empty_prices(self):
        """Pusta lista cen zwraca zerowe statystyki."""
        stats = PriceDataCoordinator._compute_stats([])
        assert stats.min_price == Decimal("0")
        assert stats.max_price == Decimal("0")
        assert stats.avg_price == Decimal("0")

    def test_stats_single_price(self):
        """Jedna cena — min == max == avg."""
        prices = [
            HourlyPrice(
                hour=5,
                price_pln_mwh=Decimal("250"),
                price_pln_kwh=Decimal("0.250"),
                date=date.today(),
            )
        ]
        stats = PriceDataCoordinator._compute_stats(prices)
        assert stats.min_price == Decimal("250")
        assert stats.max_price == Decimal("250")
        assert stats.avg_price == Decimal("250.00")
        assert stats.min_hour == 5
        assert stats.max_hour == 5


class TestPublicAPI:
    """Testy publicznego API koordynatora."""

    @pytest.mark.asyncio
    async def test_get_current_price(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """get_current_price zwraca cenę na bieżącą godzinę."""
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        # Sprawdź cenę na godzinę 10
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc),
        ):
            current = coordinator.get_current_price()

        # hour=10 -> base_price + 10*10 = 200 + 100 = 300
        assert current == Decimal("300")

    @pytest.mark.asyncio
    async def test_get_current_price_none_when_no_data(self, coordinator):
        """get_current_price zwraca None gdy brak danych."""
        assert coordinator.get_current_price() is None

    @pytest.mark.asyncio
    async def test_is_data_stale(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """is_data_stale zwraca True dla statusów STALE i NO_DATA."""
        assert coordinator.is_data_stale() is True  # NO_DATA initially

        # Po sukcesie
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.is_data_stale() is False

    @pytest.mark.asyncio
    async def test_get_price_stats(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """get_price_stats zwraca statystyki po pomyślnym pobraniu."""
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        stats = coordinator.get_price_stats()
        assert stats is not None
        assert stats.min_price == Decimal("200")
        assert stats.max_price == Decimal("430")

    def test_get_price_stats_none_when_no_data(self, coordinator):
        """get_price_stats zwraca None gdy brak danych."""
        assert coordinator.get_price_stats() is None


class TestStoreError:
    """Testy obsługi błędów zapisu do magazynu."""

    @pytest.mark.asyncio
    async def test_store_error_does_not_break_update(
        self, coordinator, mock_rce_client, mock_validator, mock_store, mock_hass
    ):
        """Błąd zapisu do magazynu nie przerywa aktualizacji."""
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)
        mock_store.store = AsyncMock(side_effect=Exception("Storage error"))

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
        ):
            result = await coordinator._async_update_data()

        # Dane powinny być dostępne mimo błędu zapisu
        assert result.today == prices
        assert result.status == PriceDataStatus.OK


class TestIntervalAdjustment:
    """Testy dostosowania interwału aktualizacji."""

    @pytest.mark.asyncio
    async def test_normal_interval_before_1330(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Standardowy interwał 60 min przed 13:30."""
        prices = _make_hourly_prices()
        mock_rce_client.fetch_prices = AsyncMock(return_value=prices)

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.update_interval == _DEFAULT_UPDATE_INTERVAL

    @pytest.mark.asyncio
    async def test_normal_interval_when_tomorrow_available(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Standardowy interwał gdy ceny na jutro dostępne."""
        today = date(2024, 6, 15)
        tomorrow = date(2024, 6, 16)
        today_prices = _make_hourly_prices(today)
        tomorrow_prices = _make_hourly_prices(tomorrow)

        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, tomorrow_prices]
        )

        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.update_interval == _DEFAULT_UPDATE_INTERVAL

    @pytest.mark.asyncio
    async def test_short_interval_restored_after_tomorrow_fetched(
        self, coordinator, mock_rce_client, mock_validator, mock_store
    ):
        """Interwał wraca do 60 min po pobraniu cen na jutro."""
        today = date(2024, 6, 15)
        tomorrow = date(2024, 6, 16)
        today_prices = _make_hourly_prices(today)

        # Pierwsza aktualizacja — jutro niedostępne
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, RCEApiError("not available")]
        )
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 0, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.update_interval == _WAITING_UPDATE_INTERVAL

        # Druga aktualizacja — jutro dostępne
        tomorrow_prices = _make_hourly_prices(tomorrow)
        mock_rce_client.fetch_prices = AsyncMock(
            side_effect=[today_prices, tomorrow_prices]
        )
        with patch(
            "custom_components.peo.price_coordinator._get_poland_now",
            return_value=datetime(2024, 6, 15, 14, 15, tzinfo=timezone.utc),
        ):
            await coordinator._async_update_data()

        assert coordinator.update_interval == _DEFAULT_UPDATE_INTERVAL
