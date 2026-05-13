"""Moduł śledzenia oszczędności dla Polish Energy Optimizer (PEO).

Wyższy poziom abstrakcji integrujący SavingsCalculator z decyzjami
optymalizacyjnymi ze wszystkich modułów (EV, loads, PV).

Oblicza oszczędności jako:
    hypothetical_cost_without_optimization - actual_cost

Po każdej decyzji wywołuje SavingsCalculator.record_optimization_savings().

Requirements: 10.1, 10.2, 10.7
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from .savings_calculator import SavingsCalculator

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

    Integruje się z decyzjami optymalizacyjnymi ze wszystkich modułów
    (EV, loads, PV) i deleguje obliczenia do SavingsCalculator.

    Oblicza oszczędności jako:
        hypothetical_cost_without_optimization - actual_cost

    Po każdej decyzji wywołuje SavingsCalculator.record_optimization_savings().
    """

    def __init__(self, calculator: SavingsCalculator | None = None) -> None:
        """Inicjalizacja trackera oszczędności.

        Args:
            calculator: Instancja SavingsCalculator. Jeśli None, tworzy nową.
        """
        self._calculator = calculator or SavingsCalculator()
        self._daily_records: list[OptimizationRecord] = []
        self._last_updated: datetime | None = None

    @property
    def calculator(self) -> SavingsCalculator:
        """Dostęp do kalkulatora oszczędności."""
        return self._calculator

    @property
    def daily_savings(self) -> Decimal | str:
        """Dzienne oszczędności (PLN, 2dp) lub 'unknown'."""
        result = self._calculator.get_daily_savings()
        if result is None:
            return STATE_UNKNOWN
        return result

    @property
    def monthly_savings(self) -> Decimal | str:
        """Miesięczne skumulowane oszczędności (PLN, 2dp) lub 'unknown'."""
        result = self._calculator.get_monthly_savings()
        if result is None:
            return STATE_UNKNOWN
        return result

    @property
    def state(self) -> SavingsState:
        """Aktualny stan sensorów oszczędności."""
        daily = self.daily_savings
        monthly = self.monthly_savings
        return SavingsState(
            daily_savings_pln=daily,
            monthly_savings_pln=monthly,
            last_reset_date=self._calculator.last_reset_date,
            last_monthly_reset_date=self._calculator.last_monthly_reset,
            last_updated=self._last_updated,
            baseline_available=self._calculator.baseline_available,
        )

    def record_optimization(
        self,
        baseline_cost_pln: Decimal,
        actual_cost_pln: Decimal,
        module: str,
        description: str,
        now: datetime | None = None,
    ) -> OptimizationRecord:
        """Zarejestruj decyzję optymalizacyjną i zaktualizuj oszczędności.

        Oblicza oszczędność jako: baseline_cost_pln - actual_cost_pln
        i wywołuje SavingsCalculator.record_optimization_savings().

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
        self._calculator._check_resets(now)

        # Calculate savings: hypothetical_cost_without_optimization - actual_cost
        savings = (baseline_cost_pln - actual_cost_pln).quantize(
            _SAVINGS_PRECISION, rounding=ROUND_HALF_UP
        )

        # Delegate to SavingsCalculator
        self._calculator.record_optimization_savings(savings)
        self._calculator.set_baseline_available(True)

        record = OptimizationRecord(
            timestamp=now,
            baseline_cost_pln=baseline_cost_pln.quantize(_SAVINGS_PRECISION),
            actual_cost_pln=actual_cost_pln.quantize(_SAVINGS_PRECISION),
            savings_pln=savings,
            module=module,
            description=description,
        )

        self._daily_records.append(record)
        self._last_updated = now

        _LOGGER.debug(
            "Zarejestrowano oszczędność: %.2f PLN (%s: %s). "
            "Dziennie: %s PLN, Miesięcznie: %s PLN",
            savings,
            module,
            description,
            self.daily_savings,
            self.monthly_savings,
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

        self._calculator.set_baseline_available(False)
        self._last_updated = now

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
        self._calculator._check_resets(now)

        # Clear daily records on new day
        today = now.date()
        if self._calculator.last_reset_date == today and self._daily_records:
            # Check if records are from a previous day
            if self._daily_records[0].timestamp.date() < today:
                self._daily_records.clear()

    def get_daily_records(self) -> list[OptimizationRecord]:
        """Zwróć listę rekordów optymalizacyjnych z bieżącego dnia."""
        return list(self._daily_records)
