"""Testy jednostkowe dla klienta RCE API PSE."""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from custom_components.peo.rce_client import (
    RCE_API_URL,
    RCE_ENDPOINT,
    RCEApiClient,
    RCEApiConnectionError,
    RCEApiRateLimitError,
    RCEApiResponseError,
    RCEApiTimeoutError,
)
from custom_components.peo.rate_limiter import RateLimiter


def _make_rce_response(num_hours: int = 24, base_price: float = 250.0) -> dict:
    """Generuj przykładową odpowiedź API RCE PSE.

    Args:
        num_hours: Liczba godzin w odpowiedzi (1-24).
        base_price: Bazowa cena PLN/MWh (każda godzina +10).

    Returns:
        Słownik imitujący odpowiedź JSON z API.
    """
    records = []
    for i in range(num_hours):
        records.append(
            {
                "rce_pln": base_price + i * 10,
                "business_date": "2024-06-15",
                "udtczas": str(i + 1),  # 1-24
            }
        )
    return {"value": records}


class FakeResponse:
    """Fałszywa odpowiedź HTTP do testów."""

    def __init__(self, status: int, json_data: dict | None = None, text: str = ""):
        self.status = status
        self._json_data = json_data
        self._text = text

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def rate_limiter():
    """Fixture: świeży RateLimiter."""
    return RateLimiter()


@pytest.fixture
def mock_session():
    """Fixture: mock sesji aiohttp."""
    return MagicMock(spec=aiohttp.ClientSession)


@pytest.fixture
def client(mock_session, rate_limiter):
    """Fixture: instancja RCEApiClient z mockami."""
    return RCEApiClient(session=mock_session, rate_limiter=rate_limiter)


class TestFetchPricesSuccess:
    """Testy poprawnego pobierania cen."""

    @pytest.mark.asyncio
    async def test_fetch_24_prices(self, client, mock_session):
        """Pobranie 24 cen godzinowych — poprawna odpowiedź API."""
        response_data = _make_rce_response(24, base_price=200.0)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        target = date(2024, 6, 15)
        prices = await client.fetch_prices(target)

        assert len(prices) == 24
        # Sprawdź sortowanie wg godziny
        for i, price in enumerate(prices):
            assert price.hour == i
            assert price.date == target

    @pytest.mark.asyncio
    async def test_price_conversion_mwh_to_kwh(self, client, mock_session):
        """Przeliczenie PLN/MWh na PLN/kWh (dzielenie przez 1000)."""
        response_data = {
            "value": [
                {"rce_pln": 500.0, "business_date": "2024-06-15", "udtczas": "1"}
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        assert len(prices) == 1
        assert prices[0].price_pln_mwh == Decimal("500.0")
        assert prices[0].price_pln_kwh == Decimal("0.500000")

    @pytest.mark.asyncio
    async def test_prices_sorted_by_hour(self, client, mock_session):
        """Ceny są posortowane wg godziny nawet gdy API zwraca w innej kolejności."""
        response_data = {
            "value": [
                {"rce_pln": 300.0, "business_date": "2024-06-15", "udtczas": "24"},
                {"rce_pln": 100.0, "business_date": "2024-06-15", "udtczas": "1"},
                {"rce_pln": 200.0, "business_date": "2024-06-15", "udtczas": "12"},
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        assert len(prices) == 3
        assert prices[0].hour == 0
        assert prices[1].hour == 11
        assert prices[2].hour == 23

    @pytest.mark.asyncio
    async def test_request_params(self, client, mock_session):
        """Sprawdź poprawne parametry żądania HTTP."""
        response_data = _make_rce_response(24)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        target = date(2024, 1, 20)
        await client.fetch_prices(target)

        mock_session.get.assert_called_once()
        call_args = mock_session.get.call_args
        assert call_args[0][0] == RCE_API_URL
        assert call_args[1]["params"] == {
            "$filter": "business_date eq '2024-01-20'"
        }
        # Timeout 30s
        timeout = call_args[1]["timeout"]
        assert timeout.total == 30


class TestFetchPricesRateLimiting:
    """Testy rate limitingu."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, mock_session):
        """Rzuca RCEApiRateLimitError gdy limit osiągnięty."""
        limiter = RateLimiter()
        # Wyczerpaj limit
        for _ in range(60):
            limiter.acquire(RCE_ENDPOINT)

        client = RCEApiClient(session=mock_session, rate_limiter=limiter)

        with pytest.raises(RCEApiRateLimitError):
            await client.fetch_prices(date(2024, 6, 15))

        # Sesja nie powinna być wywołana
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limiter_called_before_request(self, client, mock_session, rate_limiter):
        """Rate limiter jest sprawdzany przed wykonaniem żądania HTTP."""
        response_data = _make_rce_response(24)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await client.fetch_prices(date(2024, 6, 15))

        # Po wywołaniu powinno być 59 pozostałych
        remaining = rate_limiter.get_remaining(RCE_ENDPOINT)
        assert remaining == 59


class TestFetchPricesHTTPErrors:
    """Testy obsługi błędów HTTP."""

    @pytest.mark.asyncio
    async def test_http_500_raises_response_error(self, client, mock_session):
        """Kod 500 rzuca RCEApiResponseError."""
        fake_resp = FakeResponse(status=500, text="Internal Server Error")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(RCEApiResponseError) as exc_info:
            await client.fetch_prices(date(2024, 6, 15))

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_http_503_raises_response_error(self, client, mock_session):
        """Kod 503 rzuca RCEApiResponseError."""
        fake_resp = FakeResponse(status=503, text="Service Unavailable")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(RCEApiResponseError) as exc_info:
            await client.fetch_prices(date(2024, 6, 15))

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_http_404_raises_response_error(self, client, mock_session):
        """Kod 404 rzuca RCEApiResponseError."""
        fake_resp = FakeResponse(status=404, text="Not Found")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(RCEApiResponseError) as exc_info:
            await client.fetch_prices(date(2024, 6, 15))

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_http_429_raises_response_error(self, client, mock_session):
        """Kod 429 (Too Many Requests) rzuca RCEApiResponseError."""
        fake_resp = FakeResponse(status=429, text="Too Many Requests")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(RCEApiResponseError) as exc_info:
            await client.fetch_prices(date(2024, 6, 15))

        assert exc_info.value.status_code == 429


class TestFetchPricesNetworkErrors:
    """Testy obsługi błędów sieciowych."""

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self, client, mock_session):
        """Timeout rzuca RCEApiTimeoutError."""

        async def raise_timeout(*args, **kwargs):
            raise aiohttp.ServerTimeoutError("Connection timed out")

        # Użyj context managera który rzuca wyjątek
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ServerTimeoutError("timeout"))
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)

        with pytest.raises(RCEApiTimeoutError):
            await client.fetch_prices(date(2024, 6, 15))

    @pytest.mark.asyncio
    async def test_connection_error_raises_connection_error(self, client, mock_session):
        """Błąd połączenia rzuca RCEApiConnectionError."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)

        with pytest.raises(RCEApiConnectionError):
            await client.fetch_prices(date(2024, 6, 15))


class TestParseResponse:
    """Testy parsowania odpowiedzi API."""

    @pytest.mark.asyncio
    async def test_empty_response(self, client, mock_session):
        """Pusta odpowiedź zwraca pustą listę."""
        fake_resp = FakeResponse(status=200, json_data={"value": []})
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))
        assert prices == []

    @pytest.mark.asyncio
    async def test_missing_value_field(self, client, mock_session):
        """Brak pola 'value' zwraca pustą listę."""
        fake_resp = FakeResponse(status=200, json_data={})
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))
        assert prices == []

    @pytest.mark.asyncio
    async def test_invalid_records_skipped(self, client, mock_session):
        """Nieprawidłowe rekordy są pomijane."""
        response_data = {
            "value": [
                {"rce_pln": 200.0, "business_date": "2024-06-15", "udtczas": "1"},
                {"rce_pln": None, "business_date": "2024-06-15", "udtczas": "2"},  # brak ceny
                {"business_date": "2024-06-15", "udtczas": "3"},  # brak rce_pln
                {"rce_pln": 400.0, "business_date": "2024-06-15", "udtczas": "abc"},  # zły hour
                {"rce_pln": 500.0, "business_date": "2024-06-15", "udtczas": "5"},  # OK
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        # Tylko rekordy z godzinami 1 i 5 powinny przejść
        assert len(prices) == 2
        assert prices[0].hour == 0  # udtczas=1 -> hour=0
        assert prices[1].hour == 4  # udtczas=5 -> hour=4

    @pytest.mark.asyncio
    async def test_hour_out_of_range_skipped(self, client, mock_session):
        """Godziny spoza zakresu 1-24 są pomijane."""
        response_data = {
            "value": [
                {"rce_pln": 200.0, "business_date": "2024-06-15", "udtczas": "0"},  # za mała
                {"rce_pln": 200.0, "business_date": "2024-06-15", "udtczas": "25"},  # za duża
                {"rce_pln": 200.0, "business_date": "2024-06-15", "udtczas": "1"},  # OK
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        assert len(prices) == 1
        assert prices[0].hour == 0

    @pytest.mark.asyncio
    async def test_list_response_format(self, client, mock_session):
        """API zwracające listę zamiast dict z 'value' jest obsługiwane."""
        response_data = [
            {"rce_pln": 300.0, "business_date": "2024-06-15", "udtczas": "12"},
        ]
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        assert len(prices) == 1
        assert prices[0].hour == 11

    @pytest.mark.asyncio
    async def test_decimal_precision(self, client, mock_session):
        """Sprawdź precyzję konwersji Decimal."""
        response_data = {
            "value": [
                {"rce_pln": 123.45, "business_date": "2024-06-15", "udtczas": "1"},
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        prices = await client.fetch_prices(date(2024, 6, 15))

        assert prices[0].price_pln_mwh == Decimal("123.45")
        # 123.45 / 1000 = 0.12345 -> quantized to 0.123450
        assert prices[0].price_pln_kwh == Decimal("0.123450")
