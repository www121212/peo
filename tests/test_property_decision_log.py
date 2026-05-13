"""Property-based tests for decision log.

**Validates: Requirements 10.5**

Property 27: Bufor ostatnich 10 decyzji optymalizacyjnych
Dla dowolnej sekwencji decyzji optymalizacyjnych, atrybut diagnostyczny powinien
zawsze zawierać dokładnie ostatnie 10 decyzji (lub mniej jeśli łącznie podjęto
mniej niż 10), każda z polami: timestamp, decyzja, powód, oszczędność.
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

import pytest
from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    decimals,
    integers,
    text,
    datetimes,
    lists,
)

from custom_components.peo.decision_log import DecisionLog, DecisionEntry

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Strategies ---


@composite
def valid_savings(draw):
    """Generate a valid savings value in PLN (-100.00 to 500.00)."""
    return draw(
        decimals(
            min_value=Decimal("-100.00"),
            max_value=Decimal("500.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        )
    )


@composite
def valid_decision(draw, base_time=None):
    """Generate a valid optimization decision."""
    if base_time is None:
        base_time = draw(
            datetimes(
                min_value=datetime(2024, 1, 1),
                max_value=datetime(2025, 12, 31),
            )
        )
    decision = f"decision_{draw(integers(min_value=1, max_value=1000))}"
    reason = f"reason_{draw(integers(min_value=1, max_value=1000))}"
    savings_pln = draw(valid_savings())

    return {
        "timestamp": base_time,
        "decision": decision,
        "reason": reason,
        "savings_pln": savings_pln,
    }


@composite
def multiple_decisions(draw, min_count=1, max_count=30):
    """Generate multiple decisions with increasing timestamps."""
    count = draw(integers(min_value=min_count, max_value=max_count))
    base_time = datetime(2024, 6, 15, 8, 0, 0)
    decisions = []

    for i in range(count):
        timestamp = base_time + timedelta(minutes=i * 10)
        decision = f"decision_{i}"
        reason = f"reason_{i}"
        savings_pln = draw(valid_savings())
        decisions.append({
            "timestamp": timestamp,
            "decision": decision,
            "reason": reason,
            "savings_pln": savings_pln,
        })

    return decisions


@composite
def more_than_10_decisions(draw):
    """Generate more than 10 decisions to test buffer overflow."""
    count = draw(integers(min_value=11, max_value=50))
    base_time = datetime(2024, 6, 15, 8, 0, 0)
    decisions = []

    for i in range(count):
        timestamp = base_time + timedelta(minutes=i * 5)
        decision = f"decision_{i}"
        reason = f"reason_{i}"
        savings_pln = draw(valid_savings())
        decisions.append({
            "timestamp": timestamp,
            "decision": decision,
            "reason": reason,
            "savings_pln": savings_pln,
        })

    return decisions


# --- Property 27 Tests ---


class TestProperty27DecisionLog:
    """Property 27: Bufor ostatnich 10 decyzji optymalizacyjnych.

    **Validates: Requirements 10.5**
    """

    @PROPERTY_TEST_SETTINGS
    @given(decisions=multiple_decisions(min_count=1, max_count=10))
    def test_log_contains_at_most_10_entries(self, decisions):
        """Decision log always contains at most 10 entries.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()
        assert len(diagnostic) <= 10, (
            f"Diagnostic should have at most 10 entries, got {len(diagnostic)}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=more_than_10_decisions())
    def test_log_never_exceeds_10_entries(self, decisions):
        """Even after many decisions, log never exceeds 10 entries.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()
        assert len(diagnostic) == 10, (
            f"After {len(decisions)} decisions, diagnostic should have exactly 10 entries, "
            f"got {len(diagnostic)}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=more_than_10_decisions())
    def test_newest_first_in_diagnostic(self, decisions):
        """Diagnostic attribute has newest decisions first.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        # Verify newest first ordering
        for i in range(len(diagnostic) - 1):
            ts_current = datetime.fromisoformat(diagnostic[i]["timestamp"])
            ts_next = datetime.fromisoformat(diagnostic[i + 1]["timestamp"])
            assert ts_current >= ts_next, (
                f"Diagnostic should be newest first: "
                f"{diagnostic[i]['timestamp']} should be >= {diagnostic[i+1]['timestamp']}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=more_than_10_decisions())
    def test_only_last_10_decisions_retained(self, decisions):
        """Only the last 10 decisions are retained in the log.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        # The newest entry should be the last decision recorded
        last_decision = decisions[-1]
        assert diagnostic[0]["decision"] == last_decision["decision"], (
            f"Newest entry should be '{last_decision['decision']}', "
            f"got '{diagnostic[0]['decision']}'"
        )

        # The oldest entry in diagnostic should be the 10th-from-last decision
        tenth_from_last = decisions[-10]
        assert diagnostic[9]["decision"] == tenth_from_last["decision"], (
            f"Oldest entry should be '{tenth_from_last['decision']}', "
            f"got '{diagnostic[9]['decision']}'"
        )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=multiple_decisions(min_count=1, max_count=10))
    def test_all_entries_have_iso8601_timestamps(self, decisions):
        """All entries in diagnostic have valid ISO 8601 timestamps.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        for entry in diagnostic:
            assert "timestamp" in entry, "Entry must have 'timestamp' field"
            # Verify ISO 8601 format by parsing
            try:
                parsed = datetime.fromisoformat(entry["timestamp"])
                assert parsed is not None
            except ValueError:
                pytest.fail(
                    f"Timestamp '{entry['timestamp']}' is not valid ISO 8601"
                )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=multiple_decisions(min_count=1, max_count=10))
    def test_all_entries_have_2dp_savings(self, decisions):
        """All entries in diagnostic have savings with 2 decimal places.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        for entry in diagnostic:
            assert "savings_pln" in entry, "Entry must have 'savings_pln' field"
            savings = Decimal(entry["savings_pln"])
            assert savings == savings.quantize(Decimal("0.01")), (
                f"Savings should have 2dp: {savings}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=multiple_decisions(min_count=1, max_count=10))
    def test_all_entries_have_required_fields(self, decisions):
        """All entries contain: timestamp, decision, reason, savings_pln.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        required_fields = {"timestamp", "decision", "reason", "savings_pln"}
        for entry in diagnostic:
            missing = required_fields - set(entry.keys())
            assert not missing, (
                f"Entry is missing required fields: {missing}. Entry: {entry}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(decisions=multiple_decisions(min_count=1, max_count=9))
    def test_fewer_than_10_decisions_all_present(self, decisions):
        """When fewer than 10 decisions recorded, all are present in diagnostic.

        **Validates: Requirements 10.5**
        """
        assume(len(decisions) < 10)
        log = DecisionLog()

        for d in decisions:
            log.record_decision(**d)

        diagnostic = log.get_diagnostic_attribute()

        assert len(diagnostic) == len(decisions), (
            f"With {len(decisions)} decisions, diagnostic should have "
            f"{len(decisions)} entries, got {len(diagnostic)}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_decision())
    def test_single_decision_correctly_stored(self, data):
        """A single decision is correctly stored and retrievable.

        **Validates: Requirements 10.5**
        """
        log = DecisionLog()
        log.record_decision(**data)

        diagnostic = log.get_diagnostic_attribute()

        assert len(diagnostic) == 1
        entry = diagnostic[0]
        assert entry["decision"] == data["decision"]
        assert entry["reason"] == data["reason"]
        expected_savings = data["savings_pln"].quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        assert Decimal(entry["savings_pln"]) == expected_savings
