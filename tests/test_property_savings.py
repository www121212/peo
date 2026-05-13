"""Property-based tests for savings calculation.

**Validates: Requirements 10.1, 10.2**

Property 24: Obliczanie oszczędności
Dla dowolnej decyzji optymalizacyjnej, dzienna oszczędność powinna być równa
różnicy między kosztem bez optymalizacji a kosztem rzeczywistym, a miesięczna
oszczędność powinna być sumą dziennych oszczędności w bieżącym miesiącu,
resetowaną 1. dnia miesiąca.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    decimals,
    integers,
    lists,
    datetimes,
)

from custom_components.peo.savings_calculator import SavingsCalculator

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies ---


@composite
def valid_cost(draw):
    """Generate a valid cost in PLN (0.00 to 1000.00)."""
    value = draw(
        decimals(
            min_value=Decimal("0.00"),
            max_value=Decimal("1000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return value


@composite
def optimization_decision(draw):
    """Generate a pair of (non_optimized_cost, actual_cost) where
    non_optimized >= actual (optimization reduces cost)."""
    non_optimized = draw(valid_cost())
    # actual_cost <= non_optimized_cost for positive savings
    actual = draw(
        decimals(
            min_value=Decimal("0.00"),
            max_value=non_optimized,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return non_optimized, actual


@composite
def optimization_decision_any(draw):
    """Generate any pair of (non_optimized_cost, actual_cost) — savings may be negative."""
    non_optimized = draw(valid_cost())
    actual = draw(valid_cost())
    return non_optimized, actual


@composite
def multiple_decisions_same_day(draw):
    """Generate multiple optimization decisions within the same day."""
    num_decisions = draw(integers(min_value=1, max_value=20))
    base_time = datetime(2024, 6, 15, 8, 0, 0)
    decisions = []
    for i in range(num_decisions):
        non_opt, actual = draw(optimization_decision_any())
        ts = base_time + timedelta(minutes=i * 30)
        decisions.append((non_opt, actual, ts))
    return decisions


@composite
def decisions_across_days(draw):
    """Generate decisions across multiple days within the same month."""
    num_days = draw(integers(min_value=2, max_value=10))
    decisions_per_day = []
    for day_offset in range(num_days):
        num_decisions = draw(integers(min_value=1, max_value=5))
        day_decisions = []
        for i in range(num_decisions):
            non_opt, actual = draw(optimization_decision_any())
            ts = datetime(2024, 6, 1 + day_offset, 8 + i, 0, 0)
            day_decisions.append((non_opt, actual, ts))
        decisions_per_day.append(day_decisions)
    return decisions_per_day


@composite
def decisions_across_months(draw):
    """Generate decisions across a month boundary."""
    # Decisions in month 1 (last days)
    num_m1 = draw(integers(min_value=1, max_value=5))
    m1_decisions = []
    for i in range(num_m1):
        non_opt, actual = draw(optimization_decision_any())
        ts = datetime(2024, 6, 28 + (i % 3), 10 + i, 0, 0)
        m1_decisions.append((non_opt, actual, ts))

    # Decisions in month 2 (first days)
    num_m2 = draw(integers(min_value=1, max_value=5))
    m2_decisions = []
    for i in range(num_m2):
        non_opt, actual = draw(optimization_decision_any())
        ts = datetime(2024, 7, 1 + (i % 3), 10 + i, 0, 0)
        m2_decisions.append((non_opt, actual, ts))

    return m1_decisions, m2_decisions


# --- Property 24 Tests ---


class TestProperty24SavingsCalculation:
    """Property 24: Obliczanie oszczędności.

    **Validates: Requirements 10.1, 10.2**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=optimization_decision())
    def test_daily_savings_equals_non_optimized_minus_actual(self, data):
        """Daily savings = non-optimized cost - actual cost for a single decision.

        **Validates: Requirements 10.1**
        """
        non_optimized, actual = data
        calc = SavingsCalculator()
        timestamp = datetime(2024, 6, 15, 12, 0, 0)

        saving = calc.record_optimization(non_optimized, actual, timestamp)

        expected = (non_optimized - actual).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert saving == expected, (
            f"Saving should be {expected}, got {saving}. "
            f"non_optimized={non_optimized}, actual={actual}"
        )
        assert calc.daily_savings == expected

    @PROPERTY_TEST_SETTINGS
    @given(data=optimization_decision())
    def test_savings_non_negative_when_optimization_reduces_cost(self, data):
        """When optimization reduces cost (actual <= non_optimized),
        savings are always >= 0.

        **Validates: Requirements 10.1**
        """
        non_optimized, actual = data
        assume(actual <= non_optimized)

        calc = SavingsCalculator()
        timestamp = datetime(2024, 6, 15, 12, 0, 0)

        saving = calc.record_optimization(non_optimized, actual, timestamp)

        assert saving >= Decimal("0.00"), (
            f"Savings should be >= 0 when optimization reduces cost. "
            f"Got {saving} for non_optimized={non_optimized}, actual={actual}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=multiple_decisions_same_day())
    def test_daily_savings_is_sum_of_all_decisions(self, data):
        """Daily savings is the sum of all individual decision savings within a day.

        **Validates: Requirements 10.1**
        """
        calc = SavingsCalculator()
        expected_total = Decimal("0.00")

        for non_opt, actual, ts in data:
            saving = calc.record_optimization(non_opt, actual, ts)
            expected_total += saving

        expected_rounded = expected_total.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert calc.daily_savings == expected_rounded, (
            f"Daily savings should be sum of all decisions: {expected_rounded}, "
            f"got {calc.daily_savings}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=multiple_decisions_same_day())
    def test_monthly_savings_equals_daily_within_same_day(self, data):
        """Within a single day, monthly savings equals daily savings.

        **Validates: Requirements 10.2**
        """
        calc = SavingsCalculator()

        for non_opt, actual, ts in data:
            calc.record_optimization(non_opt, actual, ts)

        assert calc.monthly_savings == calc.daily_savings, (
            f"Monthly savings ({calc.monthly_savings}) should equal "
            f"daily savings ({calc.daily_savings}) within same day"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=decisions_across_days())
    def test_monthly_savings_is_sum_across_days(self, data):
        """Monthly savings is the sum of all savings across days in the same month.

        **Validates: Requirements 10.2**
        """
        calc = SavingsCalculator()
        total_savings = Decimal("0.00")

        for day_decisions in data:
            for non_opt, actual, ts in day_decisions:
                saving = calc.record_optimization(non_opt, actual, ts)
                total_savings += saving

        expected = total_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert calc.monthly_savings == expected, (
            f"Monthly savings should be sum across all days: {expected}, "
            f"got {calc.monthly_savings}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=decisions_across_days())
    def test_daily_savings_resets_on_new_day(self, data):
        """Daily savings resets to 0 at the start of a new day.

        **Validates: Requirements 10.1**
        """
        assume(len(data) >= 2)
        calc = SavingsCalculator()

        # Process all days
        for day_decisions in data:
            for non_opt, actual, ts in day_decisions:
                calc.record_optimization(non_opt, actual, ts)

        # After processing, daily_savings should reflect only the last day
        last_day_savings = Decimal("0.00")
        for non_opt, actual, ts in data[-1]:
            saving = (non_opt - actual).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            last_day_savings += saving

        last_day_expected = last_day_savings.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert calc.daily_savings == last_day_expected, (
            f"Daily savings should reflect only last day: {last_day_expected}, "
            f"got {calc.daily_savings}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=decisions_across_months())
    def test_monthly_savings_resets_on_new_month(self, data):
        """Monthly savings resets to 0 on the 1st of a new month.

        **Validates: Requirements 10.2**
        """
        m1_decisions, m2_decisions = data
        calc = SavingsCalculator()

        # Process month 1 decisions
        for non_opt, actual, ts in m1_decisions:
            calc.record_optimization(non_opt, actual, ts)

        # Process month 2 decisions — monthly should reset
        m2_total = Decimal("0.00")
        for non_opt, actual, ts in m2_decisions:
            saving = calc.record_optimization(non_opt, actual, ts)
            m2_total += saving

        expected_monthly = m2_total.quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert calc.monthly_savings == expected_monthly, (
            f"Monthly savings should reset on new month. "
            f"Expected {expected_monthly} (month 2 only), got {calc.monthly_savings}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=optimization_decision_any())
    def test_savings_precision_two_decimal_places(self, data):
        """Savings are always reported with 2 decimal places precision.

        **Validates: Requirements 10.1**
        """
        non_optimized, actual = data
        calc = SavingsCalculator()
        timestamp = datetime(2024, 6, 15, 12, 0, 0)

        calc.record_optimization(non_optimized, actual, timestamp)

        daily = calc.daily_savings
        monthly = calc.monthly_savings

        # Check 2 decimal places
        assert daily == daily.quantize(Decimal("0.01")), (
            f"Daily savings should have 2dp: {daily}"
        )
        assert monthly == monthly.quantize(Decimal("0.01")), (
            f"Monthly savings should have 2dp: {monthly}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=optimization_decision_any())
    def test_baseline_unavailable_returns_none(self, data):
        """When baseline data is unavailable, savings sensors return None (unknown).

        **Validates: Requirements 10.7**
        """
        non_optimized, actual = data
        calc = SavingsCalculator()
        timestamp = datetime(2024, 6, 15, 12, 0, 0)

        # Record some savings first
        calc.record_optimization(non_optimized, actual, timestamp)

        # Mark baseline unavailable
        calc.mark_baseline_unavailable()

        assert calc.daily_savings is None, "Daily savings should be None when baseline unavailable"
        assert calc.monthly_savings is None, "Monthly savings should be None when baseline unavailable"

        # Mark available again — values should be restored
        calc.mark_baseline_available()
        assert calc.daily_savings is not None, "Daily savings should be restored"
        assert calc.monthly_savings is not None, "Monthly savings should be restored"
