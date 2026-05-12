"""Property-based tests for RateLimiter.

**Validates: Requirements 9.8**

Property 23: Rate limiting — 60 żądań/h per endpoint
Dla dowolnej sekwencji żądań do tego samego endpointu, po osiągnięciu 60 żądań
w ciągu godziny, kolejne żądania powinny być wstrzymane do początku następnej godziny.
"""

from unittest.mock import patch

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    text,
    lists,
    floats,
    composite,
    sampled_from,
)

from custom_components.peo.const import MAX_REQUESTS_PER_HOUR
from custom_components.peo.rate_limiter import RateLimiter

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies ---

def endpoint_names():
    """Generate realistic endpoint names."""
    return sampled_from([
        "rce/prices",
        "solcast/forecast",
        "forecast_solar/estimate",
        "openweathermap/solar",
        "api/v1/data",
        "api/v2/prices",
        "charger/status",
        "charger/command",
    ])


@composite
def time_offsets_within_hour(draw):
    """Generate a list of monotonically increasing time offsets within a 1-hour window."""
    count = draw(integers(min_value=1, max_value=120))
    offsets = sorted([
        draw(floats(min_value=0.0, max_value=3599.0, allow_nan=False, allow_infinity=False))
        for _ in range(count)
    ])
    return offsets


@composite
def time_offsets_spanning_hours(draw):
    """Generate time offsets that span across hour boundaries."""
    count = draw(integers(min_value=2, max_value=100))
    offsets = sorted([
        draw(floats(min_value=0.0, max_value=7200.0, allow_nan=False, allow_infinity=False))
        for _ in range(count)
    ])
    return offsets


# --- Property Tests ---


class TestProperty23RateLimiting:
    """Property 23: Rate limiting — 60 żądań/h per endpoint."""

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoint=endpoint_names(),
        num_requests=integers(min_value=1, max_value=200),
    )
    def test_never_more_than_max_requests_in_hour_window(self, endpoint, num_requests):
        """For any sequence of acquire() calls, at most MAX_REQUESTS_PER_HOUR (60)
        succeed within any 1-hour window for the same endpoint.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 1000.0
        successful = 0

        # All calls happen at the same time (worst case — all within 1 hour)
        with patch("custom_components.peo.rate_limiter.time.monotonic", return_value=base_time):
            for _ in range(num_requests):
                if limiter.acquire(endpoint):
                    successful += 1

        assert successful <= MAX_REQUESTS_PER_HOUR

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoint=endpoint_names(),
        offsets=time_offsets_within_hour(),
    )
    def test_max_60_successes_within_any_hour(self, endpoint, offsets):
        """For any sequence of acquire() calls within a 1-hour window,
        at most 60 return True.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 5000.0
        successful = 0

        for offset in offsets:
            with patch(
                "custom_components.peo.rate_limiter.time.monotonic",
                return_value=base_time + offset,
            ):
                if limiter.acquire(endpoint):
                    successful += 1

        assert successful <= MAX_REQUESTS_PER_HOUR

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoint=endpoint_names(),
        num_requests=integers(min_value=1, max_value=200),
    )
    def test_get_remaining_consistent_with_acquires(self, endpoint, num_requests):
        """get_remaining() is always consistent with the number of successful acquires.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 1000.0
        successful = 0

        with patch("custom_components.peo.rate_limiter.time.monotonic", return_value=base_time):
            for _ in range(num_requests):
                if limiter.acquire(endpoint):
                    successful += 1

            remaining = limiter.get_remaining(endpoint)

        assert remaining == MAX_REQUESTS_PER_HOUR - successful
        assert remaining >= 0
        assert remaining <= MAX_REQUESTS_PER_HOUR

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoint=endpoint_names(),
        first_batch=integers(min_value=1, max_value=60),
        time_gap=floats(min_value=3601.0, max_value=7200.0, allow_nan=False, allow_infinity=False),
    )
    def test_old_entries_expire_after_one_hour(self, endpoint, first_batch, time_gap):
        """After time passes (>1 hour), old entries expire and new requests are allowed.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 1000.0

        # First batch of requests
        with patch("custom_components.peo.rate_limiter.time.monotonic", return_value=base_time):
            for _ in range(first_batch):
                limiter.acquire(endpoint)

        # After more than 1 hour, all old entries should have expired
        new_time = base_time + time_gap
        with patch("custom_components.peo.rate_limiter.time.monotonic", return_value=new_time):
            remaining = limiter.get_remaining(endpoint)
            # All old entries expired, full capacity available
            assert remaining == MAX_REQUESTS_PER_HOUR

            # Should be able to acquire again
            assert limiter.acquire(endpoint) is True

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoint=endpoint_names(),
        offsets=time_offsets_spanning_hours(),
    )
    def test_sliding_window_never_exceeds_limit(self, endpoint, offsets):
        """For any sequence of calls spanning multiple hours, no 1-hour sliding window
        contains more than 60 successful acquisitions.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 1000.0
        successful_times = []

        for offset in offsets:
            current_time = base_time + offset
            with patch(
                "custom_components.peo.rate_limiter.time.monotonic",
                return_value=current_time,
            ):
                if limiter.acquire(endpoint):
                    successful_times.append(current_time)

        # Verify: for any 1-hour window, at most 60 successes
        for t in successful_times:
            window_start = t - 3600.0
            count_in_window = sum(
                1 for st in successful_times if st > window_start and st <= t
            )
            assert count_in_window <= MAX_REQUESTS_PER_HOUR, (
                f"Found {count_in_window} successful requests in 1-hour window "
                f"ending at {t}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        endpoints=lists(endpoint_names(), min_size=2, max_size=5, unique=True),
    )
    def test_rate_limiting_independent_per_endpoint(self, endpoints):
        """Rate limiting is tracked independently per endpoint.
        Exhausting one endpoint does not affect others.

        **Validates: Requirements 9.8**
        """
        limiter = RateLimiter()
        base_time = 1000.0

        with patch("custom_components.peo.rate_limiter.time.monotonic", return_value=base_time):
            # Exhaust the first endpoint
            first_endpoint = endpoints[0]
            for _ in range(MAX_REQUESTS_PER_HOUR):
                limiter.acquire(first_endpoint)

            # First endpoint should be exhausted
            assert limiter.acquire(first_endpoint) is False
            assert limiter.get_remaining(first_endpoint) == 0

            # Other endpoints should still have full capacity
            for ep in endpoints[1:]:
                assert limiter.get_remaining(ep) == MAX_REQUESTS_PER_HOUR
                assert limiter.acquire(ep) is True
