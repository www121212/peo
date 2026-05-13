"""Moduł powiadomień o rekomendacji zmiany taryfy dla PEO.

Generuje powiadomienia gdy różnica kosztów między aktualną taryfą
a najtańszą przekracza 10% kosztu miesięcznego (max raz na 7 dni).
Udostępnia sensor z rekomendowaną taryfą i szacowaną oszczędnością.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .models import TariffComparison

_LOGGER = logging.getLogger(__name__)

# Minimum difference threshold to trigger notification (10% of monthly cost)
_NOTIFICATION_THRESHOLD_PERCENT = Decimal("10.0")

# Minimum interval between notifications (7 days)
_NOTIFICATION_COOLDOWN_DAYS = 7


@dataclass
class TariffRecommendationState:
    """Stan sensora rekomendacji taryfy."""

    recommended_tariff: str
    estimated_monthly_savings_pln: Decimal
    current_tariff: str
    is_sufficient_data: bool
    data_days: int
    last_updated: datetime | None = None


class TariffRecommendationNotifier:
    """Zarządzanie powiadomieniami o rekomendacji zmiany taryfy.

    Generuje powiadomienie gdy:
    - Różnica kosztów > 10% kosztu miesięcznego aktualnej taryfy
    - Od ostatniego powiadomienia minęło >= 7 dni

    Udostępnia stan sensora z rekomendowaną taryfą i oszczędnościami.
    """

    def __init__(self) -> None:
        """Inicjalizacja notifiera."""
        self._last_notification_time: datetime | None = None
        self._current_state: TariffRecommendationState | None = None

    @property
    def state(self) -> TariffRecommendationState | None:
        """Aktualny stan rekomendacji (do ekspozycji jako sensor)."""
        return self._current_state

    @property
    def last_notification_time(self) -> datetime | None:
        """Czas ostatniego wysłanego powiadomienia."""
        return self._last_notification_time

    def update_from_comparison(
        self,
        comparison: TariffComparison,
        now: datetime | None = None,
    ) -> bool:
        """Zaktualizuj stan na podstawie wyniku porównania taryf.

        Args:
            comparison: Wynik analizy porównawczej taryf.
            now: Aktualny czas (domyślnie datetime.now()).

        Returns:
            True jeśli powiadomienie powinno zostać wysłane, False w przeciwnym razie.
        """
        if now is None:
            now = datetime.now()

        # Update sensor state
        self._current_state = TariffRecommendationState(
            recommended_tariff=comparison.recommended.value,
            estimated_monthly_savings_pln=comparison.monthly_savings_pln,
            current_tariff=comparison.current_tariff.value,
            is_sufficient_data=comparison.is_sufficient_data,
            data_days=comparison.data_days,
            last_updated=now,
        )

        # Check if notification should be generated
        should_notify = self._should_notify(comparison, now)

        if should_notify:
            self._last_notification_time = now
            _LOGGER.info(
                "Rekomendacja zmiany taryfy: %s → %s, oszczędność: %.2f PLN/mies.",
                comparison.current_tariff.value,
                comparison.recommended.value,
                comparison.monthly_savings_pln,
            )

        return should_notify

    def _should_notify(
        self,
        comparison: TariffComparison,
        now: datetime,
    ) -> bool:
        """Sprawdź czy powiadomienie powinno zostać wygenerowane.

        Warunki:
        1. Dane wystarczające (>= 7 dni)
        2. Rekomendowana taryfa != aktualna
        3. Różnica > 10% kosztu miesięcznego aktualnej taryfy
        4. Od ostatniego powiadomienia minęło >= 7 dni

        Args:
            comparison: Wynik porównania taryf.
            now: Aktualny czas.

        Returns:
            True jeśli wszystkie warunki spełnione.
        """
        # Condition 1: Sufficient data
        if not comparison.is_sufficient_data:
            _LOGGER.debug(
                "Brak powiadomienia: niewystarczające dane (%d dni)",
                comparison.data_days,
            )
            return False

        # Condition 2: Recommended differs from current
        if comparison.recommended == comparison.current_tariff:
            _LOGGER.debug("Brak powiadomienia: aktualna taryfa jest optymalna")
            return False

        # Condition 3: Difference > 10% of monthly cost
        if not comparison.rankings:
            return False

        # Find current tariff monthly cost
        current_monthly_cost = Decimal("0")
        for ranking in comparison.rankings:
            if ranking.tariff == comparison.current_tariff:
                current_monthly_cost = ranking.monthly_cost_pln
                break

        if current_monthly_cost <= Decimal("0"):
            return False

        difference_percent = (
            comparison.monthly_savings_pln / current_monthly_cost * Decimal("100")
        )

        if difference_percent <= _NOTIFICATION_THRESHOLD_PERCENT:
            _LOGGER.debug(
                "Brak powiadomienia: różnica %.1f%% <= 10%%",
                float(difference_percent),
            )
            return False

        # Condition 4: Cooldown period (7 days)
        if self._last_notification_time is not None:
            elapsed = now - self._last_notification_time
            if elapsed < timedelta(days=_NOTIFICATION_COOLDOWN_DAYS):
                _LOGGER.debug(
                    "Brak powiadomienia: cooldown (ostatnie %s temu)",
                    elapsed,
                )
                return False

        return True

    def get_notification_message(self) -> str | None:
        """Generuj treść powiadomienia na podstawie aktualnego stanu.

        Returns:
            Treść powiadomienia w języku polskim lub None jeśli brak rekomendacji.
        """
        if self._current_state is None:
            return None

        if not self._current_state.is_sufficient_data:
            return None

        if self._current_state.recommended_tariff == self._current_state.current_tariff:
            return None

        return (
            f"Rekomendacja zmiany taryfy: przejście z {self._current_state.current_tariff} "
            f"na {self._current_state.recommended_tariff} może zaoszczędzić "
            f"{self._current_state.estimated_monthly_savings_pln:.2f} PLN miesięcznie."
        )

    def reset_cooldown(self) -> None:
        """Resetuj cooldown powiadomień (np. po zmianie taryfy przez użytkownika)."""
        self._last_notification_time = None
        _LOGGER.debug("Zresetowano cooldown powiadomień o rekomendacji taryfy")
