"""Klient HTTP do API PSE RCE — pobieranie cen energii z Rynku Dnia Następnego."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import aiohttp

from .const import HTTP_TIMEOUT
from .models import HourlyPrice
from .rate_limiter import RateLimiter

_LOGGER = logging.getLogger(__name__)

# Endpoint API RCE PSE
RCE_API_URL = "https://api.raporty.pse.pl/api/rce-pln"

# Identyfikator endpointu dla rate limitera
RCE_ENDPOINT = "rce-pln"

# Przelicznik PLN/MWh -> PLN/kWh
_MWH_TO_KWH_DIVISOR = Decimal("1000")


class RCEApiError(Exception):
    """Bazowy wyjątek dla błędów klienta RCE API."""


class RCEApiConnectionError(RCEApiError):
    """Błąd połączenia z API RCE PSE."""


class RCEApiTimeoutError(RCEApiError):
    """Przekroczono limit czasu żądania do API RCE PSE."""


class RCEApiResponseError(RCEApiError):
    """Błąd odpowiedzi HTTP z API RCE PSE (4xx, 5xx)."""

    def __init__(self, status_code: int, message: str) -> None:
        """Inicjalizacja z kodem statusu HTTP."""
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class RCEApiRateLimitError(RCEApiError):
    """Osiągnięto limit częstotliwości wywołań API."""


class RCEApiClient:
    """Klient HTTP do API PSE RCE.

    Pobiera ceny energii z Rynku Dnia Następnego (RDN) publikowane przez PSE.
    Integruje RateLimiter do kontroli częstotliwości wywołań.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rate_limiter: RateLimiter,
    ) -> None:
        """Inicjalizacja klienta RCE API.

        Args:
            session: Sesja aiohttp (zarządzana przez Home Assistant).
            rate_limiter: Instancja RateLimiter do kontroli częstotliwości.
        """
        self._session = session
        self._rate_limiter = rate_limiter

    async def fetch_prices(self, target_date: date) -> list[HourlyPrice]:
        """Pobierz ceny energii na podany dzień z API RCE PSE.

        Args:
            target_date: Data, dla której pobieramy ceny.

        Returns:
            Lista 24 obiektów HourlyPrice (po jednym na każdą godzinę doby).

        Raises:
            RCEApiRateLimitError: Osiągnięto limit wywołań API.
            RCEApiTimeoutError: Przekroczono 30s timeout.
            RCEApiConnectionError: Błąd połączenia z API.
            RCEApiResponseError: Kod błędu HTTP (4xx, 5xx).
        """
        # Sprawdź rate limiter przed wykonaniem żądania
        if not self._rate_limiter.acquire(RCE_ENDPOINT):
            _LOGGER.warning(
                "Osiągnięto limit wywołań API RCE PSE. "
                "Żądanie wstrzymane do początku następnej godziny."
            )
            raise RCEApiRateLimitError(
                "Osiągnięto limit wywołań API RCE PSE (60/h)."
            )

        date_str = target_date.isoformat()
        params = {"$filter": f"business_date eq '{date_str}'"}

        _LOGGER.debug(
            "Pobieranie cen RCE PSE na dzień %s z URL: %s",
            date_str,
            RCE_API_URL,
        )

        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        try:
            async with self._session.get(
                RCE_API_URL, params=params, timeout=timeout
            ) as response:
                if response.status >= 500:
                    text = await response.text()
                    _LOGGER.warning(
                        "Błąd serwera API RCE PSE: HTTP %d — %s",
                        response.status,
                        text[:200],
                    )
                    raise RCEApiResponseError(
                        response.status,
                        f"Błąd serwera API RCE PSE: {text[:200]}",
                    )

                if response.status >= 400:
                    text = await response.text()
                    _LOGGER.warning(
                        "Błąd klienta API RCE PSE: HTTP %d — %s",
                        response.status,
                        text[:200],
                    )
                    raise RCEApiResponseError(
                        response.status,
                        f"Błąd żądania do API RCE PSE: {text[:200]}",
                    )

                data = await response.json()

        except aiohttp.ServerTimeoutError as err:
            _LOGGER.warning(
                "Przekroczono limit czasu (%ds) żądania do API RCE PSE.",
                HTTP_TIMEOUT,
            )
            raise RCEApiTimeoutError(
                f"Timeout {HTTP_TIMEOUT}s przy połączeniu z API RCE PSE."
            ) from err

        except (aiohttp.ClientError, OSError) as err:
            if isinstance(err, (RCEApiResponseError,)):
                raise
            _LOGGER.warning(
                "Błąd połączenia z API RCE PSE: %s", str(err)
            )
            raise RCEApiConnectionError(
                f"Nie można połączyć się z API RCE PSE: {err}"
            ) from err

        _LOGGER.debug(
            "Otrzymano odpowiedź z API RCE PSE na dzień %s.", date_str
        )

        return self._parse_response(data, target_date)

    def _parse_response(
        self, data: dict | list, target_date: date
    ) -> list[HourlyPrice]:
        """Parsuj odpowiedź JSON z API RCE PSE do listy HourlyPrice.

        API zwraca dane w formacie:
        {
            "value": [
                {"rce_pln": 250.50, "business_date": "2024-01-15", "udtczas": "1", ...},
                ...
            ]
        }

        Args:
            data: Odpowiedź JSON z API.
            target_date: Data żądania (do walidacji).

        Returns:
            Lista obiektów HourlyPrice posortowana wg godziny.
        """
        # API PSE zwraca dane w polu "value"
        if isinstance(data, dict):
            records = data.get("value", [])
        elif isinstance(data, list):
            records = data
        else:
            records = []

        prices: list[HourlyPrice] = []

        for record in records:
            try:
                # Pole "udtczas" zawiera numer godziny (1-24)
                hour_raw = record.get("udtczas")
                if hour_raw is None:
                    continue
                # Konwersja z 1-24 na 0-23
                hour = int(hour_raw) - 1
                if hour < 0 or hour > 23:
                    continue

                # Cena w PLN/MWh
                price_raw = record.get("rce_pln")
                if price_raw is None:
                    continue

                price_pln_mwh = Decimal(str(price_raw))

                # Przeliczenie PLN/MWh -> PLN/kWh (dzielenie przez 1000)
                price_pln_kwh = (price_pln_mwh / _MWH_TO_KWH_DIVISOR).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )

                prices.append(
                    HourlyPrice(
                        hour=hour,
                        price_pln_mwh=price_pln_mwh,
                        price_pln_kwh=price_pln_kwh,
                        date=target_date,
                    )
                )
            except (ValueError, TypeError, KeyError) as err:
                _LOGGER.debug(
                    "Pominięto nieprawidłowy rekord cenowy: %s — %s",
                    record,
                    err,
                )
                continue

        # Sortuj wg godziny
        prices.sort(key=lambda p: p.hour)

        _LOGGER.debug(
            "Sparsowano %d cen godzinowych na dzień %s.",
            len(prices),
            target_date.isoformat(),
        )

        return prices
