"""Testy jednostkowe dla PriceHistoryStore."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.peo.models import HourlyPrice
from custom_components.peo.price_store import (
    STORAGE_KEY,
    STORAGE_VERSION,
    PriceHistoryStore,
)


def _make_hourly_price(
    hour: int,
    price_mwh: Decimal | float | int = 250,
    target_date: date | None = None,
) -> HourlyPrice:
    """Pomocnicza funkcja do tworzenia obiektów HourlyPrice."""
    if not isinstance(price_mwh, Decimal):
        price_mwh = Decimal(str(price_mwh))
    price_kwh = price_mwh / Decimal("1000")
    return HourlyPrice(
        hour=hour,
        price_pln_mwh=price_mwh,
        price_pln_kwh=price_kwh,
        date=target_date or date(2024, 1, 15),
    )


def _make_valid_prices(target_date: date | None = None) -> list[HourlyPrice]:
    """Utwórz poprawny zestaw 24 cen godzinowych."""
    return [_make_hourly_price(h, target_date=target_date) for h in range(24)]


@pytest.fixture
def mock_hass():
    """Fixture tworzący mock Home Assistant."""
    return MagicMock()


@pytest.fixture
def mock_store():
    """Fixture tworzący mock Store z async metodami."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    return store


@pytest.fixture
def price_store(mock_hass, mock_store):
    """Fixture tworzący PriceHistoryStore z zamockowanym Store."""
    with patch(
        "custom_components.peo.price_store.Store", return_value=mock_store
    ) as mock_store_cls:
        store = PriceHistoryStore(mock_hass)
        # Verify Store was created with correct params
        mock_store_cls.assert_called_once_with(
            mock_hass, STORAGE_VERSION, STORAGE_KEY
        )
    return store


class TestPriceHistoryStoreInit:
    """Testy inicjalizacji PriceHistoryStore."""

    def test_creates_store_with_correct_key(self, mock_hass):
        """Store powinien być utworzony z kluczem peo_price_history."""
        with patch(
            "custom_components.peo.price_store.Store"
        ) as mock_store_cls:
            PriceHistoryStore(mock_hass)
            mock_store_cls.assert_called_once_with(
                mock_hass, STORAGE_VERSION, STORAGE_KEY
            )

    def test_storage_key_contains_domain(self):
        """Klucz magazynu powinien zawierać domenę integracji."""
        assert "peo" in STORAGE_KEY


class TestPriceHistoryStoreStore:
    """Testy metody store()."""

    @pytest.mark.asyncio
    async def test_store_prices_for_date(self, price_store, mock_store):
        """Zapisanie cen dla daty powinno serializować i zapisać dane."""
        target_date = date(2024, 3, 15)
        prices = _make_valid_prices(target_date)

        await price_store.store(target_date, prices)

        # Verify async_save was called
        mock_store.async_save.assert_called_once()
        saved_data = mock_store.async_save.call_args[0][0]
        assert "2024-03-15" in saved_data
        assert len(saved_data["2024-03-15"]) == 24

    @pytest.mark.asyncio
    async def test_store_serializes_decimal_as_string(self, price_store, mock_store):
        """Decimal powinien być serializowany jako string."""
        target_date = date(2024, 3, 15)
        prices = [_make_hourly_price(0, price_mwh=Decimal("123.45"), target_date=target_date)]

        await price_store.store(target_date, prices)

        saved_data = mock_store.async_save.call_args[0][0]
        entry = saved_data["2024-03-15"][0]
        assert entry["price_pln_mwh"] == "123.45"
        assert isinstance(entry["price_pln_mwh"], str)

    @pytest.mark.asyncio
    async def test_store_overwrites_existing_date(self, price_store, mock_store):
        """Zapis dla istniejącej daty powinien nadpisać dane."""
        target_date = date(2024, 3, 15)
        prices_v1 = [_make_hourly_price(0, price_mwh=100, target_date=target_date)]
        prices_v2 = [_make_hourly_price(0, price_mwh=200, target_date=target_date)]

        await price_store.store(target_date, prices_v1)
        await price_store.store(target_date, prices_v2)

        saved_data = mock_store.async_save.call_args[0][0]
        assert saved_data["2024-03-15"][0]["price_pln_mwh"] == "200"

    @pytest.mark.asyncio
    async def test_store_preserves_other_dates(self, price_store, mock_store):
        """Zapis nowej daty nie powinien usuwać istniejących danych."""
        date1 = date(2024, 3, 14)
        date2 = date(2024, 3, 15)
        prices1 = [_make_hourly_price(0, target_date=date1)]
        prices2 = [_make_hourly_price(0, target_date=date2)]

        await price_store.store(date1, prices1)
        await price_store.store(date2, prices2)

        saved_data = mock_store.async_save.call_args[0][0]
        assert "2024-03-14" in saved_data
        assert "2024-03-15" in saved_data


class TestPriceHistoryStoreGetHistory:
    """Testy metody get_history()."""

    @pytest.mark.asyncio
    async def test_get_history_empty_store(self, price_store, mock_store):
        """Pusty magazyn powinien zwrócić pusty słownik."""
        result = await price_store.get_history()
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_history_returns_recent_data(self, price_store, mock_store):
        """Powinien zwrócić dane z ostatnich N dni."""
        today = date.today()
        prices = _make_valid_prices(today)

        await price_store.store(today, prices)
        result = await price_store.get_history(days=30)

        assert today in result
        assert len(result[today]) == 24

    @pytest.mark.asyncio
    async def test_get_history_deserializes_decimal(self, price_store, mock_store):
        """Decimal powinien być poprawnie deserializowany ze stringa."""
        today = date.today()
        prices = [_make_hourly_price(0, price_mwh=Decimal("345.67"), target_date=today)]

        await price_store.store(today, prices)
        result = await price_store.get_history(days=30)

        assert today in result
        restored_price = result[today][0]
        assert restored_price.price_pln_mwh == Decimal("345.67")
        assert isinstance(restored_price.price_pln_mwh, Decimal)

    @pytest.mark.asyncio
    async def test_get_history_excludes_old_data(self, price_store, mock_store):
        """Dane starsze niż N dni nie powinny być zwracane."""
        old_date = date.today() - timedelta(days=31)
        recent_date = date.today()

        await price_store.store(old_date, [_make_hourly_price(0, target_date=old_date)])
        await price_store.store(recent_date, [_make_hourly_price(0, target_date=recent_date)])

        result = await price_store.get_history(days=30)

        assert old_date not in result
        assert recent_date in result

    @pytest.mark.asyncio
    async def test_get_history_custom_days(self, price_store, mock_store):
        """Parametr days powinien kontrolować zakres historii."""
        today = date.today()
        date_8_days_ago = today - timedelta(days=8)
        date_3_days_ago = today - timedelta(days=3)

        await price_store.store(date_8_days_ago, [_make_hourly_price(0, target_date=date_8_days_ago)])
        await price_store.store(date_3_days_ago, [_make_hourly_price(0, target_date=date_3_days_ago)])

        result = await price_store.get_history(days=7)

        assert date_8_days_ago not in result
        assert date_3_days_ago in result

    @pytest.mark.asyncio
    async def test_get_history_with_preloaded_data(self, price_store, mock_store):
        """Powinien poprawnie załadować dane z trwałego magazynu."""
        today = date.today()
        mock_store.async_load = AsyncMock(return_value={
            today.isoformat(): [
                {
                    "hour": 0,
                    "price_pln_mwh": "250.00",
                    "price_pln_kwh": "0.250",
                    "date": today.isoformat(),
                }
            ]
        })
        # Reset internal cache to force reload
        price_store._data = None

        result = await price_store.get_history(days=30)

        assert today in result
        assert result[today][0].price_pln_mwh == Decimal("250.00")

    @pytest.mark.asyncio
    async def test_get_history_skips_invalid_date_keys(self, price_store, mock_store):
        """Nieprawidłowe klucze dat powinny być pominięte."""
        today = date.today()
        mock_store.async_load = AsyncMock(return_value={
            "invalid-date": [{"hour": 0, "price_pln_mwh": "100", "price_pln_kwh": "0.1", "date": "2024-01-01"}],
            today.isoformat(): [{"hour": 0, "price_pln_mwh": "200", "price_pln_kwh": "0.2", "date": today.isoformat()}],
        })
        price_store._data = None

        result = await price_store.get_history(days=30)

        assert today in result
        assert len(result) == 1


class TestPriceHistoryStoreCleanupOld:
    """Testy metody cleanup_old()."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_entries(self, price_store, mock_store):
        """Wpisy starsze niż 30 dni powinny być usunięte."""
        old_date = date.today() - timedelta(days=31)
        recent_date = date.today()

        await price_store.store(old_date, [_make_hourly_price(0, target_date=old_date)])
        await price_store.store(recent_date, [_make_hourly_price(0, target_date=recent_date)])

        await price_store.cleanup_old()

        saved_data = mock_store.async_save.call_args[0][0]
        assert old_date.isoformat() not in saved_data
        assert recent_date.isoformat() in saved_data

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_entries(self, price_store, mock_store):
        """Wpisy z ostatnich 30 dni powinny być zachowane."""
        dates = [date.today() - timedelta(days=i) for i in range(5)]
        for d in dates:
            await price_store.store(d, [_make_hourly_price(0, target_date=d)])

        await price_store.cleanup_old()

        saved_data = mock_store.async_save.call_args[0][0]
        for d in dates:
            assert d.isoformat() in saved_data

    @pytest.mark.asyncio
    async def test_cleanup_empty_store(self, price_store, mock_store):
        """Czyszczenie pustego magazynu nie powinno powodować błędu."""
        await price_store.cleanup_old()
        # No save should be called since nothing to remove
        # (only the initial load happens)

    @pytest.mark.asyncio
    async def test_cleanup_removes_invalid_keys(self, price_store, mock_store):
        """Nieprawidłowe klucze dat powinny być usunięte podczas czyszczenia."""
        today = date.today()
        mock_store.async_load = AsyncMock(return_value={
            "not-a-date": [{"hour": 0}],
            today.isoformat(): [{"hour": 0, "price_pln_mwh": "100", "price_pln_kwh": "0.1", "date": today.isoformat()}],
        })
        price_store._data = None

        await price_store.cleanup_old()

        saved_data = mock_store.async_save.call_args[0][0]
        assert "not-a-date" not in saved_data
        assert today.isoformat() in saved_data

    @pytest.mark.asyncio
    async def test_cleanup_boundary_exactly_30_days_kept(self, price_store, mock_store):
        """Wpis dokładnie sprzed 30 dni powinien być zachowany (cutoff = today - 30)."""
        boundary_date = date.today() - timedelta(days=30)
        await price_store.store(boundary_date, [_make_hourly_price(0, target_date=boundary_date)])

        await price_store.cleanup_old()

        # The cutoff is today - 30 days; entry_date >= cutoff means it's kept
        saved_data = mock_store.async_save.call_args[0][0]
        assert boundary_date.isoformat() in saved_data

    @pytest.mark.asyncio
    async def test_cleanup_boundary_31_days_removed(self, price_store, mock_store):
        """Wpis sprzed 31 dni powinien być usunięty."""
        old_date = date.today() - timedelta(days=31)
        await price_store.store(old_date, [_make_hourly_price(0, target_date=old_date)])

        await price_store.cleanup_old()

        saved_data = mock_store.async_save.call_args[0][0]
        assert old_date.isoformat() not in saved_data


class TestPriceHistoryStoreSerialization:
    """Testy serializacji/deserializacji."""

    def test_serialize_price(self):
        """Serializacja HourlyPrice powinna zwrócić poprawny słownik."""
        price = HourlyPrice(
            hour=5,
            price_pln_mwh=Decimal("345.67"),
            price_pln_kwh=Decimal("0.34567"),
            date=date(2024, 6, 15),
        )
        result = PriceHistoryStore._serialize_price(price)

        assert result == {
            "hour": 5,
            "price_pln_mwh": "345.67",
            "price_pln_kwh": "0.34567",
            "date": "2024-06-15",
        }

    def test_deserialize_price(self):
        """Deserializacja słownika powinna zwrócić poprawny HourlyPrice."""
        data = {
            "hour": 12,
            "price_pln_mwh": "500.00",
            "price_pln_kwh": "0.500",
            "date": "2024-07-20",
        }
        result = PriceHistoryStore._deserialize_price(data)

        assert result.hour == 12
        assert result.price_pln_mwh == Decimal("500.00")
        assert result.price_pln_kwh == Decimal("0.500")
        assert result.date == date(2024, 7, 20)

    def test_roundtrip_serialization(self):
        """Serializacja i deserializacja powinny zachować dane."""
        original = HourlyPrice(
            hour=23,
            price_pln_mwh=Decimal("1234.5678"),
            price_pln_kwh=Decimal("1.2345678"),
            date=date(2024, 12, 31),
        )
        serialized = PriceHistoryStore._serialize_price(original)
        restored = PriceHistoryStore._deserialize_price(serialized)

        assert restored == original

    def test_roundtrip_preserves_decimal_precision(self):
        """Precyzja Decimal powinna być zachowana po serializacji."""
        original = HourlyPrice(
            hour=0,
            price_pln_mwh=Decimal("0.01"),
            price_pln_kwh=Decimal("0.00001"),
            date=date(2024, 1, 1),
        )
        serialized = PriceHistoryStore._serialize_price(original)
        restored = PriceHistoryStore._deserialize_price(serialized)

        assert restored.price_pln_mwh == original.price_pln_mwh
        assert restored.price_pln_kwh == original.price_pln_kwh
