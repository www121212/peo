"""Testy jednostkowe dla InputValidator."""

from decimal import Decimal

import pytest

from custom_components.peo.validators import InputValidator


class TestValidatePrice:
    """Testy walidacji ceny energii."""

    def test_valid_price_integer(self):
        """Poprawna cena jako liczba całkowita."""
        result = InputValidator.validate_price(100)
        assert result == Decimal("100")

    def test_valid_price_decimal(self):
        """Poprawna cena jako Decimal."""
        result = InputValidator.validate_price(Decimal("250.50"))
        assert result == Decimal("250.50")

    def test_valid_price_string(self):
        """Poprawna cena jako string."""
        result = InputValidator.validate_price("1500.75")
        assert result == Decimal("1500.75")

    def test_valid_price_zero(self):
        """Cena równa zero (dolna granica)."""
        result = InputValidator.validate_price(0)
        assert result == Decimal("0")

    def test_valid_price_max(self):
        """Cena równa 5000 (górna granica)."""
        result = InputValidator.validate_price(5000)
        assert result == Decimal("5000")

    def test_invalid_price_none(self):
        """None powinno zgłosić ValueError."""
        with pytest.raises(ValueError, match="wartość nie może być pusta"):
            InputValidator.validate_price(None)

    def test_invalid_price_negative(self):
        """Cena ujemna poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_price(-1)

    def test_invalid_price_too_high(self):
        """Cena powyżej 5000 poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_price(5001)

    def test_invalid_price_not_numeric(self):
        """Wartość nieliczbowa."""
        with pytest.raises(ValueError, match="wymagana wartość liczbowa"):
            InputValidator.validate_price("abc")


class TestValidateSoc:
    """Testy walidacji poziomu naładowania (SoC)."""

    def test_valid_soc_zero(self):
        """SoC równe 0 (dolna granica)."""
        result = InputValidator.validate_soc(0)
        assert result == 0

    def test_valid_soc_max(self):
        """SoC równe 100 (górna granica)."""
        result = InputValidator.validate_soc(100)
        assert result == 100

    def test_valid_soc_mid(self):
        """SoC w środku zakresu."""
        result = InputValidator.validate_soc(50)
        assert result == 50

    def test_valid_soc_from_string(self):
        """SoC jako string konwertowany na int."""
        result = InputValidator.validate_soc("80")
        assert result == 80

    def test_invalid_soc_none(self):
        """None powinno zgłosić ValueError."""
        with pytest.raises(ValueError, match="wartość nie może być pusta"):
            InputValidator.validate_soc(None)

    def test_invalid_soc_negative(self):
        """SoC ujemne poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_soc(-1)

    def test_invalid_soc_too_high(self):
        """SoC powyżej 100 poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_soc(101)

    def test_invalid_soc_not_numeric(self):
        """Wartość nieliczbowa."""
        with pytest.raises(ValueError, match="wymagana liczba całkowita"):
            InputValidator.validate_soc("abc")


class TestValidatePower:
    """Testy walidacji mocy."""

    def test_valid_power_zero(self):
        """Moc równa 0 (dolna granica)."""
        result = InputValidator.validate_power(0)
        assert result == 0.0

    def test_valid_power_max(self):
        """Moc równa 100 (górna granica)."""
        result = InputValidator.validate_power(100)
        assert result == 100.0

    def test_valid_power_float(self):
        """Moc jako float."""
        result = InputValidator.validate_power(11.5)
        assert result == 11.5

    def test_valid_power_from_string(self):
        """Moc jako string konwertowany na float."""
        result = InputValidator.validate_power("22.0")
        assert result == 22.0

    def test_invalid_power_none(self):
        """None powinno zgłosić ValueError."""
        with pytest.raises(ValueError, match="wartość nie może być pusta"):
            InputValidator.validate_power(None)

    def test_invalid_power_negative(self):
        """Moc ujemna poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_power(-0.1)

    def test_invalid_power_too_high(self):
        """Moc powyżej 100 kW poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_power(100.1)

    def test_invalid_power_not_numeric(self):
        """Wartość nieliczbowa."""
        with pytest.raises(ValueError, match="wymagana wartość liczbowa"):
            InputValidator.validate_power("xyz")


class TestValidateRate:
    """Testy walidacji stawki taryfowej."""

    def test_valid_rate_zero(self):
        """Stawka równa 0 (dolna granica)."""
        result = InputValidator.validate_rate(0)
        assert result == Decimal("0")

    def test_valid_rate_max(self):
        """Stawka równa 5 (górna granica)."""
        result = InputValidator.validate_rate(5)
        assert result == Decimal("5")

    def test_valid_rate_decimal(self):
        """Stawka jako Decimal."""
        result = InputValidator.validate_rate(Decimal("0.75"))
        assert result == Decimal("0.75")

    def test_valid_rate_from_string(self):
        """Stawka jako string."""
        result = InputValidator.validate_rate("2.35")
        assert result == Decimal("2.35")

    def test_invalid_rate_none(self):
        """None powinno zgłosić ValueError."""
        with pytest.raises(ValueError, match="wartość nie może być pusta"):
            InputValidator.validate_rate(None)

    def test_invalid_rate_negative(self):
        """Stawka ujemna poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_rate(-0.01)

    def test_invalid_rate_too_high(self):
        """Stawka powyżej 5 PLN/kWh poza zakresem."""
        with pytest.raises(ValueError, match="poza dozwolonym zakresem"):
            InputValidator.validate_rate(5.01)

    def test_invalid_rate_not_numeric(self):
        """Wartość nieliczbowa."""
        with pytest.raises(ValueError, match="wymagana wartość liczbowa"):
            InputValidator.validate_rate("abc")
