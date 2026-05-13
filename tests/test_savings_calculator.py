"""Testy jednostkowe dla SavingsCalculator i SavingsTracker.

Testuje:
- Rejestrowanie oszczędności z decyzji optymalizacyjnych
- Obliczanie dziennych i miesięcznych oszczędności
- Reset dzienny o 00:00
- Reset miesięczny 1. dnia miesiąca o 00:00
- Oznaczanie "unknown" gdy brak danych bazowych
- Integrację SavingsTracker z SavingsCalculator

Requirements: 10.1, 10.2, 10.7
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from custom_components.peo.savings_calculator import SavingsCalculator
from custom_components.peo.savings_tracker import (
    SavingsTracker,
    OptimizationRecord,
    STATE_UNKNOWN,
)


class TestSavingsCalculatorRecordOptimizationSavings:
    """Testy metody record_optimization_savings."""

    def test_record_positive_savings(self):
        """Rejestracja pozytywnej oszczędności zwiększa dzienne i miesięczne."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.50"))

        assert calc.get_daily_savings() == Decimal("5.50")
        assert calc.get_monthly_savings() == Decimal("5.50")

    def test_record_multiple_savings(self):
        """Wielokrotne rejestracje kumulują się."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("3.00"))
        calc.record_optimization_savings(Decimal("2.50"))
        calc.record_optimization_savings(Decimal("1.25"))

        assert calc.get_daily_savings() == Decimal("6.75")
        assert calc.get_monthly_savings() == Decimal("6.75")

    def test_record_negative_savings(self):
        """Ujemna oszczędność (optymalizacja zwiększyła koszt) jest dozwolona."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("10.00"))
        calc.record_optimization_savings(Decimal("-3.00"))

        assert calc.get_daily_savings() == Decimal("7.00")
        assert calc.get_monthly_savings() == Decimal("7.00")

    def test_record_zero_savings(self):
        """Zerowa oszczędność nie zmienia stanu."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))
        calc.record_optimization_savings(Decimal("0.00"))

        assert calc.get_daily_savings() == Decimal("5.00")

    def test_record_rounds_to_two_decimal_places(self):
        """Oszczędności są zaokrąglane do 2 miejsc po przecinku."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("1.555"))

        assert calc.get_daily_savings() == Decimal("1.56")

    def test_record_rounds_half_up(self):
        """Zaokrąglanie HALF_UP: 0.005 -> 0.01."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("0.005"))

        assert calc.get_daily_savings() == Decimal("0.01")


class TestSavingsCalculatorGetDailySavings:
    """Testy metody get_daily_savings."""

    def test_initial_value_is_zero(self):
        """Początkowa wartość dziennych oszczędności to 0.00."""
        calc = SavingsCalculator()
        assert calc.get_daily_savings() == Decimal("0.00")

    def test_returns_none_when_baseline_unavailable(self):
        """Zwraca None gdy dane bazowe niedostępne."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))
        calc.set_baseline_available(False)

        assert calc.get_daily_savings() is None

    def test_returns_value_after_baseline_restored(self):
        """Zwraca wartość po przywróceniu danych bazowych."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))
        calc.set_baseline_available(False)
        calc.set_baseline_available(True)

        assert calc.get_daily_savings() == Decimal("5.00")

    def test_precision_two_decimal_places(self):
        """Wynik zawsze ma 2 miejsca po przecinku."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("1.10"))

        result = calc.get_daily_savings()
        assert result == Decimal("1.10")
        # Verify it's exactly 2 decimal places
        assert result == result.quantize(Decimal("0.01"))


class TestSavingsCalculatorGetMonthlySavings:
    """Testy metody get_monthly_savings."""

    def test_initial_value_is_zero(self):
        """Początkowa wartość miesięcznych oszczędności to 0.00."""
        calc = SavingsCalculator()
        assert calc.get_monthly_savings() == Decimal("0.00")

    def test_returns_none_when_baseline_unavailable(self):
        """Zwraca None gdy dane bazowe niedostępne."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("10.00"))
        calc.set_baseline_available(False)

        assert calc.get_monthly_savings() is None

    def test_accumulates_across_multiple_records(self):
        """Kumuluje oszczędności z wielu rekordów."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))
        calc.record_optimization_savings(Decimal("3.50"))
        calc.record_optimization_savings(Decimal("2.25"))

        assert calc.get_monthly_savings() == Decimal("10.75")


class TestSavingsCalculatorResetDaily:
    """Testy metody reset_daily."""

    def test_resets_daily_savings_to_zero(self):
        """Reset dzienny zeruje dzienne oszczędności."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("15.00"))

        ts = datetime(2024, 6, 16, 0, 0, 0)
        calc.reset_daily(ts)

        assert calc.get_daily_savings() == Decimal("0.00")

    def test_does_not_reset_monthly_savings(self):
        """Reset dzienny nie zeruje miesięcznych oszczędności."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("15.00"))

        ts = datetime(2024, 6, 16, 0, 0, 0)
        calc.reset_daily(ts)

        assert calc.get_monthly_savings() == Decimal("15.00")

    def test_updates_last_reset_date(self):
        """Reset dzienny aktualizuje last_reset_date."""
        calc = SavingsCalculator()
        ts = datetime(2024, 6, 16, 0, 0, 0)
        calc.reset_daily(ts)

        assert calc.last_reset_date == date(2024, 6, 16)

    def test_reset_without_timestamp_uses_now(self):
        """Reset bez timestamp używa datetime.now()."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))
        calc.reset_daily()

        assert calc.get_daily_savings() == Decimal("0.00")
        assert calc.last_reset_date is not None


class TestSavingsCalculatorResetMonthly:
    """Testy metody reset_monthly."""

    def test_resets_monthly_savings_to_zero(self):
        """Reset miesięczny zeruje miesięczne oszczędności."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("100.00"))

        ts = datetime(2024, 7, 1, 0, 0, 0)
        calc.reset_monthly(ts)

        assert calc.get_monthly_savings() == Decimal("0.00")

    def test_does_not_reset_daily_savings(self):
        """Reset miesięczny nie zeruje dziennych oszczędności."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("5.00"))

        ts = datetime(2024, 7, 1, 0, 0, 0)
        calc.reset_monthly(ts)

        # Daily savings remain (they are reset separately by reset_daily)
        assert calc.get_daily_savings() == Decimal("5.00")

    def test_updates_last_monthly_reset(self):
        """Reset miesięczny aktualizuje last_monthly_reset."""
        calc = SavingsCalculator()
        ts = datetime(2024, 7, 1, 0, 0, 0)
        calc.reset_monthly(ts)

        assert calc.last_monthly_reset == date(2024, 7, 1)

    def test_reset_without_timestamp_uses_now(self):
        """Reset bez timestamp używa datetime.now()."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("50.00"))
        calc.reset_monthly()

        assert calc.get_monthly_savings() == Decimal("0.00")
        assert calc.last_monthly_reset is not None


class TestSavingsCalculatorSetBaselineAvailable:
    """Testy metody set_baseline_available."""

    def test_set_unavailable_makes_savings_none(self):
        """Ustawienie baseline_available=False powoduje zwracanie None."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("10.00"))
        calc.set_baseline_available(False)

        assert calc.get_daily_savings() is None
        assert calc.get_monthly_savings() is None

    def test_set_available_restores_savings(self):
        """Ustawienie baseline_available=True przywraca wartości."""
        calc = SavingsCalculator()
        calc.record_optimization_savings(Decimal("10.00"))
        calc.set_baseline_available(False)
        calc.set_baseline_available(True)

        assert calc.get_daily_savings() == Decimal("10.00")
        assert calc.get_monthly_savings() == Decimal("10.00")

    def test_baseline_available_property(self):
        """Właściwość baseline_available odzwierciedla stan."""
        calc = SavingsCalculator()
        assert calc.baseline_available is True

        calc.set_baseline_available(False)
        assert calc.baseline_available is False

        calc.set_baseline_available(True)
        assert calc.baseline_available is True

    def test_mark_baseline_unavailable_alias(self):
        """mark_baseline_unavailable() jest aliasem dla set_baseline_available(False)."""
        calc = SavingsCalculator()
        calc.mark_baseline_unavailable()
        assert calc.baseline_available is False

    def test_mark_baseline_available_alias(self):
        """mark_baseline_available() jest aliasem dla set_baseline_available(True)."""
        calc = SavingsCalculator()
        calc.set_baseline_available(False)
        calc.mark_baseline_available()
        assert calc.baseline_available is True


class TestSavingsCalculatorAutoReset:
    """Testy automatycznego resetu przy record_optimization."""

    def test_auto_reset_daily_on_new_day(self):
        """record_optimization automatycznie resetuje dzienne przy nowym dniu."""
        calc = SavingsCalculator()

        # Dzień 1
        ts1 = datetime(2024, 6, 15, 12, 0, 0)
        calc.record_optimization(Decimal("10.00"), Decimal("7.00"), ts1)
        assert calc.get_daily_savings() == Decimal("3.00")

        # Dzień 2
        ts2 = datetime(2024, 6, 16, 10, 0, 0)
        calc.record_optimization(Decimal("8.00"), Decimal("6.00"), ts2)
        assert calc.get_daily_savings() == Decimal("2.00")

    def test_auto_reset_monthly_on_first_of_month(self):
        """record_optimization automatycznie resetuje miesięczne 1. dnia miesiąca."""
        calc = SavingsCalculator()

        # Czerwiec
        ts1 = datetime(2024, 6, 30, 12, 0, 0)
        calc.record_optimization(Decimal("10.00"), Decimal("5.00"), ts1)
        assert calc.get_monthly_savings() == Decimal("5.00")

        # Lipiec 1.
        ts2 = datetime(2024, 7, 1, 10, 0, 0)
        calc.record_optimization(Decimal("8.00"), Decimal("6.00"), ts2)
        assert calc.get_monthly_savings() == Decimal("2.00")

    def test_monthly_accumulates_across_days_same_month(self):
        """Miesięczne oszczędności kumulują się w ramach tego samego miesiąca."""
        calc = SavingsCalculator()

        ts1 = datetime(2024, 6, 10, 12, 0, 0)
        calc.record_optimization(Decimal("10.00"), Decimal("7.00"), ts1)

        ts2 = datetime(2024, 6, 15, 12, 0, 0)
        calc.record_optimization(Decimal("8.00"), Decimal("5.00"), ts2)

        ts3 = datetime(2024, 6, 20, 12, 0, 0)
        calc.record_optimization(Decimal("6.00"), Decimal("4.00"), ts3)

        # 3.00 + 3.00 + 2.00 = 8.00
        assert calc.get_monthly_savings() == Decimal("8.00")


class TestSavingsCalculatorRecordOptimization:
    """Testy metody record_optimization (wyższy poziom)."""

    def test_returns_savings_value(self):
        """record_optimization zwraca obliczoną oszczędność."""
        calc = SavingsCalculator()
        ts = datetime(2024, 6, 15, 12, 0, 0)

        result = calc.record_optimization(Decimal("10.00"), Decimal("7.00"), ts)

        assert result == Decimal("3.00")

    def test_negative_savings_when_actual_exceeds_baseline(self):
        """Ujemna oszczędność gdy koszt rzeczywisty > bazowy."""
        calc = SavingsCalculator()
        ts = datetime(2024, 6, 15, 12, 0, 0)

        result = calc.record_optimization(Decimal("5.00"), Decimal("8.00"), ts)

        assert result == Decimal("-3.00")
        assert calc.get_daily_savings() == Decimal("-3.00")

    def test_sets_baseline_available_true(self):
        """record_optimization ustawia baseline_available na True."""
        calc = SavingsCalculator()
        calc.set_baseline_available(False)

        ts = datetime(2024, 6, 15, 12, 0, 0)
        calc.record_optimization(Decimal("10.00"), Decimal("7.00"), ts)

        assert calc.baseline_available is True


class TestSavingsTrackerIntegration:
    """Testy integracji SavingsTracker z SavingsCalculator."""

    def test_tracker_uses_provided_calculator(self):
        """Tracker używa dostarczonego kalkulatora."""
        calc = SavingsCalculator()
        tracker = SavingsTracker(calculator=calc)

        assert tracker.calculator is calc

    def test_tracker_creates_calculator_if_none(self):
        """Tracker tworzy nowy kalkulator jeśli nie dostarczono."""
        tracker = SavingsTracker()
        assert tracker.calculator is not None

    def test_record_optimization_updates_calculator(self):
        """record_optimization aktualizuje kalkulator."""
        calc = SavingsCalculator()
        tracker = SavingsTracker(calculator=calc)

        now = datetime(2024, 6, 15, 12, 0, 0)
        tracker.record_optimization(
            baseline_cost_pln=Decimal("10.00"),
            actual_cost_pln=Decimal("7.00"),
            module="ev",
            description="Ładowanie EV w tanim oknie",
            now=now,
        )

        assert calc.get_daily_savings() == Decimal("3.00")
        assert calc.get_monthly_savings() == Decimal("3.00")

    def test_record_optimization_returns_record(self):
        """record_optimization zwraca OptimizationRecord."""
        tracker = SavingsTracker()
        now = datetime(2024, 6, 15, 12, 0, 0)

        record = tracker.record_optimization(
            baseline_cost_pln=Decimal("10.00"),
            actual_cost_pln=Decimal("7.00"),
            module="loads",
            description="Bojler CWU przesunięty",
            now=now,
        )

        assert isinstance(record, OptimizationRecord)
        assert record.savings_pln == Decimal("3.00")
        assert record.module == "loads"
        assert record.description == "Bojler CWU przesunięty"
        assert record.timestamp == now

    def test_record_optimization_validates_negative_baseline(self):
        """record_optimization odrzuca ujemny koszt bazowy."""
        tracker = SavingsTracker()

        with pytest.raises(ValueError, match="Koszt bazowy"):
            tracker.record_optimization(
                baseline_cost_pln=Decimal("-1.00"),
                actual_cost_pln=Decimal("5.00"),
                module="ev",
                description="test",
            )

    def test_record_optimization_validates_negative_actual(self):
        """record_optimization odrzuca ujemny koszt rzeczywisty."""
        tracker = SavingsTracker()

        with pytest.raises(ValueError, match="Koszt rzeczywisty"):
            tracker.record_optimization(
                baseline_cost_pln=Decimal("5.00"),
                actual_cost_pln=Decimal("-1.00"),
                module="ev",
                description="test",
            )

    def test_daily_savings_returns_unknown_when_baseline_unavailable(self):
        """daily_savings zwraca 'unknown' gdy baseline niedostępny."""
        tracker = SavingsTracker()
        tracker.mark_baseline_unavailable()

        assert tracker.daily_savings == STATE_UNKNOWN
        assert tracker.monthly_savings == STATE_UNKNOWN

    def test_multiple_modules_accumulate(self):
        """Oszczędności z różnych modułów kumulują się."""
        tracker = SavingsTracker()
        now = datetime(2024, 6, 15, 12, 0, 0)

        tracker.record_optimization(
            Decimal("10.00"), Decimal("7.00"), "ev", "EV charging", now
        )
        tracker.record_optimization(
            Decimal("5.00"), Decimal("3.00"), "loads", "Bojler", now
        )
        tracker.record_optimization(
            Decimal("8.00"), Decimal("6.00"), "pv", "Battery discharge", now
        )

        # 3.00 + 2.00 + 2.00 = 7.00
        assert tracker.daily_savings == Decimal("7.00")
        assert tracker.monthly_savings == Decimal("7.00")

    def test_get_daily_records(self):
        """get_daily_records zwraca listę rekordów z bieżącego dnia."""
        tracker = SavingsTracker()
        now = datetime(2024, 6, 15, 12, 0, 0)

        tracker.record_optimization(
            Decimal("10.00"), Decimal("7.00"), "ev", "EV", now
        )
        tracker.record_optimization(
            Decimal("5.00"), Decimal("3.00"), "loads", "Loads", now
        )

        records = tracker.get_daily_records()
        assert len(records) == 2
        assert records[0].module == "ev"
        assert records[1].module == "loads"

    def test_state_property(self):
        """state property zwraca aktualny stan."""
        tracker = SavingsTracker()
        now = datetime(2024, 6, 15, 12, 0, 0)

        tracker.record_optimization(
            Decimal("10.00"), Decimal("7.00"), "ev", "EV", now
        )

        state = tracker.state
        assert state.daily_savings_pln == Decimal("3.00")
        assert state.monthly_savings_pln == Decimal("3.00")
        assert state.baseline_available is True
        assert state.last_updated == now
