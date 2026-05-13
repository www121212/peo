"""Moduł śledzenia oszczędności dla Polish Energy Optimizer (PEO).

Oblicza dzienne i miesięczne oszczędności jako różnicę między kosztem
bez optymalizacji (baseline) a kosztem rzeczywistym.

Sensory:
- Dzienne oszczędności (PLN, 2 miejsca po przecinku) — reset o 00:00
- Miesięczne skumulowane oszczędności (PLN, 2 miejsca po przecinku) — reset 1. dnia miesiąca
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

_LOGGER = logging.getLogger(__name__)

# Precision for savings calculations (2 decimal places)
_SAVINGS_PRECISION = Decimal("0.01")

# State value when baseline data is unavailable
STATE_UNKNOWN = "unknown"


@dataclass
class SavingsState:
    """Stan sensorów oszczędności."""

    daily_savings_pln: Decimal | str = Decimal("0.00")
    monthly_savings_pln: Decimal | str = Decimal("0.00")
    last_reset_date: date | None = None
    last_monthly_reset_date: date | None = None
    last_updated: datetime | None = None
    baseline_available: bool = True


@dataclass
class OptimizationRecord:
    """Rekord pojedynczej decyzji optymalizacyjnej z oszczędnością."""

    timestamp: datetime
    baseline_cost_pln: Decimal  # koszt bez optymalizacji
    actual_cost_pln: Decimal  # koszt rzeczywisty
    savings_pln: Decimal  # różnica (baseline - actual)
    module: str  # moduł źródłowy (ev, loads, pv)
    description: str


class SavingsTracker:
    """Tracker oszczędności generowanych przez optymalizację PEO.

    Oblicza:
    - Dzienne oszczędności: różnica między kosztem bez optymalizacji a kosztem
      rzeczywistym, resetowane codziennie o 00:00.
    - Miesięczne skumulowane oszczędności: suma dziennych oszczędności w bieżącym
      miesiącu, resetowane 1. dnia każdego miesiąca o 00:00.

    Gdy dane cenowe bazowe (baseline) są niedostępne, sensory przyjmują
    stan "unknown".
    """

    def __init__(self) -> None:
        """Inicjalizacja trackera oszczędności."""
        self._state = SavingsState()
        self._daily_records: list[OptimizationRecord] = []

    @property
    def state(self) -> SavingsState:
        """Aktualny stan sensorów oszczędności."""
        return self._state

    @property
    def daily_savings(self) -> Decimal | str:
        """Dzienne oszczędności (PLN, 2dp) lub 'unknown'."""
        return self._state.daily_savings_pln

    @property
    def monthly_savings(self) -> Decimal | str:
        """Miesięczne skumulowane oszczędności (PLN, 2dp) lub 'unknown'."""
        return self._state.monthly_savings_pln

    def record_optimization(
        self,
        baseline_cost_pln: Decimal,
        actual_cost_pln: Decimal,
        module: str,
        description: str,
        now: datetime | None = None,
    ) -> OptimizationRecord:
        """Zarejestruj decyzję optymalizacyjną i zaktualizuj oszczędności.

        Args:
            baseline_cost_pln: Koszt bez optymalizacji (PLN).
            actual_cost_pln: Koszt rzeczywisty po optymalizacji (PLN).
            module: Moduł źródłowy (np. "ev", "loads", "pv").
            description: Opis decyzji optymalizacyjnej.
            now: Aktualny czas (domyślnie datetime.now()).

        Returns:
            OptimizationRecord z obliczoną oszczędnością.

        Raises:
            ValueError: Gdy baseline_cost_pln lub actual_cost_pln jest ujemny.
        """
        if now is None:
            now = datetime.now()

        if baseline_cost_pln < Decimal("0"):
            raise ValueError(
                f"Koszt bazowy nie może być ujemny: {baseline_cost_pln}"
            )
        if actual_cost_pln < Decimal("0"):
            raise ValueError(
                f"Koszt rzeczywisty nie może być ujemny: {actual_cost_pln}"
            )

        # Check for daily/monthly reset before recording
        self._check_resets(now)

        # Calculate savings for this decision
        savings = (baseline_cost_pln - actual_cost_pln).quantize(
            _SAVINGS_PRECISION, rounding=ROUND_HALF_UP
        )

        record = OptimizationRecord(
            timestamp=now,
            baseline_cost_pln=baseline_cost_pln.quantize(_SAVINGS_PRECISION),
            actual_cost_pln=actual_cost_pln.quantize(_SAVINGS_PRECISION),
            savings_pln=savings,
            module=module,
            description=description,
        )

        self._daily_records.append(record)

        # Update daily savings
        if isinstance(self._state.daily_savings_pln, Decimal):
            self._state.daily_savings_pln = (
                self._state.daily_savings_pln + savings
            ).quantize(_SAVINGS_PRECISION, rounding=ROUND_HALF_UP)
        else:
            # Was unknown, now we have data
            self._state.daily_savings_pln = savings

        # Update monthly savings
        if isinstance(self._state.monthly_savings_pln, Decimal):
            self._state.monthly_savings_pln = (
                self._state.monthly_savings_pln + savings
            ).quantize(_SAVINGS_PRECISION, rounding=ROUND_HALF_UP)
        else:
            self._state.monthly_savings_pln = savings

        self._state.last_updated = now
        self._state.baseline_available = True

        _LOGGER.debug(
            "Zarejestrowano oszczędność: %.2f PLN (%s: %s). "
            "Dziennie: %s PLN, Miesięcznie: %s PLN",
            savings,
            module,
            description,
            self._state.daily_savings_pln,
            self._state.monthly_savings_pln,
        )

        return record

    def mark_baseline_unavailable(self, now: datetime | None = None) -> None:
        """Oznacz sensory jako 'unknown' gdy dane bazowe niedostępne.

        Wywoływane gdy dane cenowe wymagane do obliczenia kosztu bazowego
        (bez optymalizacji) są niedostępne.

        Args:
            now: Aktualny czas (domyślnie datetime.now()).
        """
        if now is None:
            now = datetime.now()

        self._state.daily_savings_pln = STATE_UNKNOWN
        self._state.monthly_savings_pln = STATE_UNKNOWN
        self._state.baseline_available = False
        self._state.last_updated = now

        _LOGGER.info(
            "Sensory oszczędności oznaczone jako 'unknown' — "
            "brak danych cenowych do obliczenia kosztu bazowego"
        )

    def check_and_reset(self, now: datetime | None = None) -> None:
        """Sprawdź i wykonaj resety dzienne/miesięczne.

        Powinno być wywoływane periodycznie (np. co minutę) lub
        przed każdą rejestracją oszczędności.

        Args:
            now: Aktualny czas (domyślnie datetime.now()).
        """
        if now is None:
            now = datetime.now()
        self._check_resets(now)

    def _check_resets(self, now: datetime) -> None:
        """Sprawdź czy wymagany jest reset dzienny lub miesięczny.

        Reset dzienny: o 00:00 każdego dnia.
        Reset miesięczny: o 00:00 pierwszego dnia każdego miesiąca.
        """
        today = now.date()

        # Monthly reset: 1st day of month
        if today.day == 1:
            if (
                self._state.last_monthly_reset_date is None
                or self._state.last_monthly_reset_date < today
            ):
                self._reset_monthly(today)

        # Daily reset
        if (
            self._state.last_reset_date is None
            or self._state.last_reset_date < today
        ):
            self._reset_daily(today)

    def _reset_daily(self, today: date) -> None:
        """Reset dziennych oszczędności do 0.00 PLN."""
        previous = self._state.daily_savings_pln
        self._state.daily_savings_pln = Decimal("0.00")
        self._state.last_reset_date = today
        self._daily_records.clear()

        _LOGGER.info(
            "Reset dziennych oszczędności (poprzednia wartość: %s PLN)",
            previous,
        )

    def _reset_monthly(self, today: date) -> None:
        """Reset miesięcznych oszczędności do 0.00 PLN."""
        previous = self._state.monthly_savings_pln
        self._state.monthly_savings_pln = Decimal("0.00")
        self._state.last_monthly_reset_date = today

        _LOGGER.info(
            "Reset miesięcznych oszczędności (poprzednia wartość: %s PLN)",
            previous,
        )

    def get_daily_records(self) -> list[OptimizationRecord]:
        """Zwróć listę rekordów optymalizacyjnych z bieżącego dnia."""
        return list(self._daily_records)
