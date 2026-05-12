"""Ogranicznik częstotliwości wywołań API dla integracji PEO."""

import logging
import time
from collections import defaultdict

from .const import MAX_REQUESTS_PER_HOUR

_LOGGER = logging.getLogger(__name__)

# Jedna godzina w sekundach
_ONE_HOUR_SECONDS = 3600


class RateLimiter:
    """Ogranicznik częstotliwości wywołań API.

    Śledzi liczbę żądań per endpoint w oknie godzinowym.
    Limit: MAX_REQUESTS_PER_HOUR (60) żądań na godzinę na endpoint.
    """

    def __init__(self) -> None:
        """Inicjalizacja rate limitera."""
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, endpoint: str) -> None:
        """Usuń wpisy starsze niż 1 godzina dla danego endpointu."""
        now = time.monotonic()
        cutoff = now - _ONE_HOUR_SECONDS
        self._requests[endpoint] = [
            ts for ts in self._requests[endpoint] if ts > cutoff
        ]

    def acquire(self, endpoint: str) -> bool:
        """Sprawdź i zarejestruj żądanie.

        Args:
            endpoint: Identyfikator endpointu API.

        Returns:
            True jeśli żądanie zostało zarejestrowane (limit nie osiągnięty),
            False jeśli limit został osiągnięty.
        """
        self._cleanup(endpoint)

        if len(self._requests[endpoint]) >= MAX_REQUESTS_PER_HOUR:
            _LOGGER.warning(
                "Osiągnięto limit %d żądań/h dla endpointu: %s. "
                "Kolejne żądania wstrzymane do początku następnej godziny.",
                MAX_REQUESTS_PER_HOUR,
                endpoint,
            )
            return False

        self._requests[endpoint].append(time.monotonic())
        return True

    def get_remaining(self, endpoint: str) -> int:
        """Ile żądań pozostało w bieżącej godzinie dla danego endpointu.

        Args:
            endpoint: Identyfikator endpointu API.

        Returns:
            Liczba pozostałych dozwolonych żądań (0 do MAX_REQUESTS_PER_HOUR).
        """
        self._cleanup(endpoint)
        used = len(self._requests[endpoint])
        return max(0, MAX_REQUESTS_PER_HOUR - used)
