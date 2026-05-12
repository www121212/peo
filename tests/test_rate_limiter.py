"""Testy jednostkowe dla RateLimiter."""

import time
from unittest.mock import patch

import pytest

from custom_components.peo.rate_limiter import RateLimiter


class TestRateLimiterAcquire:
    """Testy metody acquire."""

    def test_acquire_returns_true_when_under_limit(self):
        """acquire() zwraca True gdy limit nie jest osiągnięty."""
        limiter = RateLimiter()
        assert limiter.acquire("test_endpoint") is True

    def test_acquire_tracks_per_endpoint(self):
        """Żądania są śledzone niezależnie per endpoint."""
        limiter = RateLimiter()

        for _ in range(60):
            limiter.acquire("endpoint_a")

        # endpoint_b powinien nadal mieć dostępne żądania
        assert limiter.acquire("endpoint_b") is True

    def test_acquire_returns_false_at_limit(self):
        """acquire() zwraca False po osiągnięciu 60 żądań/h."""
        limiter = RateLimiter()

        for _ in range(60):
            assert limiter.acquire("test") is True

        assert limiter.acquire("test") is False

    def test_acquire_logs_warning_at_limit(self, caplog):
        """Loguje WARNING gdy limit zostanie osiągnięty."""
        limiter = RateLimiter()

        for _ in range(60):
            limiter.acquire("api/prices")

        with caplog.at_level("WARNING"):
            limiter.acquire("api/prices")

        assert "Osiągnięto limit" in caplog.text
        assert "api/prices" in caplog.text

    def test_acquire_allows_after_old_entries_expire(self):
        """acquire() pozwala na żądania po wygaśnięciu starych wpisów."""
        limiter = RateLimiter()

        # Symuluj 60 żądań sprzed ponad godziny
        old_time = time.monotonic() - 3601
        limiter._requests["test"] = [old_time] * 60

        # Powinno pozwolić na nowe żądanie (stare wygasły)
        assert limiter.acquire("test") is True


class TestRateLimiterGetRemaining:
    """Testy metody get_remaining."""

    def test_get_remaining_full_when_no_requests(self):
        """get_remaining() zwraca 60 gdy brak żądań."""
        limiter = RateLimiter()
        assert limiter.get_remaining("test") == 60

    def test_get_remaining_decreases_with_requests(self):
        """get_remaining() maleje z każdym żądaniem."""
        limiter = RateLimiter()

        for _ in range(10):
            limiter.acquire("test")

        assert limiter.get_remaining("test") == 50

    def test_get_remaining_zero_at_limit(self):
        """get_remaining() zwraca 0 po osiągnięciu limitu."""
        limiter = RateLimiter()

        for _ in range(60):
            limiter.acquire("test")

        assert limiter.get_remaining("test") == 0

    def test_get_remaining_recovers_after_expiry(self):
        """get_remaining() odzyskuje po wygaśnięciu starych wpisów."""
        limiter = RateLimiter()

        # Symuluj żądania sprzed ponad godziny
        old_time = time.monotonic() - 3601
        limiter._requests["test"] = [old_time] * 30

        assert limiter.get_remaining("test") == 60

    def test_get_remaining_independent_per_endpoint(self):
        """get_remaining() jest niezależne per endpoint."""
        limiter = RateLimiter()

        for _ in range(20):
            limiter.acquire("endpoint_a")

        assert limiter.get_remaining("endpoint_a") == 40
        assert limiter.get_remaining("endpoint_b") == 60


class TestRateLimiterCleanup:
    """Testy mechanizmu czyszczenia starych wpisów."""

    def test_cleanup_removes_old_entries(self):
        """Stare wpisy (>1h) są usuwane przy kolejnym wywołaniu."""
        limiter = RateLimiter()

        # Dodaj mix starych i nowych wpisów
        now = time.monotonic()
        limiter._requests["test"] = [
            now - 3700,  # stary (>1h)
            now - 3601,  # stary (>1h)
            now - 100,   # nowy
            now - 50,    # nowy
        ]

        # Wywołanie acquire wymusi cleanup
        limiter.acquire("test")

        # 2 nowe + 1 z acquire = 3
        assert len(limiter._requests["test"]) == 3

    def test_mixed_old_and_new_entries(self):
        """get_remaining() poprawnie liczy tylko aktualne wpisy."""
        limiter = RateLimiter()

        now = time.monotonic()
        # 55 starych + 5 nowych
        limiter._requests["test"] = (
            [now - 3700] * 55 + [now - 10] * 5
        )

        # Po cleanup powinno zostać 5 aktualnych
        assert limiter.get_remaining("test") == 55
