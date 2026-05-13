"""Testy jednostkowe dla TariffRecommendationNotifier.

Validates: Requirements 6.3, 6.4
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.peo.enums import TariffType
from custom_components.peo.models import TariffComparison, TariffRanking
from custom_components.peo.tariff_recommendation import (
    NOTIFICATION_TITLE,
    TariffRecommendationNotifier,
    TariffRecommendationState,
)


@pytest.fixture
def notifier():
    """Fixture: fresh TariffRecommendationNotifier."""
    return TariffRecommendationNotifier()


def _make_comparison(
    current: TariffType = TariffType.G11,
    recommended: TariffType = TariffType.G12,
    current_cost: Decimal = Decimal("500.00"),
    cheapest_cost: Decimal = Decimal("400.00"),
    savings: Decimal = Decimal("100.00"),
    is_sufficient: bool = True,
    data_days: int = 30,
) -> TariffComparison:
    """Helper: create a TariffComparison with given parameters."""
    rankings = [
        TariffRanking(
            tariff=recommended,
            monthly_cost_pln=cheapest_cost,
            difference_pln=cheapest_cost - current_cost,
            difference_percent=float((cheapest_cost - current_cost) / current_cost * 100),
        ),
        TariffRanking(
            tariff=current,
            monthly_cost_pln=current_cost,
            difference_pln=Decimal("0.00"),
            difference_percent=0.0,
        ),
    ]
    # Sort by cost
    rankings.sort(key=lambda r: r.monthly_cost_pln)

    return TariffComparison(
        current_tariff=current,
        rankings=rankings,
        recommended=recommended,
        monthly_savings_pln=savings,
        data_days=data_days,
        is_sufficient_data=is_sufficient,
    )


class TestUpdateFromComparison:
    """Testy update_from_comparison()."""

    def test_updates_sensor_state(self, notifier):
        """Aktualizuje stan sensora po porównaniu."""
        comparison = _make_comparison()
        now = datetime(2024, 3, 15, 1, 0)

        notifier.update_from_comparison(comparison, now=now)

        state = notifier.state
        assert state is not None
        assert state.recommended_tariff == "G12"
        assert state.estimated_monthly_savings_pln == Decimal("100.00")
        assert state.current_tariff == "G11"
        assert state.is_sufficient_data is True
        assert state.data_days == 30
        assert state.last_updated == now

    def test_returns_true_when_notification_triggered(self, notifier):
        """Zwraca True gdy powiadomienie powinno być wysłane."""
        # Difference > 10%: savings 100 PLN on 500 PLN = 20%
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)

        result = notifier.update_from_comparison(comparison, now=now)
        assert result is True

    def test_returns_false_when_difference_below_threshold(self, notifier):
        """Zwraca False gdy różnica <= 10%."""
        # Difference 5%: savings 25 PLN on 500 PLN = 5%
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("475.00"),
            savings=Decimal("25.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)

        result = notifier.update_from_comparison(comparison, now=now)
        assert result is False

    def test_returns_false_when_insufficient_data(self, notifier):
        """Zwraca False gdy dane niewystarczające."""
        comparison = _make_comparison(is_sufficient=False, data_days=5)
        now = datetime(2024, 3, 15, 1, 0)

        result = notifier.update_from_comparison(comparison, now=now)
        assert result is False

    def test_returns_false_when_current_is_cheapest(self, notifier):
        """Zwraca False gdy aktualna taryfa jest najtańsza."""
        comparison = _make_comparison(
            current=TariffType.G12,
            recommended=TariffType.G12,
            current_cost=Decimal("400.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("0.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)

        result = notifier.update_from_comparison(comparison, now=now)
        assert result is False

    def test_cooldown_prevents_repeated_notifications(self, notifier):
        """Cooldown 7 dni zapobiega powtórnym powiadomieniom."""
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )

        # First notification
        now1 = datetime(2024, 3, 15, 1, 0)
        result1 = notifier.update_from_comparison(comparison, now=now1)
        assert result1 is True

        # 3 days later — should be blocked by cooldown
        now2 = now1 + timedelta(days=3)
        result2 = notifier.update_from_comparison(comparison, now=now2)
        assert result2 is False

    def test_notification_allowed_after_cooldown(self, notifier):
        """Powiadomienie dozwolone po upływie 7 dni."""
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )

        # First notification
        now1 = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now1)

        # 8 days later — cooldown expired
        now2 = now1 + timedelta(days=8)
        result = notifier.update_from_comparison(comparison, now=now2)
        assert result is True

    def test_exactly_7_days_cooldown_allows_notification(self, notifier):
        """Dokładnie 7 dni po ostatnim powiadomieniu — dozwolone."""
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )

        now1 = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now1)

        now2 = now1 + timedelta(days=7)
        result = notifier.update_from_comparison(comparison, now=now2)
        assert result is True

    def test_threshold_exactly_10_percent_no_notification(self, notifier):
        """Różnica dokładnie 10% — brak powiadomienia (wymaga > 10%)."""
        # 10% of 500 = 50
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("450.00"),
            savings=Decimal("50.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)

        result = notifier.update_from_comparison(comparison, now=now)
        assert result is False


class TestGetNotificationMessage:
    """Testy get_notification_message()."""

    def test_returns_none_when_no_state(self, notifier):
        """Zwraca None gdy brak stanu."""
        assert notifier.get_notification_message() is None

    def test_returns_none_when_insufficient_data(self, notifier):
        """Zwraca None gdy dane niewystarczające."""
        comparison = _make_comparison(is_sufficient=False)
        notifier.update_from_comparison(comparison)
        assert notifier.get_notification_message() is None

    def test_returns_none_when_current_is_optimal(self, notifier):
        """Zwraca None gdy aktualna taryfa jest optymalna."""
        comparison = _make_comparison(
            current=TariffType.G12,
            recommended=TariffType.G12,
            savings=Decimal("0.00"),
        )
        notifier.update_from_comparison(comparison)
        assert notifier.get_notification_message() is None

    def test_returns_polish_message(self, notifier):
        """Zwraca wiadomość w języku polskim z danymi."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G12,
            savings=Decimal("85.50"),
        )
        notifier.update_from_comparison(comparison)

        msg = notifier.get_notification_message()
        assert msg is not None
        assert "G11" in msg
        assert "G12" in msg
        assert "85.50" in msg
        assert "PLN" in msg


class TestResetCooldown:
    """Testy reset_cooldown()."""

    def test_reset_allows_immediate_notification(self, notifier):
        """Reset cooldown pozwala na natychmiastowe powiadomienie."""
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )

        # First notification
        now1 = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now1)

        # Reset cooldown
        notifier.reset_cooldown()

        # Immediate second notification should work
        now2 = now1 + timedelta(hours=1)
        result = notifier.update_from_comparison(comparison, now=now2)
        assert result is True


class TestLastNotificationTime:
    """Testy last_notification_time property."""

    def test_initially_none(self, notifier):
        """Początkowo None."""
        assert notifier.last_notification_time is None

    def test_updated_after_notification(self, notifier):
        """Aktualizowane po wysłaniu powiadomienia."""
        comparison = _make_comparison(
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now)

        assert notifier.last_notification_time == now

    def test_not_updated_when_no_notification(self, notifier):
        """Nie aktualizowane gdy brak powiadomienia."""
        comparison = _make_comparison(is_sufficient=False)
        now = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now)

        assert notifier.last_notification_time is None


class TestNotificationTitle:
    """Testy notification_title property."""

    def test_title_is_polish(self, notifier):
        """Tytuł powiadomienia jest w języku polskim."""
        assert notifier.notification_title == "PEO: Rekomendacja zmiany taryfy"

    def test_title_matches_constant(self, notifier):
        """Tytuł odpowiada stałej NOTIFICATION_TITLE."""
        assert notifier.notification_title == NOTIFICATION_TITLE


class TestGetSensorData:
    """Testy get_sensor_data()."""

    def test_returns_none_values_when_no_state(self, notifier):
        """Zwraca None dla pól gdy brak stanu."""
        data = notifier.get_sensor_data()
        assert data["recommended_tariff"] is None
        assert data["monthly_savings_pln"] == Decimal("0.00")
        assert data["current_tariff"] is None
        assert data["last_analysis_date"] is None

    def test_returns_correct_data_after_update(self, notifier):
        """Zwraca poprawne dane po aktualizacji."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G12,
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        now = datetime(2024, 3, 15, 1, 0)
        notifier.update_from_comparison(comparison, now=now)

        data = notifier.get_sensor_data()
        assert data["recommended_tariff"] == "G12"
        assert data["monthly_savings_pln"] == Decimal("100.00")
        assert data["current_tariff"] == "G11"
        assert data["last_analysis_date"] == "2024-03-15T01:00:00"

    def test_last_analysis_date_is_iso_format(self, notifier):
        """last_analysis_date jest w formacie ISO 8601."""
        comparison = _make_comparison()
        now = datetime(2024, 6, 20, 14, 30, 45)
        notifier.update_from_comparison(comparison, now=now)

        data = notifier.get_sensor_data()
        assert data["last_analysis_date"] == "2024-06-20T14:30:45"

    def test_contains_all_required_keys(self, notifier):
        """Słownik zawiera wszystkie wymagane klucze."""
        data = notifier.get_sensor_data()
        assert "recommended_tariff" in data
        assert "monthly_savings_pln" in data
        assert "current_tariff" in data
        assert "last_analysis_date" in data


class TestNotificationMessageContent:
    """Testy treści powiadomienia — zawiera koszty aktualnej i rekomendowanej taryfy."""

    def test_message_contains_current_cost(self, notifier):
        """Wiadomość zawiera koszt aktualnej taryfy."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G12,
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        notifier.update_from_comparison(comparison)

        msg = notifier.get_notification_message()
        assert msg is not None
        assert "500.00" in msg

    def test_message_contains_recommended_cost(self, notifier):
        """Wiadomość zawiera koszt rekomendowanej taryfy."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G12,
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        notifier.update_from_comparison(comparison)

        msg = notifier.get_notification_message()
        assert msg is not None
        assert "400.00" in msg

    def test_message_contains_savings(self, notifier):
        """Wiadomość zawiera kwotę oszczędności."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G12,
            current_cost=Decimal("500.00"),
            cheapest_cost=Decimal("400.00"),
            savings=Decimal("100.00"),
        )
        notifier.update_from_comparison(comparison)

        msg = notifier.get_notification_message()
        assert msg is not None
        assert "100.00" in msg

    def test_message_contains_tariff_names(self, notifier):
        """Wiadomość zawiera nazwy taryf."""
        comparison = _make_comparison(
            current=TariffType.G11,
            recommended=TariffType.G13,
            current_cost=Decimal("600.00"),
            cheapest_cost=Decimal("450.00"),
            savings=Decimal("150.00"),
        )
        notifier.update_from_comparison(comparison)

        msg = notifier.get_notification_message()
        assert msg is not None
        assert "G11" in msg
        assert "G13" in msg
