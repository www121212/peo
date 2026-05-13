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


class SavingsCalculator:
    """Kalkulator oszczędności z optymalizacji energetycznej.

    Oblicza różnicę między kosztem bez optymalizacji (baseline)
    a kosztem rzeczywistym (actual). Oszczędności >= 0 gdy optymalizacja
    redukuje koszt.
    """

    def __init__(self) -> None:
        """Inicjalizacja kalkulatora oszczędności."""
        self._daily_savings: Decimal = Decimal("0.00")
        self._monthly_savings: Decimal = Decimal("0.00")
        self._tracking_date: date | None = None
        self._tracking_month: int | None = None
        self._baseline_available: bool = True

    @property
    def daily_savings(self) -> Decimal | None:
        """Dzienne oszczędności (PLN, 2 miejsca po przecinku).

        Returns:
            Decimal z oszczędnościami lub None gdy brak danych bazowych.
        """
        if not self._baseline_available:
            return None
        return self._daily_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def monthly_savings(self) -> Decimal | None:
        """Miesięczne skumulowane oszczędności (PLN, 2 miejsca po przecinku).

        Returns:
            Decimal z oszczędnościami lub None gdy brak danych bazowych.
        """
        if not self._baseline_available:
            return None
        return self._monthly_savings.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def record_optimization(
        self,
        non_optimized_cost: Decimal,
        actual_cost: Decimal,
        timestamp: datetime,
    ) -> Decimal:
        """Zarejestruj decyzję optymalizacyjną i oblicz oszczędność.

        Oszczędność = non_optimized_cost - actual_cost.
        Wartość >= 0 gdy optymalizacja redukuje koszt.

        Args:
            non_optimized_cost: Koszt bez optymalizacji (PLN).
            actual_cost: Koszt rzeczywisty (PLN).
            timestamp: Czas decyzji.

        Returns:
            Oszczędność z tej decyzji (PLN, 2dp).
        """
        self._check_resets(timestamp)
        self._baseline_available = True

        saving = non_optimized_cost - actual_cost
        saving_rounded = saving.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        self._daily_savings += saving_rounded
        self._monthly_savings += saving_rounded

        _LOGGER.debug(
            "Oszczędność: %.2f PLN (dzienna: %.2f, miesięczna: %.2f)",
            float(saving_rounded),
            float(self._daily_savings),
            float(self._monthly_savings),
        )

        return saving_rounded

    def mark_baseline_unavailable(self) -> None:
        """Oznacz dane bazowe jako niedostępne.

        Sensory oszczędności przejdą w stan "unknown".
        """
        self._baseline_available = False
        _LOGGER.warning("Dane cenowe bazowe niedostępne — oszczędności: unknown")

    def mark_baseline_available(self) -> None:
        """Oznacz dane bazowe jako dostępne."""
        self._baseline_available = True

    def reset_daily(self, timestamp: datetime) -> None:
        """Reset dzienny o 00:00.

        Args:
            timestamp: Bieżący czas (do ustalenia daty).
        """
        self._daily_savings = Decimal("0.00")
        self._tracking_date = timestamp.date()
        _LOGGER.debug("Reset dziennych oszczędności (data: %s)", self._tracking_date)

    def reset_monthly(self, timestamp: datetime) -> None:
        """Reset miesięczny 1. dnia miesiąca o 00:00.

        Args:
            timestamp: Bieżący czas (do ustalenia miesiąca).
        """
        self._monthly_savings = Decimal("0.00")
        self._tracking_month = timestamp.month
        _LOGGER.debug("Reset miesięcznych oszczędności (miesiąc: %d)", self._tracking_month)

    def _check_resets(self, timestamp: datetime) -> None:
        """Sprawdź czy potrzebny reset dzienny/miesięczny.

        Args:
            timestamp: Bieżący czas.
        """
        current_date = timestamp.date()
        current_month = timestamp.month

        # Reset miesięczny — nowy miesiąc
        if self._tracking_month is not None and self._tracking_month != current_month:
            self.reset_monthly(timestamp)

        # Reset dzienny — nowy dzień
        if self._tracking_date is not None and self._tracking_date != current_date:
            self.reset_daily(timestamp)

        # Inicjalizacja tracking
        if self._tracking_date is None:
            self._tracking_date = current_date
        if self._tracking_month is None:
            self._tracking_month = current_month
