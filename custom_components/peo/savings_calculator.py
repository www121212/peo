"""Kalkulator oszczędności — obliczanie dziennych i miesięcznych oszczędności.

Odpowiada za:
- Obliczanie dziennych oszczędności (koszt bez optymalizacji - koszt rzeczywisty)
- Kumulowanie miesięcznych oszczędności
- Reset dzienny o 00:00
- Reset miesięczny 1. dnia miesiąca o 00:00
- Oznaczanie "unknown" gdy brak danych cenowych bazowych

Requirements: 10.1, 10.2, 10.7
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

_LOGGER = logging.getLogger(__name__)

# Precision for savings calculations (2 decimal places)
_SAVINGS_PRECISION = Decimal("0.01")


class SavingsCalculator:
    """Kalkulator oszczędności z optymalizacji energetycznej.

    Oblicza różnicę między kosztem bez optymalizacji (baseline)
    a kosztem rzeczywistym (actual). Oszczędności >= 0 gdy optymalizacja
    redukuje koszt.

    Tracks:
    - daily_savings: dzienne oszczędności (PLN, 2dp)
    - monthly_savings: miesięczne skumulowane oszczędności (PLN, 2dp)
    - baseline_available: czy dane bazowe są dostępne
    - last_reset_date: data ostatniego resetu dziennego
    - last_monthly_reset: data ostatniego resetu miesięcznego
    """

    def __init__(self) -> None:
        """Inicjalizacja kalkulatora oszczędności."""
        self._daily_savings: Decimal = Decimal("0.00")
        self._monthly_savings: Decimal = Decimal("0.00")
        self._baseline_available: bool = True
        self._last_reset_date: date | None = None
        self._last_monthly_reset: date | None = None

    @property
    def daily_savings(self) -> Decimal | None:
        """Dzienne oszczędności (PLN, 2 miejsca po przecinku).

        Returns:
            Decimal z oszczędnościami lub None gdy brak danych bazowych.
        """
        if not self._baseline_available:
            return None
        return self._daily_savings.quantize(_SAVINGS_PRECISION, rounding=ROUND_HALF_UP)

    @property
    def monthly_savings(self) -> Decimal | None:
        """Miesięczne skumulowane oszczędności (PLN, 2 miejsca po przecinku).

        Returns:
            Decimal z oszczędnościami lub None gdy brak danych bazowych.
        """
        if not self._baseline_available:
            return None
        return self._monthly_savings.quantize(
            _SAVINGS_PRECISION, rounding=ROUND_HALF_UP
        )

    @property
    def baseline_available(self) -> bool:
        """Czy dane cenowe bazowe są dostępne."""
        return self._baseline_available

    @property
    def last_reset_date(self) -> date | None:
        """Data ostatniego resetu dziennego."""
        return self._last_reset_date

    @property
    def last_monthly_reset(self) -> date | None:
        """Data ostatniego resetu miesięcznego."""
        return self._last_monthly_reset

    def record_optimization_savings(self, savings_pln: Decimal) -> None:
        """Dodaj oszczędność z decyzji optymalizacyjnej.

        Aktualizuje zarówno dzienne jak i miesięczne oszczędności.

        Args:
            savings_pln: Oszczędność z decyzji (PLN). Może być ujemna
                jeśli optymalizacja zwiększyła koszt.
        """
        savings_rounded = savings_pln.quantize(
            _SAVINGS_PRECISION, rounding=ROUND_HALF_UP
        )
        self._daily_savings += savings_rounded
        self._monthly_savings += savings_rounded

        _LOGGER.debug(
            "Zarejestrowano oszczędność: %.2f PLN (dziennie: %.2f, miesięcznie: %.2f)",
            float(savings_rounded),
            float(self._daily_savings),
            float(self._monthly_savings),
        )

    def record_optimization(
        self,
        non_optimized_cost: Decimal,
        actual_cost: Decimal,
        timestamp: datetime,
    ) -> Decimal:
        """Zarejestruj decyzję optymalizacyjną i oblicz oszczędność.

        Oszczędność = non_optimized_cost - actual_cost.
        Automatycznie sprawdza resety dzienne/miesięczne.

        Args:
            non_optimized_cost: Koszt bez optymalizacji (PLN).
            actual_cost: Koszt rzeczywisty (PLN).
            timestamp: Czas decyzji.

        Returns:
            Oszczędność z tej decyzji (PLN, 2dp).
        """
        self._check_resets(timestamp)
        self._baseline_available = True

        saving = (non_optimized_cost - actual_cost).quantize(
            _SAVINGS_PRECISION, rounding=ROUND_HALF_UP
        )

        self.record_optimization_savings(saving)

        return saving

    def get_daily_savings(self) -> Decimal | None:
        """Pobierz bieżące dzienne oszczędności.

        Returns:
            Decimal z oszczędnościami (PLN, 2dp) lub None gdy brak danych bazowych.
        """
        return self.daily_savings

    def get_monthly_savings(self) -> Decimal | None:
        """Pobierz bieżące miesięczne skumulowane oszczędności.

        Returns:
            Decimal z oszczędnościami (PLN, 2dp) lub None gdy brak danych bazowych.
        """
        return self.monthly_savings

    def reset_daily(self, timestamp: datetime | None = None) -> None:
        """Reset dziennych oszczędności do 0.00 PLN.

        Wywoływane o 00:00 każdego dnia.

        Args:
            timestamp: Bieżący czas (do ustalenia daty). Jeśli None,
                używa datetime.now().
        """
        if timestamp is None:
            timestamp = datetime.now()
        self._daily_savings = Decimal("0.00")
        self._last_reset_date = timestamp.date()
        _LOGGER.debug("Reset dziennych oszczędności (data: %s)", self._last_reset_date)

    def reset_monthly(self, timestamp: datetime | None = None) -> None:
        """Reset miesięcznych oszczędności do 0.00 PLN.

        Wywoływane o 00:00 pierwszego dnia każdego miesiąca.

        Args:
            timestamp: Bieżący czas (do ustalenia miesiąca). Jeśli None,
                używa datetime.now().
        """
        if timestamp is None:
            timestamp = datetime.now()
        self._monthly_savings = Decimal("0.00")
        self._last_monthly_reset = timestamp.date()
        _LOGGER.debug(
            "Reset miesięcznych oszczędności (data: %s)", self._last_monthly_reset
        )

    def set_baseline_available(self, available: bool) -> None:
        """Ustaw dostępność danych cenowych bazowych.

        Gdy available=False, sensory oszczędności zwracają None ("unknown").

        Args:
            available: True jeśli dane bazowe dostępne, False w przeciwnym razie.
        """
        self._baseline_available = available
        if not available:
            _LOGGER.warning(
                "Dane cenowe bazowe niedostępne — oszczędności: unknown"
            )
        else:
            _LOGGER.debug("Dane cenowe bazowe dostępne")

    def mark_baseline_unavailable(self) -> None:
        """Oznacz dane bazowe jako niedostępne (alias dla set_baseline_available(False))."""
        self.set_baseline_available(False)

    def mark_baseline_available(self) -> None:
        """Oznacz dane bazowe jako dostępne (alias dla set_baseline_available(True))."""
        self.set_baseline_available(True)

    def _check_resets(self, timestamp: datetime) -> None:
        """Sprawdź czy potrzebny reset dzienny/miesięczny.

        Args:
            timestamp: Bieżący czas.
        """
        current_date = timestamp.date()

        # Reset miesięczny — nowy miesiąc (1. dzień)
        if current_date.day == 1:
            if (
                self._last_monthly_reset is None
                or self._last_monthly_reset < current_date
            ):
                self.reset_monthly(timestamp)

        # Reset dzienny — nowy dzień
        if (
            self._last_reset_date is None
            or self._last_reset_date < current_date
        ):
            self.reset_daily(timestamp)
