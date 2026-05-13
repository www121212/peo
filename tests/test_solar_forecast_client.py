"""Testy jednostkowe dla klienta prognoz solarnych (SolarForecastClient)."""

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import aiohttp

from custom_components.peo.solar_forecast_client import (
    SolarForecastClient,
    SolarForecastError,
    SolarForecastRateLimitError,
    SolarForecastTimeoutError,
    SolarProviderConfig,
    SOLCAST_ENDPOINT,
    FORECAST_SOLAR_ENDPOINT,
    OPENWEATHERMAP_SOLAR_ENDPOINT,
    _STALE_THRESHOLD_SECONDS,
)
from custom_components.peo.enums import SolarProvider
from custom_components.peo.rate_limiter import RateLimiter
from custom_components.peo.models import HourlyPVForecast


class FakeResponse:
    """Fałszywa odpowiedź HTTP do testów."""

    def __init__(self, status: int, json_data=None, text: str = ""):
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
def solcast_config():
    """Fixture: konfiguracja Solcast."""
    return SolarProviderConfig(
        provider=SolarProvider.SOLCAST,
        api_key="test-solcast-key",
        latitude=50.06,
        longitude=19.94,
        site_id="test-site-123",
    )


@pytest.fixture
def forecast_solar_config():
    """Fixture: konfiguracja Forecast.Solar."""
    return SolarProviderConfig(
        provider=SolarProvider.FORECAST_SOLAR,
        api_key="test-fs-key",
        latitude=50.06,
        longitude=19.94,
        declination=35,
        azimuth=0,
        kwp=10.0,
    )


@pytest.fixture
def owm_config():
    """Fixture: konfiguracja OpenWeatherMap Solar."""
    return SolarProviderConfig(
        provider=SolarProvider.OPENWEATHERMAP,
        api_key="test-owm-key",
        latitude=50.06,
        longitude=19.94,
        kwp=10.0,
    )


@pytest.fixture
def solcast_client(mock_session, rate_limiter, solcast_config):
    """Fixture: klient Solcast."""
    return SolarForecastClient(
        session=mock_session,
        rate_limiter=rate_limiter,
        config=solcast_config,
    )


@pytest.fixture
def forecast_solar_client(mock_session, rate_limiter, forecast_solar_config):
    """Fixture: klient Forecast.Solar."""
    return SolarForecastClient(
        session=mock_session,
        rate_limiter=rate_limiter,
        config=forecast_solar_config,
    )


@pytest.fixture
def owm_client(mock_session, rate_limiter, owm_config):
    """Fixture: klient OpenWeatherMap Solar."""
    return SolarForecastClient(
        session=mock_session,
        rate_limiter=rate_limiter,
        config=owm_config,
    )


def _make_solcast_response(num_periods: int = 48) -> dict:
    """Generuj przykładową odpowiedź Solcast (30-min interwały)."""
    from datetime import timedelta

    forecasts = []
    base_time = datetime(2024, 6, 15, 0, 30, tzinfo=timezone.utc)
    for i in range(num_periods):
        period_end = base_time + timedelta(minutes=30 * i)
        forecasts.append(
            {
                "period_end": period_end.isoformat(),
                "pv_estimate": 0.5 + (i * 0.1),
            }
        )
    return {"forecasts": forecasts}


def _make_forecast_solar_response(num_hours: int = 24) -> dict:
    """Generuj przykładową odpowiedź Forecast.Solar."""
    watt_hours = {}
    for i in range(num_hours):
        ts = datetime(2024, 6, 15, i, 0, tzinfo=timezone.utc)
        watt_hours[ts.isoformat()] = 500 + i * 100  # Wh
    return {"result": {"watt_hours_period": watt_hours}}


def _make_owm_response(num_hours: int = 24) -> dict:
    """Generuj przykładową odpowiedź OpenWeatherMap Solar."""
    hourly = []
    base_ts = int(datetime(2024, 6, 15, 0, 0, tzinfo=timezone.utc).timestamp())
    for i in range(num_hours):
        hourly.append(
            {
                "dt": base_ts + i * 3600,
                "clear_sky": {"ghi": 200 + i * 20},
            }
        )
    return {"irradiance": {"hourly": hourly}}


class TestSolcastFetch:
    """Testy pobierania prognozy z Solcast."""

    @pytest.mark.asyncio
    async def test_fetch_solcast_success(self, solcast_client, mock_session):
        """Poprawne pobranie prognozy z Solcast."""
        response_data = _make_solcast_response(48)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecasts = await solcast_client.fetch_forecast()

        assert len(forecasts) > 0
        assert all(isinstance(f, HourlyPVForecast) for f in forecasts)
        # Forecasts should be sorted by hour
        hours = [f.hour for f in forecasts]
        assert hours == sorted(hours)

    @pytest.mark.asyncio
    async def test_fetch_solcast_aggregates_subhourly(
        self, solcast_client, mock_session
    ):
        """Solcast agreguje 30-min interwały do godzinowych."""
        # Two 30-min periods for hour 10
        base_time = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
        response_data = {
            "forecasts": [
                {
                    "period_end": base_time.replace(minute=30).isoformat(),
                    "pv_estimate": 1.5,
                },
                {
                    "period_end": base_time.replace(hour=11, minute=0).isoformat(),
                    "pv_estimate": 2.0,
                },
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecasts = await solcast_client.fetch_forecast()

        # Both entries map to hour 10 (10:30 and 11:00 are within hour 10 range)
        assert len(forecasts) >= 1

    @pytest.mark.asyncio
    async def test_fetch_solcast_missing_site_id(
        self, mock_session, rate_limiter
    ):
        """Brak site_id rzuca SolarForecastError."""
        config = SolarProviderConfig(
            provider=SolarProvider.SOLCAST,
            api_key="key",
            latitude=50.0,
            longitude=19.0,
            site_id=None,
        )
        client = SolarForecastClient(mock_session, rate_limiter, config)

        with pytest.raises(SolarForecastError, match="site_id"):
            await client.fetch_forecast()

    @pytest.mark.asyncio
    async def test_fetch_solcast_http_error(self, solcast_client, mock_session):
        """Solcast HTTP 500 rzuca SolarForecastError."""
        fake_resp = FakeResponse(status=500, text="Internal Server Error")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(SolarForecastError):
            await solcast_client.fetch_forecast()

    @pytest.mark.asyncio
    async def test_fetch_solcast_uses_auth_header(
        self, solcast_client, mock_session
    ):
        """Solcast używa nagłówka Authorization Bearer."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        call_args = mock_session.get.call_args
        headers = call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-solcast-key"


class TestForecastSolarFetch:
    """Testy pobierania prognozy z Forecast.Solar."""

    @pytest.mark.asyncio
    async def test_fetch_forecast_solar_success(
        self, forecast_solar_client, mock_session
    ):
        """Poprawne pobranie prognozy z Forecast.Solar."""
        response_data = _make_forecast_solar_response(24)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecasts = await forecast_solar_client.fetch_forecast()

        assert len(forecasts) == 24
        assert all(isinstance(f, HourlyPVForecast) for f in forecasts)
        # Check conversion from Wh to kWh
        assert forecasts[0].production_kwh == 0.5  # 500 Wh -> 0.5 kWh

    @pytest.mark.asyncio
    async def test_fetch_forecast_solar_url_format(
        self, forecast_solar_client, mock_session
    ):
        """Forecast.Solar URL zawiera parametry lokalizacji."""
        response_data = {"result": {"watt_hours_period": {}}}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await forecast_solar_client.fetch_forecast()

        call_args = mock_session.get.call_args
        url = call_args[0][0]
        assert "50.06" in url
        assert "19.94" in url
        assert "35" in url  # declination
        assert "0" in url  # azimuth
        assert "10.0" in url  # kwp

    @pytest.mark.asyncio
    async def test_fetch_forecast_solar_http_error(
        self, forecast_solar_client, mock_session
    ):
        """Forecast.Solar HTTP 429 rzuca SolarForecastError."""
        fake_resp = FakeResponse(status=429, text="Rate limit exceeded")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(SolarForecastError):
            await forecast_solar_client.fetch_forecast()


class TestOpenWeatherMapFetch:
    """Testy pobierania prognozy z OpenWeatherMap Solar."""

    @pytest.mark.asyncio
    async def test_fetch_owm_success(self, owm_client, mock_session):
        """Poprawne pobranie prognozy z OpenWeatherMap Solar."""
        response_data = _make_owm_response(24)
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecasts = await owm_client.fetch_forecast()

        assert len(forecasts) == 24
        assert all(isinstance(f, HourlyPVForecast) for f in forecasts)
        # Check production calculation: GHI * kwp * 0.001
        # First hour: 200 * 10.0 * 0.001 = 2.0 kWh
        assert forecasts[0].production_kwh == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_fetch_owm_uses_params(self, owm_client, mock_session):
        """OpenWeatherMap używa parametrów lat, lon, appid."""
        response_data = {"irradiance": {"hourly": []}}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await owm_client.fetch_forecast()

        call_args = mock_session.get.call_args
        params = call_args[1]["params"]
        assert params["lat"] == "50.06"
        assert params["lon"] == "19.94"
        assert params["appid"] == "test-owm-key"

    @pytest.mark.asyncio
    async def test_fetch_owm_http_error(self, owm_client, mock_session):
        """OpenWeatherMap HTTP 401 rzuca SolarForecastError."""
        fake_resp = FakeResponse(status=401, text="Unauthorized")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(SolarForecastError):
            await owm_client.fetch_forecast()


class TestRateLimiting:
    """Testy integracji z RateLimiter."""

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_raises_error(self, mock_session):
        """Przekroczenie limitu rzuca SolarForecastRateLimitError."""
        limiter = RateLimiter()
        config = SolarProviderConfig(
            provider=SolarProvider.SOLCAST,
            api_key="key",
            latitude=50.0,
            longitude=19.0,
            site_id="site-1",
        )
        client = SolarForecastClient(mock_session, limiter, config)

        # Exhaust rate limit
        for _ in range(60):
            limiter.acquire(SOLCAST_ENDPOINT)

        with pytest.raises(SolarForecastRateLimitError):
            await client.fetch_forecast()

        # Session should not be called
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_limiter_decrements_on_call(
        self, solcast_client, mock_session, rate_limiter
    ):
        """Rate limiter jest dekrementowany po wywołaniu."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        remaining_before = rate_limiter.get_remaining(SOLCAST_ENDPOINT)
        await solcast_client.fetch_forecast()
        remaining_after = rate_limiter.get_remaining(SOLCAST_ENDPOINT)

        assert remaining_after == remaining_before - 1

    @pytest.mark.asyncio
    async def test_different_providers_use_different_endpoints(
        self, mock_session, rate_limiter
    ):
        """Różni dostawcy używają różnych endpointów w rate limiterze."""
        config_solcast = SolarProviderConfig(
            provider=SolarProvider.SOLCAST,
            api_key="key",
            latitude=50.0,
            longitude=19.0,
            site_id="site-1",
        )
        config_fs = SolarProviderConfig(
            provider=SolarProvider.FORECAST_SOLAR,
            api_key="key",
            latitude=50.0,
            longitude=19.0,
            kwp=5.0,
        )

        client_solcast = SolarForecastClient(mock_session, rate_limiter, config_solcast)
        client_fs = SolarForecastClient(mock_session, rate_limiter, config_fs)

        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await client_solcast.fetch_forecast()

        response_data_fs = {"result": {"watt_hours_period": {}}}
        fake_resp_fs = FakeResponse(status=200, json_data=response_data_fs)
        mock_session.get = MagicMock(return_value=fake_resp_fs)

        await client_fs.fetch_forecast()

        # Each endpoint should have 59 remaining independently
        assert rate_limiter.get_remaining(SOLCAST_ENDPOINT) == 59
        assert rate_limiter.get_remaining(FORECAST_SOLAR_ENDPOINT) == 59


class TestStalenessDetection:
    """Testy wykrywania nieaktualności prognozy."""

    def test_is_stale_when_never_fetched(self, solcast_client):
        """Prognoza jest nieaktualna gdy nigdy nie pobrana."""
        assert solcast_client.is_forecast_stale() is True

    @pytest.mark.asyncio
    async def test_not_stale_after_successful_fetch(
        self, solcast_client, mock_session
    ):
        """Prognoza nie jest nieaktualna tuż po pobraniu."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        assert solcast_client.is_forecast_stale() is False

    @pytest.mark.asyncio
    async def test_stale_after_threshold(self, solcast_client, mock_session):
        """Prognoza jest nieaktualna po przekroczeniu progu 180 min."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        # Simulate time passing beyond threshold
        solcast_client._last_successful_fetch = (
            time.monotonic() - _STALE_THRESHOLD_SECONDS - 1
        )

        assert solcast_client.is_forecast_stale() is True

    @pytest.mark.asyncio
    async def test_not_stale_just_before_threshold(
        self, solcast_client, mock_session
    ):
        """Prognoza nie jest nieaktualna tuż przed progiem 180 min."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        # Simulate time just before threshold
        solcast_client._last_successful_fetch = (
            time.monotonic() - _STALE_THRESHOLD_SECONDS + 60
        )

        assert solcast_client.is_forecast_stale() is False


class TestFallbackBehavior:
    """Testy zachowania fallback przy niedostępności dostawcy."""

    @pytest.mark.asyncio
    async def test_fallback_returns_last_forecast_on_error(
        self, solcast_client, mock_session
    ):
        """Fallback zwraca ostatnią prognozę gdy dostawca niedostępny."""
        # First successful fetch
        response_data = {
            "forecasts": [
                {
                    "period_end": "2024-06-15T10:30:00+00:00",
                    "pv_estimate": 3.5,
                }
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)
        await solcast_client.fetch_forecast()

        # Second fetch fails
        fake_resp_err = FakeResponse(status=500, text="Server Error")
        mock_session.get = MagicMock(return_value=fake_resp_err)

        forecast, is_stale = await solcast_client.fetch_forecast_with_fallback()

        assert len(forecast) > 0
        assert is_stale is False  # Not stale yet (just fetched)

    @pytest.mark.asyncio
    async def test_fallback_marks_stale_after_threshold(
        self, solcast_client, mock_session
    ):
        """Fallback oznacza prognozę jako nieaktualną po >180 min."""
        # First successful fetch
        response_data = {
            "forecasts": [
                {
                    "period_end": "2024-06-15T10:30:00+00:00",
                    "pv_estimate": 3.5,
                }
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)
        await solcast_client.fetch_forecast()

        # Simulate time passing beyond threshold
        solcast_client._last_successful_fetch = (
            time.monotonic() - _STALE_THRESHOLD_SECONDS - 1
        )

        # Next fetch fails
        fake_resp_err = FakeResponse(status=500, text="Server Error")
        mock_session.get = MagicMock(return_value=fake_resp_err)

        forecast, is_stale = await solcast_client.fetch_forecast_with_fallback()

        assert len(forecast) > 0
        assert is_stale is True

    @pytest.mark.asyncio
    async def test_fallback_raises_when_no_cached_data(
        self, solcast_client, mock_session
    ):
        """Fallback rzuca wyjątek gdy brak danych w cache."""
        fake_resp_err = FakeResponse(status=500, text="Server Error")
        mock_session.get = MagicMock(return_value=fake_resp_err)

        with pytest.raises(SolarForecastError, match="nigdy nie pobrano"):
            await solcast_client.fetch_forecast_with_fallback()

    @pytest.mark.asyncio
    async def test_fallback_success_returns_fresh_data(
        self, solcast_client, mock_session
    ):
        """Fallback zwraca świeże dane gdy pobranie się powiedzie."""
        response_data = {
            "forecasts": [
                {
                    "period_end": "2024-06-15T12:00:00+00:00",
                    "pv_estimate": 5.0,
                }
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecast, is_stale = await solcast_client.fetch_forecast_with_fallback()

        assert len(forecast) > 0
        assert is_stale is False


class TestLastSuccessfulFetch:
    """Testy śledzenia ostatniego udanego pobrania."""

    def test_initial_last_fetch_is_none(self, solcast_client):
        """Początkowy timestamp ostatniego pobrania to None."""
        assert solcast_client.last_successful_fetch is None

    @pytest.mark.asyncio
    async def test_last_fetch_updated_on_success(
        self, solcast_client, mock_session
    ):
        """Timestamp aktualizowany po udanym pobraniu."""
        response_data = {"forecasts": []}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        assert solcast_client.last_successful_fetch is not None

    @pytest.mark.asyncio
    async def test_last_fetch_not_updated_on_failure(
        self, solcast_client, mock_session
    ):
        """Timestamp NIE jest aktualizowany po nieudanym pobraniu."""
        fake_resp = FakeResponse(status=500, text="Error")
        mock_session.get = MagicMock(return_value=fake_resp)

        with pytest.raises(SolarForecastError):
            await solcast_client.fetch_forecast()

        assert solcast_client.last_successful_fetch is None


class TestTimeoutHandling:
    """Testy obsługi timeout."""

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self, solcast_client, mock_session):
        """Timeout rzuca SolarForecastTimeoutError."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ServerTimeoutError("Connection timed out")
        )
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)

        with pytest.raises(SolarForecastTimeoutError):
            await solcast_client.fetch_forecast()

    @pytest.mark.asyncio
    async def test_connection_error_raises_forecast_error(
        self, solcast_client, mock_session
    ):
        """Błąd połączenia rzuca SolarForecastError."""
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(
            side_effect=aiohttp.ClientConnectorError(
                connection_key=MagicMock(), os_error=OSError("Connection refused")
            )
        )
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=cm)

        with pytest.raises(SolarForecastError):
            await solcast_client.fetch_forecast()


class TestProviderSelection:
    """Testy wyboru dostawcy."""

    @pytest.mark.asyncio
    async def test_explicit_provider_override(
        self, mock_session, rate_limiter
    ):
        """Można nadpisać dostawcę w wywołaniu fetch_forecast."""
        config = SolarProviderConfig(
            provider=SolarProvider.SOLCAST,
            api_key="key",
            latitude=50.0,
            longitude=19.0,
            site_id="site-1",
            kwp=5.0,
        )
        client = SolarForecastClient(mock_session, rate_limiter, config)

        # Override to Forecast.Solar
        response_data = {"result": {"watt_hours_period": {}}}
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        forecasts = await client.fetch_forecast(
            provider=SolarProvider.FORECAST_SOLAR
        )

        assert forecasts == []
        # Should use forecast_solar endpoint in rate limiter
        assert rate_limiter.get_remaining(FORECAST_SOLAR_ENDPOINT) == 59
        assert rate_limiter.get_remaining(SOLCAST_ENDPOINT) == 60


class TestExceptions:
    """Testy wyjątków."""

    def test_solar_forecast_error_has_provider(self):
        """SolarForecastError przechowuje informację o dostawcy."""
        err = SolarForecastError("test", provider=SolarProvider.SOLCAST)
        assert err.provider == SolarProvider.SOLCAST
        assert str(err) == "test"

    def test_solar_forecast_timeout_inherits(self):
        """SolarForecastTimeoutError dziedziczy z SolarForecastError."""
        err = SolarForecastTimeoutError("timeout", provider=SolarProvider.SOLCAST)
        assert isinstance(err, SolarForecastError)

    def test_solar_forecast_rate_limit_inherits(self):
        """SolarForecastRateLimitError dziedziczy z SolarForecastError."""
        err = SolarForecastRateLimitError("limit", provider=SolarProvider.SOLCAST)
        assert isinstance(err, SolarForecastError)


class TestCachedForecast:
    """Testy cache'owania prognozy."""

    @pytest.mark.asyncio
    async def test_last_forecast_cached(self, solcast_client, mock_session):
        """Ostatnia prognoza jest cache'owana."""
        response_data = {
            "forecasts": [
                {
                    "period_end": "2024-06-15T10:30:00+00:00",
                    "pv_estimate": 3.5,
                }
            ]
        }
        fake_resp = FakeResponse(status=200, json_data=response_data)
        mock_session.get = MagicMock(return_value=fake_resp)

        await solcast_client.fetch_forecast()

        assert solcast_client.last_forecast is not None
        assert len(solcast_client.last_forecast) > 0

    def test_initial_last_forecast_is_none(self, solcast_client):
        """Początkowy cache prognozy to None."""
        assert solcast_client.last_forecast is None
