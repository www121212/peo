"""Testy jednostkowe dla PriceValidator."""

from datetime import date
from decimal import Decimal

import pytest

from custom_components.peo.models import HourlyPrice
from custom_components.peo.price_validator import PriceValidator


def _make_hourly_price(
    hour: int,
    price_mwh: Decimal | float | int = 250,
    target_date: date | None = None,
) -> HourlyPrice:
    """Pomocnicza funkcja do tworzenia obiektów HourlyPrice."""
    if not isinstance(price_mwh, Decimal):
        price_mwh = Decimal(str(price_mwh))
    price_kwh = price_mwh / Decimal("1000")
    return HourlyPrice(
        hour=hour,
        price_pln_mwh=price_mwh,
        price_pln_kwh=price_kwh,
        date=target_date or date(2024, 1, 15),
    )


def _make_valid_prices(target_date: date | None = None) -> list[HourlyPrice]:
    """Utwórz poprawny zestaw 24 cen godzinowych."""
    return [_make_hourly_price(h, target_date=target_date) for h in range(24)]


class TestPriceValidatorValidate:
    """Testy metody validate()."""

    def setup_method(self):
        """Inicjalizacja walidatora."""
        self.validator = PriceValidator()

    def test_valid_24_prices(self):
        """Poprawny zestaw 24 cen powinien przejść walidację."""
        prices = _make_valid_prices()
        assert self.validator.validate(prices) is True

    def test_valid_prices_boundary_min(self):
        """Cena równa 0 PLN/MWh (dolna granica) jest poprawna."""
        prices = _make_valid_prices()
        prices[0] = _make_hourly_price(0, price_mwh=0)
        assert self.validator.validate(prices) is True

    def test_valid_prices_boundary_max(self):
        """Cena równa 5000 PLN/MWh (górna granica) jest poprawna."""
        prices = _make_valid_prices()
        prices[23] = _make_hourly_price(23, price_mwh=5000)
        assert self.validator.validate(prices) is True

    def test_reject_none(self):
        """None powinno być odrzucone."""
        assert self.validator.validate(None) is False

    def test_reject_not_a_list(self):
        """Obiekt niebędący listą powinien być odrzucony."""
        assert self.validator.validate("not a list") is False

    def test_reject_empty_list(self):
        """Pusta lista powinna być odrzucona."""
        assert self.validator.validate([]) is False

    def test_reject_fewer_than_24(self):
        """Lista z mniej niż 24 elementami powinna być odrzucona."""
        prices = [_make_hourly_price(h) for h in range(23)]
        assert self.validator.validate(prices) is False

    def test_reject_more_than_24(self):
        """Lista z więcej niż 24 elementami powinna być odrzucona."""
        prices = [_make_hourly_price(h % 24) for h in range(25)]
        assert self.validator.validate(prices) is False

    def test_reject_price_below_range(self):
        """Cena poniżej 0 PLN/MWh powinna być odrzucona."""
        prices = _make_valid_prices()
        prices[5] = _make_hourly_price(5, price_mwh=Decimal("-1"))
        assert self.validator.validate(prices) is False

    def test_reject_price_above_range(self):
        """Cena powyżej 5000 PLN/MWh powinna być odrzucona."""
        prices = _make_valid_prices()
        prices[10] = _make_hourly_price(10, price_mwh=Decimal("5001"))
        assert self.validator.validate(prices) is False

    def test_reject_duplicate_hours(self):
        """Zduplikowane godziny powinny być odrzucone."""
        prices = _make_valid_prices()
        # Zastąp godzinę 23 duplikatem godziny 0
        prices[23] = _make_hourly_price(0, price_mwh=300)
        assert self.validator.validate(prices) is False

    def test_reject_invalid_item_type(self):
        """Element niebędący HourlyPrice powinien być odrzucony."""
        prices = _make_valid_prices()
        prices[5] = {"hour": 5, "price_pln_mwh": Decimal("100")}
        assert self.validator.validate(prices) is False

    def test_reject_entire_dataset_on_single_error(self):
        """Jeden błąd powoduje odrzucenie całego zestawu danych."""
        prices = _make_valid_prices()
        prices[12] = _make_hourly_price(12, price_mwh=Decimal("6000"))
        assert self.validator.validate(prices) is False


class TestPriceValidatorGetErrors:
    """Testy metody get_validation_errors()."""

    def setup_method(self):
        """Inicjalizacja walidatora."""
        self.validator = PriceValidator()

    def test_no_errors_for_valid_data(self):
        """Poprawne dane nie generują błędów."""
        prices = _make_valid_prices()
        errors = self.validator.get_validation_errors(prices)
        assert errors == []

    def test_error_message_for_none(self):
        """None generuje odpowiedni komunikat."""
        errors = self.validator.get_validation_errors(None)
        assert len(errors) == 1
        assert "puste" in errors[0].lower() or "None" in errors[0]

    def test_error_message_for_wrong_count(self):
        """Nieprawidłowa liczba elementów generuje komunikat z liczbami."""
        prices = [_make_hourly_price(h) for h in range(20)]
        errors = self.validator.get_validation_errors(prices)
        assert any("24" in e and "20" in e for e in errors)

    def test_error_message_for_out_of_range_price(self):
        """Cena poza zakresem generuje komunikat z wartością i zakresem."""
        prices = _make_valid_prices()
        prices[3] = _make_hourly_price(3, price_mwh=Decimal("5500"))
        errors = self.validator.get_validation_errors(prices)
        assert any("5500" in e for e in errors)
        assert any("5000" in e for e in errors)

    def test_error_message_for_duplicate_hour(self):
        """Zduplikowana godzina generuje komunikat."""
        prices = _make_valid_prices()
        prices[23] = _make_hourly_price(0)
        errors = self.validator.get_validation_errors(prices)
        assert any("zduplikowana" in e.lower() for e in errors)

    def test_error_message_for_invalid_type(self):
        """Nieprawidłowy typ elementu generuje komunikat."""
        prices = _make_valid_prices()
        prices[7] = "not a price"
        errors = self.validator.get_validation_errors(prices)
        assert any("HourlyPrice" in e for e in errors)

    def test_multiple_errors_reported(self):
        """Wiele błędów jest raportowanych jednocześnie."""
        prices = _make_valid_prices()
        prices[0] = _make_hourly_price(0, price_mwh=Decimal("-10"))
        prices[23] = _make_hourly_price(23, price_mwh=Decimal("9999"))
        errors = self.validator.get_validation_errors(prices)
        assert len(errors) >= 2


class TestPriceValidatorEdgeCases:
    """Testy przypadków brzegowych."""

    def setup_method(self):
        """Inicjalizacja walidatora."""
        self.validator = PriceValidator()

    def test_all_prices_at_zero(self):
        """Wszystkie ceny równe 0 — poprawne."""
        prices = [_make_hourly_price(h, price_mwh=0) for h in range(24)]
        assert self.validator.validate(prices) is True

    def test_all_prices_at_max(self):
        """Wszystkie ceny równe 5000 — poprawne."""
        prices = [_make_hourly_price(h, price_mwh=5000) for h in range(24)]
        assert self.validator.validate(prices) is True

    def test_varying_prices(self):
        """Różne ceny w zakresie — poprawne."""
        prices = [
            _make_hourly_price(h, price_mwh=Decimal(str(h * 200)))
            for h in range(24)
        ]
        assert self.validator.validate(prices) is True

    def test_hours_out_of_order_but_complete(self):
        """Godziny w losowej kolejności ale kompletne — poprawne."""
        import random

        hours = list(range(24))
        random.shuffle(hours)
        prices = [_make_hourly_price(h) for h in hours]
        assert self.validator.validate(prices) is True
