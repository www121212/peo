"""Klient prognoz solarnych (multi-provider) dla integracji PEO.

Obsługuje dostawców: Solcast, Forecast.Solar, OpenWeatherMap Solar.
Pobiera 24h prognozę PV co 60 minut z integracją RateLimiter.
Wykrywa nieaktualność prognozy (>180 min bez aktualizacji).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from .const import HTTP_TIMEOUT, PV_FORECAST_STALE_MINUTES
from .enums import SolarProvider
from .models import HourlyPVForecast
from .rate_limiter import RateLimiter

_LOGGER = logging.getLogger(__name__)

# Endpoint identifiers for rate limiter
SOLCAST_ENDPOINT = "solcast_forecast"
FORECAST_SOLAR_ENDPOINT = "forecast_solar"
OPENWEATHERMAP_SOLAR_ENDPOINT = "openweathermap_solar"

# Stale threshold in seconds
_STALE_THRESHOLD_SECONDS = PV_FORECAST_STALE_MINUTES * 60


class SolarForecastError(Exception):
    """Bazowy wyjątek dla błędów prognozy solarnej."""

    def __init__(self, message: str, provider: Optional[SolarProvider] = None) -> None:
        self.provider = provider
        super().__init__(message)


class SolarForecastTimeoutError(SolarForecastError):
    """Wyjątek timeout przy pobieraniu prognozy solarnej."""


class SolarForecastRateLimitError(SolarForecastError):
    """Wyjątek przekroczenia limitu żądań API prognozy solarnej."""


@dataclass
class SolarProviderConfig:
    """Konfiguracja dostawcy prognozy solarnej."""

    provider: SolarProvider
    api_key: str
    latitude: float
    longitude: float
    # Solcast-specific
    site_id: Optional[str] = None
    # Forecast.Solar-specific
    declination: Optional[int] = None  # degrees
    azimuth: Optional[int] = None  # degrees
    kwp: Optional[float] = None  # kWp capacity
    # OpenWeatherMap-specific (uses lat/lon + api_key)


class SolarForecastClient:
    """Klient prognoz solarnych z obsługą wielu dostawców.

    Pobiera 24h prognozę produkcji PV z wybranego dostawcy.
    Integruje RateLimiter do kontroli częstotliwości żądań.
    Wykrywa nieaktualność prognozy (>180 min bez sukcesu).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rate_limiter: RateLimiter,
        config: SolarProviderConfig,
    ) -> None:
        """Inicjalizacja klienta prognoz solarnych.

        Args:
            session: Sesja aiohttp do wykonywania żądań HTTP.
            rate_limiter: Instancja RateLimiter do kontroli częstotliwości.
            config: Konfiguracja dostawcy prognozy.
        """
        self._session = session
        self._rate_limiter = rate_limiter
        self._config = config
        self._last_successful_fetch: Optional[float] = None
        self._last_forecast: Optional[list[HourlyPVForecast]] = None

    @property
    def last_successful_fetch(self) -> Optional[datetime]:
        """Zwróć timestamp ostatniego udanego pobrania prognozy."""
        if self._last_successful_fetch is None:
            return None
        return datetime.fromtimestamp(self._last_successful_fetch, tz=timezone.utc)

    @property
    def last_forecast(self) -> Optional[list[HourlyPVForecast]]:
        """Zwróć ostatnio pobraną prognozę (cache)."""
        return self._last_forecast

    def is_forecast_stale(self) -> bool:
        """Sprawdź czy prognoza jest nieaktualna (>180 min od ostatniego sukcesu).

        Returns:
            True jeśli prognoza jest nieaktualna lub nigdy nie została pobrana.
        """
        if self._last_successful_fetch is None:
            return True
        elapsed = time.monotonic() - self._last_successful_fetch
        return elapsed > _STALE_THRESHOLD_SECONDS

    async def fetch_forecast(
        self, provider: Optional[SolarProvider] = None
    ) -> list[HourlyPVForecast]:
        """Pobierz 24h prognozę PV z dostawcy.

        Jeśli dostawca jest niedostępny >180 min, zwraca ostatnią prognozę
        ze statusem "prognoza nieaktualna".

        Args:
            provider: Dostawca prognozy (domyślnie z konfiguracji).

        Returns:
            Lista obiektów HourlyPVForecast (do 24 elementów).

        Raises:
            SolarForecastRateLimitError: Gdy limit żądań został osiągnięty.
            SolarForecastTimeoutError: Gdy żądanie przekroczyło timeout.
            SolarForecastError: Gdy wystąpił inny błąd.
        """
        active_provider = provider or self._config.provider
        endpoint = self._get_endpoint_name(active_provider)

        # Check rate limiter
        if not self._rate_limiter.acquire(endpoint):
            raise SolarForecastRateLimitError(
                f"Osiągnięto limit żądań dla dostawcy: {active_provider.value}",
                provider=active_provider,
            )

        try:
            forecast = await self._fetch_from_provider(active_provider)
            self._last_successful_fetch = time.monotonic()
            self._last_forecast = forecast
            return forecast
        except SolarForecastError:
            # Re-raise forecast errors (timeout, rate limit, etc.)
            raise
        except aiohttp.ServerTimeoutError as err:
            raise SolarForecastTimeoutError(
                f"Timeout przy pobieraniu prognozy z {active_provider.value}: {err}",
                provider=active_provider,
            ) from err
        except (aiohttp.ClientError, OSError) as err:
            _LOGGER.warning(
                "Błąd połączenia z dostawcą %s: %s",
                active_provider.value,
                err,
            )
            raise SolarForecastError(
                f"Błąd połączenia z dostawcą {active_provider.value}: {err}",
                provider=active_provider,
            ) from err

    async def fetch_forecast_with_fallback(
        self, provider: Optional[SolarProvider] = None
    ) -> tuple[list[HourlyPVForecast], bool]:
        """Pobierz prognozę z fallbackiem do ostatniej prognozy.

        Jeśli pobranie się nie powiedzie i prognoza jest nieaktualna (>180 min),
        zwraca ostatnią prognozę ze statusem stale=True.

        Args:
            provider: Dostawca prognozy (domyślnie z konfiguracji).

        Returns:
            Tuple (forecast, is_stale): lista prognoz i flaga nieaktualności.

        Raises:
            SolarForecastError: Gdy brak danych (nigdy nie pobrano prognozy).
        """
        try:
            forecast = await self.fetch_forecast(provider)
            return forecast, False
        except SolarForecastError as err:
            _LOGGER.warning(
                "Nie udało się pobrać prognozy PV: %s. Sprawdzam fallback.",
                err,
            )
            if self._last_forecast is not None:
                is_stale = self.is_forecast_stale()
                if is_stale:
                    _LOGGER.warning(
                        "Prognoza PV nieaktualna (>%d min bez aktualizacji). "
                        "Status: prognoza nieaktualna.",
                        PV_FORECAST_STALE_MINUTES,
                    )
                return self._last_forecast, is_stale
            raise SolarForecastError(
                "Brak dostępnej prognozy PV — nigdy nie pobrano danych.",
                provider=provider or self._config.provider,
            ) from err

    async def _fetch_from_provider(
        self, provider: SolarProvider
    ) -> list[HourlyPVForecast]:
        """Pobierz prognozę z konkretnego dostawcy.

        Args:
            provider: Dostawca prognozy.

        Returns:
            Lista obiektów HourlyPVForecast.
        """
        if provider == SolarProvider.SOLCAST:
            return await self._fetch_solcast()
        elif provider == SolarProvider.FORECAST_SOLAR:
            return await self._fetch_forecast_solar()
        elif provider == SolarProvider.OPENWEATHERMAP:
            return await self._fetch_openweathermap()
        else:
            raise SolarForecastError(
                f"Nieobsługiwany dostawca prognozy: {provider}",
                provider=provider,
            )

    async def _fetch_solcast(self) -> list[HourlyPVForecast]:
        """Pobierz prognozę z Solcast API.

        Endpoint: https://api.solcast.com.au/rooftop_sites/{site_id}/forecasts
        """
        if not self._config.site_id:
            raise SolarForecastError(
                "Brak site_id w konfiguracji Solcast.",
                provider=SolarProvider.SOLCAST,
            )

        url = (
            f"https://api.solcast.com.au/rooftop_sites/"
            f"{self._config.site_id}/forecasts"
        )
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Accept": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        async with self._session.get(
            url, headers=headers, timeout=timeout
        ) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.warning(
                    "Solcast API zwróciło kod %d: %s", response.status, text
                )
                raise SolarForecastError(
                    f"Solcast API HTTP {response.status}: {text}",
                    provider=SolarProvider.SOLCAST,
                )
            data = await response.json()

        return self._parse_solcast_response(data)

    def _parse_solcast_response(self, data: dict) -> list[HourlyPVForecast]:
        """Parsuj odpowiedź Solcast do listy HourlyPVForecast."""
        forecasts: list[HourlyPVForecast] = []
        raw_forecasts = data.get("forecasts", [])

        for entry in raw_forecasts:
            try:
                period_end_str = entry.get("period_end", "")
                pv_estimate = float(entry.get("pv_estimate", 0))

                # Parse ISO timestamp
                period_end = datetime.fromisoformat(
                    period_end_str.replace("Z", "+00:00")
                )

                hour = period_end.hour
                forecasts.append(
                    HourlyPVForecast(
                        hour=hour,
                        timestamp=period_end,
                        production_kwh=pv_estimate,
                    )
                )
            except (ValueError, TypeError, KeyError) as err:
                _LOGGER.debug("Pominięto wpis Solcast: %s", err)
                continue

        # Aggregate by hour (Solcast returns 30-min intervals)
        # Limit to 24 hours
        aggregated = self._aggregate_by_hour(forecasts)
        return aggregated[:24]

    async def _fetch_forecast_solar(self) -> list[HourlyPVForecast]:
        """Pobierz prognozę z Forecast.Solar API.

        Endpoint: https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}
        """
        lat = self._config.latitude
        lon = self._config.longitude
        dec = self._config.declination or 30
        az = self._config.azimuth or 0
        kwp = self._config.kwp or 5.0

        url = f"https://api.forecast.solar/estimate/{lat}/{lon}/{dec}/{az}/{kwp}"
        headers = {}
        if self._config.api_key:
            headers["X-Api-Key"] = self._config.api_key

        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        async with self._session.get(
            url, headers=headers, timeout=timeout
        ) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.warning(
                    "Forecast.Solar API zwróciło kod %d: %s", response.status, text
                )
                raise SolarForecastError(
                    f"Forecast.Solar API HTTP {response.status}: {text}",
                    provider=SolarProvider.FORECAST_SOLAR,
                )
            data = await response.json()

        return self._parse_forecast_solar_response(data)

    def _parse_forecast_solar_response(self, data: dict) -> list[HourlyPVForecast]:
        """Parsuj odpowiedź Forecast.Solar do listy HourlyPVForecast."""
        forecasts: list[HourlyPVForecast] = []
        result = data.get("result", {})
        # watt_hours_period contains hourly production
        watt_hours = result.get("watt_hours_period", {})

        for timestamp_str, wh_value in watt_hours.items():
            try:
                ts = datetime.fromisoformat(timestamp_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                hour = ts.hour
                production_kwh = float(wh_value) / 1000.0  # Wh -> kWh

                forecasts.append(
                    HourlyPVForecast(
                        hour=hour,
                        timestamp=ts,
                        production_kwh=production_kwh,
                    )
                )
            except (ValueError, TypeError) as err:
                _LOGGER.debug("Pominięto wpis Forecast.Solar: %s", err)
                continue

        # Return only next 24h, sorted by hour
        return sorted(forecasts[:24], key=lambda f: f.hour)

    async def _fetch_openweathermap(self) -> list[HourlyPVForecast]:
        """Pobierz prognozę z OpenWeatherMap Solar API.

        Endpoint: https://api.openweathermap.org/energy/1.0/solar/data
        """
        url = "https://api.openweathermap.org/energy/1.0/solar/data"
        params = {
            "lat": str(self._config.latitude),
            "lon": str(self._config.longitude),
            "appid": self._config.api_key,
        }
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        async with self._session.get(
            url, params=params, timeout=timeout
        ) as response:
            if response.status != 200:
                text = await response.text()
                _LOGGER.warning(
                    "OpenWeatherMap Solar API zwróciło kod %d: %s",
                    response.status,
                    text,
                )
                raise SolarForecastError(
                    f"OpenWeatherMap Solar API HTTP {response.status}: {text}",
                    provider=SolarProvider.OPENWEATHERMAP,
                )
            data = await response.json()

        return self._parse_openweathermap_response(data)

    def _parse_openweathermap_response(self, data: dict) -> list[HourlyPVForecast]:
        """Parsuj odpowiedź OpenWeatherMap Solar do listy HourlyPVForecast."""
        forecasts: list[HourlyPVForecast] = []
        irradiance_data = data.get("irradiance", {})
        hourly_data = irradiance_data.get("hourly", [])

        for entry in hourly_data:
            try:
                dt_value = entry.get("dt", 0)
                # GHI (Global Horizontal Irradiance) in W/m²
                clear_sky = entry.get("clear_sky", {})
                ghi = float(clear_sky.get("ghi", 0))

                ts = datetime.fromtimestamp(dt_value, tz=timezone.utc)
                hour = ts.hour

                # Estimate production: GHI * panel_area_factor * efficiency
                # Simplified: use kwp config as scaling factor
                kwp = self._config.kwp or 5.0
                # Rough estimate: GHI W/m² * kwp * 0.001 (to kWh per hour)
                production_kwh = ghi * kwp * 0.001

                forecasts.append(
                    HourlyPVForecast(
                        hour=hour,
                        timestamp=ts,
                        production_kwh=production_kwh,
                    )
                )
            except (ValueError, TypeError, KeyError) as err:
                _LOGGER.debug("Pominięto wpis OpenWeatherMap: %s", err)
                continue

        return sorted(forecasts[:24], key=lambda f: f.hour)

    def _aggregate_by_hour(
        self, forecasts: list[HourlyPVForecast]
    ) -> list[HourlyPVForecast]:
        """Agreguj prognozy sub-godzinowe do godzinowych.

        Sumuje produkcję dla wpisów z tą samą godziną.
        """
        hourly: dict[int, tuple[datetime, float]] = {}

        for f in forecasts:
            if f.hour in hourly:
                existing_ts, existing_prod = hourly[f.hour]
                hourly[f.hour] = (existing_ts, existing_prod + f.production_kwh)
            else:
                hourly[f.hour] = (f.timestamp, f.production_kwh)

        result = []
        for hour in sorted(hourly.keys()):
            ts, prod = hourly[hour]
            result.append(
                HourlyPVForecast(
                    hour=hour,
                    timestamp=ts,
                    production_kwh=prod,
                )
            )

        return result

    @staticmethod
    def _get_endpoint_name(provider: SolarProvider) -> str:
        """Zwróć nazwę endpointu dla rate limitera."""
        if provider == SolarProvider.SOLCAST:
            return SOLCAST_ENDPOINT
        elif provider == SolarProvider.FORECAST_SOLAR:
            return FORECAST_SOLAR_ENDPOINT
        elif provider == SolarProvider.OPENWEATHERMAP:
            return OPENWEATHERMAP_SOLAR_ENDPOINT
        return f"solar_{provider.value}"
