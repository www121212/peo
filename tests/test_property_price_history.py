"""Property-based tests for price history retention — 30 days.

**Validates: Requirements 1.6**

Property 3: Retencja historii cen — 30 dni
Dla dowolnej sekwencji zapisów cen dziennych, magazyn historii powinien zawsze
przechowywać dokładnie ostatnie 30 dni danych — starsze wpisy powinny być usunięte,
a nowsze zachowane.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    dates,
    floats,
    integers,
    lists,
    sampled_from,
)

from custom_components.peo.models import HourlyPrice
from custom_components.peo.price_store import PriceHistoryStore

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

# Constants
PRICE_HISTORY_DAYS = 30
MWH_TO_KWH_DIVISOR = Decimal("1000")


# --- Helper Functions ---


def make_hourly_price(hour: int, price_mwh: Decimal, target_date: date) -> HourlyPrice:
    """Create an HourlyPrice object with proper PLN/kWh conversion."""
    price_kwh = price_mwh / MWH_TO_KWH_DIVISOR
    return HourlyPrice(
        hour=hour,
        price_pln_mwh=price_mwh,
        price_pln_kwh=price_kwh,
        date=target_date,
    )


def make_prices_for_date(target_date: date) -> list[HourlyPrice]:
    """Create a valid set of 24 hourly prices for a given date."""
    price_mwh = Decimal("250.00")
    return [make_hourly_price(h, price_mwh, target_date) for h in range(24)]


def create_store_with_data(
    initial_data: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[PriceHistoryStore, MagicMock]:
    """Create a PriceHistoryStore with mocked HA Store and optional initial data."""
    mock_hass = MagicMock()
    mock_ha_store = MagicMock()
    mock_ha_store.async_load = AsyncMock(return_value=initial_data)
    mock_ha_store.async_save = AsyncMock()

    with patch("custom_components.peo.price_store.Store", return_value=mock_ha_store):
        store = PriceHistoryStore(mock_hass)

    return store, mock_ha_store


# --- Strategies ---


@composite
def date_offsets_within_30_days(draw):
    """Generate a date offset within the last 30 days (0 to 29 days ago)."""
    offset = draw(integers(min_value=0, max_value=29))
    return date.today() - timedelta(days=offset)


@composite
def date_offsets_older_than_30_days(draw):
    """Generate a date offset older than 30 days (31 to 365 days ago)."""
    offset = draw(integers(min_value=31, max_value=365))
    return date.today() - timedelta(days=offset)


@composite
def mixed_date_sequence(draw):
    """Generate a sequence of dates — some within 30 days, some older.

    Returns a tuple of (all_dates, recent_dates, old_dates).
    """
    # Generate some recent dates (within 30 days)
    num_recent = draw(integers(min_value=1, max_value=15))
    recent_dates = []
    for _ in range(num_recent):
        d = draw(date_offsets_within_30_days())
        recent_dates.append(d)

    # Generate some old dates (older than 30 days)
    num_old = draw(integers(min_value=1, max_value=15))
    old_dates = []
    for _ in range(num_old):
        d = draw(date_offsets_older_than_30_days())
        old_dates.append(d)

    all_dates = recent_dates + old_dates
    # Deduplicate
    recent_dates = list(set(recent_dates))
    old_dates = list(set(old_dates))
    all_dates = list(set(all_dates))

    return all_dates, recent_dates, old_dates


@composite
def days_parameter(draw):
    """Generate a valid days parameter for get_history (1 to 30)."""
    return draw(integers(min_value=1, max_value=30))


@composite
def valid_price_mwh(draw):
    """Generate a valid price in PLN/MWh as Decimal."""
    value = draw(
        floats(min_value=0.0, max_value=5000.0, allow_nan=False, allow_infinity=False)
    )
    return Decimal(str(round(value, 2)))


@composite
def date_sequence_with_duplicates(draw):
    """Generate a sequence of dates where some dates appear multiple times.

    Returns (dates_with_duplicates, unique_dates).
    """
    num_unique = draw(integers(min_value=1, max_value=10))
    unique_dates = []
    for _ in range(num_unique):
        d = draw(date_offsets_within_30_days())
        unique_dates.append(d)
    unique_dates = list(set(unique_dates))

    # Create duplicates by repeating some dates
    all_dates = list(unique_dates)
    num_duplicates = draw(integers(min_value=1, max_value=5))
    for _ in range(num_duplicates):
        d = draw(sampled_from(unique_dates))
        all_dates.append(d)

    return all_dates, unique_dates


# --- Property 3 Tests ---


class TestProperty3PriceHistoryRetention:
    """Property 3: Retencja historii cen — 30 dni.

    **Validates: Requirements 1.6**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=mixed_date_sequence())
    def test_cleanup_removes_old_entries_preserves_recent(self, data):
        """For any sequence of daily price stores, after cleanup_old(),
        all entries with date >= today - 30 days are present and
        all entries with date < today - 30 days are removed.

        **Validates: Requirements 1.6**
        """
        all_dates, recent_dates, old_dates = data
        assume(len(recent_dates) > 0 and len(old_dates) > 0)

        import asyncio

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store prices for all dates
            for d in all_dates:
                await store.store(d, make_prices_for_date(d))

            # Run cleanup
            await store.cleanup_old()

            # Verify via get_history (with full 30-day window)
            history = await store.get_history(days=PRICE_HISTORY_DAYS)

            # All recent dates should be present
            for d in recent_dates:
                assert d in history, (
                    f"Recent date {d} should be in history after cleanup"
                )

            # No old dates should be present
            for d in old_dates:
                assert d not in history, (
                    f"Old date {d} should NOT be in history after cleanup"
                )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(data=mixed_date_sequence())
    def test_count_never_exceeds_30_after_cleanup(self, data):
        """After cleanup_old(), the total count of entries never exceeds 30.

        **Validates: Requirements 1.6**
        """
        all_dates, recent_dates, old_dates = data

        import asyncio

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store prices for all dates
            for d in all_dates:
                await store.store(d, make_prices_for_date(d))

            # Run cleanup
            await store.cleanup_old()

            # Get internal data after cleanup
            internal_data = await store._async_load()

            # Count should never exceed 30
            assert len(internal_data) <= PRICE_HISTORY_DAYS, (
                f"After cleanup, store has {len(internal_data)} entries, "
                f"expected at most {PRICE_HISTORY_DAYS}"
            )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(days=days_parameter(), data=mixed_date_sequence())
    def test_get_history_returns_entries_within_n_days(self, days, data):
        """get_history(days=N) returns exactly entries within the last N days.

        **Validates: Requirements 1.6**
        """
        all_dates, _, _ = data

        import asyncio

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store prices for all dates
            for d in all_dates:
                await store.store(d, make_prices_for_date(d))

            # Get history with specific days parameter
            history = await store.get_history(days=days)

            cutoff = date.today() - timedelta(days=days)

            # All returned entries should be within the window
            for entry_date in history.keys():
                assert entry_date >= cutoff, (
                    f"Date {entry_date} is older than cutoff {cutoff} "
                    f"but was returned by get_history(days={days})"
                )

            # All stored dates within the window should be returned
            unique_dates = set(all_dates)
            for d in unique_dates:
                if d >= cutoff:
                    assert d in history, (
                        f"Date {d} is within {days}-day window "
                        f"(cutoff={cutoff}) but was not returned"
                    )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(data=date_sequence_with_duplicates())
    def test_storing_existing_date_overwrites_no_duplicates(self, data):
        """Storing new data for an existing date overwrites it — no duplicates.

        **Validates: Requirements 1.6**
        """
        all_dates, unique_dates = data
        assume(len(unique_dates) > 0)

        import asyncio

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store prices for all dates (including duplicates)
            for d in all_dates:
                await store.store(d, make_prices_for_date(d))

            # Get internal data
            internal_data = await store._async_load()

            # Number of entries should equal number of unique dates
            assert len(internal_data) == len(unique_dates), (
                f"Store has {len(internal_data)} entries but expected "
                f"{len(unique_dates)} unique dates (no duplicates)"
            )

            # Each unique date should appear exactly once
            for d in unique_dates:
                assert d.isoformat() in internal_data, (
                    f"Date {d} should be in store"
                )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(
        num_recent=integers(min_value=0, max_value=30),
        num_old=integers(min_value=0, max_value=30),
    )
    def test_cleanup_preserves_exactly_recent_entries(self, num_recent, num_old):
        """After cleanup, the store contains exactly the recent entries
        (those within 30 days) and none of the old ones.

        **Validates: Requirements 1.6**
        """
        import asyncio

        # Generate deterministic dates to avoid duplicates
        recent_dates = [
            date.today() - timedelta(days=i) for i in range(num_recent)
        ]
        old_dates = [
            date.today() - timedelta(days=31 + i) for i in range(num_old)
        ]

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store all dates
            for d in recent_dates + old_dates:
                await store.store(d, make_prices_for_date(d))

            # Run cleanup
            await store.cleanup_old()

            # Get internal data
            internal_data = await store._async_load()

            # Verify exact count of recent entries
            assert len(internal_data) == num_recent, (
                f"After cleanup, expected {num_recent} entries, "
                f"got {len(internal_data)}"
            )

            # Verify all recent dates are present
            for d in recent_dates:
                assert d.isoformat() in internal_data

            # Verify no old dates remain
            for d in old_dates:
                assert d.isoformat() not in internal_data

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(price_mwh=valid_price_mwh())
    def test_store_overwrite_preserves_latest_value(self, price_mwh):
        """When storing prices for the same date twice, the latest value
        is preserved (overwrite semantics).

        **Validates: Requirements 1.6**
        """
        import asyncio

        target_date = date.today()

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            # Store initial prices
            initial_prices = make_prices_for_date(target_date)
            await store.store(target_date, initial_prices)

            # Store new prices with different value
            new_prices = [
                make_hourly_price(h, price_mwh, target_date) for h in range(24)
            ]
            await store.store(target_date, new_prices)

            # Retrieve and verify latest value is stored
            history = await store.get_history(days=1)
            assert target_date in history

            for hp in history[target_date]:
                assert hp.price_pln_mwh == price_mwh, (
                    f"Expected price {price_mwh}, got {hp.price_pln_mwh}. "
                    f"Overwrite should preserve latest value."
                )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(num_days=integers(min_value=1, max_value=30))
    def test_boundary_date_exactly_at_cutoff_is_kept(self, num_days):
        """A date exactly at the cutoff boundary (today - N days) is kept
        by get_history(days=N).

        **Validates: Requirements 1.6**
        """
        import asyncio

        boundary_date = date.today() - timedelta(days=num_days)

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            await store.store(boundary_date, make_prices_for_date(boundary_date))

            history = await store.get_history(days=num_days)

            # The boundary date should be included (>= cutoff)
            assert boundary_date in history, (
                f"Boundary date {boundary_date} (exactly {num_days} days ago) "
                f"should be included in get_history(days={num_days})"
            )

        asyncio.run(run_test())

    @PROPERTY_TEST_SETTINGS
    @given(num_days=integers(min_value=1, max_value=30))
    def test_date_one_day_past_cutoff_is_excluded(self, num_days):
        """A date one day past the cutoff (today - N - 1 days) is excluded
        by get_history(days=N).

        **Validates: Requirements 1.6**
        """
        import asyncio

        past_cutoff_date = date.today() - timedelta(days=num_days + 1)

        async def run_test():
            store, mock_ha_store = create_store_with_data()

            await store.store(past_cutoff_date, make_prices_for_date(past_cutoff_date))

            history = await store.get_history(days=num_days)

            # The date past cutoff should NOT be included
            assert past_cutoff_date not in history, (
                f"Date {past_cutoff_date} ({num_days + 1} days ago) "
                f"should NOT be in get_history(days={num_days})"
            )

        asyncio.run(run_test())
