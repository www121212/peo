"""Property-based tests for price parsing, statistics, and validation.

**Validates: Requirements 1.2, 1.3, 1.8, 9.1, 9.2**

Property 1: Parsowanie i statystyki cen RCE
Dla dowolnej poprawnej odpowiedzi API RCE PSE zawierającej 24 wartości cenowych
w zakresie 0–5000 PLN/MWh, parsowanie powinno wyprodukować dokładnie 24 obiektów
HourlyPrice, a obliczone statystyki (min, max, średnia) powinny być matematycznie
poprawne względem tych 24 wartości.

Property 2: Walidacja danych wejściowych odrzuca nieprawidłowe dane
Dla dowolnej odpowiedzi API zawierającej mniej niż 24 wartości godzinowych LUB
zawierającej wartości spoza zakresu 0–5000 PLN/MWh LUB zawierającej nieprawidłowe
typy danych lub brakujące wymagane pola, walidator powinien odrzucić cały zestaw
danych.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    floats,
    lists,
    composite,
    just,
    one_of,
    none,
    text,
    sampled_from,
    booleans,
)

from custom_components.peo.models import HourlyPrice, PriceStats
from custom_components.peo.price_validator import PriceValidator
from custom_components.peo.rce_client import RCEApiClient

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

# Constants
PRICE_MIN = 0
PRICE_MAX = 5000
HOURS_PER_DAY = 24
MWH_TO_KWH_DIVISOR = Decimal("1000")


# --- Helper Functions ---


def compute_price_stats(prices: list[HourlyPrice]) -> PriceStats:
    """Compute PriceStats from a list of HourlyPrice objects.

    Calculates min, max, avg prices and the hours at which min/max occur.
    """
    min_price = min(p.price_pln_mwh for p in prices)
    max_price = max(p.price_pln_mwh for p in prices)
    avg_price = sum(p.price_pln_mwh for p in prices) / len(prices)
    min_hour = next(p.hour for p in prices if p.price_pln_mwh == min_price)
    max_hour = next(p.hour for p in prices if p.price_pln_mwh == max_price)

    return PriceStats(
        min_price=min_price,
        max_price=max_price,
        avg_price=avg_price,
        min_hour=min_hour,
        max_hour=max_hour,
    )


def make_hourly_price(hour: int, price_mwh: Decimal, target_date: date) -> HourlyPrice:
    """Create an HourlyPrice object with proper PLN/kWh conversion."""
    price_kwh = (price_mwh / MWH_TO_KWH_DIVISOR).quantize(
        Decimal("0.000001"), rounding=ROUND_HALF_UP
    )
    return HourlyPrice(
        hour=hour,
        price_pln_mwh=price_mwh,
        price_pln_kwh=price_kwh,
        date=target_date,
    )


# --- Strategies ---


@composite
def valid_price_values(draw):
    """Generate a valid price value in range [0, 5000] PLN/MWh as Decimal."""
    # Use floats for variety, then convert to Decimal with 2 decimal places
    value = draw(
        floats(
            min_value=0.0,
            max_value=5000.0,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    return Decimal(str(round(value, 2)))


@composite
def valid_24_price_list(draw):
    """Generate a valid list of 24 price values in [0, 5000] PLN/MWh."""
    prices = [draw(valid_price_values()) for _ in range(HOURS_PER_DAY)]
    return prices


@composite
def valid_api_response(draw):
    """Generate a valid API response dict with 24 hourly price records."""
    prices = draw(valid_24_price_list())
    target_date = date(2024, 1, 15)

    records = []
    for hour_idx in range(HOURS_PER_DAY):
        records.append({
            "rce_pln": float(prices[hour_idx]),
            "business_date": target_date.isoformat(),
            "udtczas": str(hour_idx + 1),  # API uses 1-24
        })

    return {"value": records}, target_date, prices


@composite
def too_few_prices(draw):
    """Generate a list with fewer than 24 HourlyPrice objects."""
    count = draw(integers(min_value=0, max_value=23))
    target_date = date(2024, 1, 15)
    prices = []
    for h in range(count):
        price_mwh = draw(valid_price_values())
        prices.append(make_hourly_price(h, price_mwh, target_date))
    return prices


@composite
def too_many_prices(draw):
    """Generate a list with more than 24 HourlyPrice objects."""
    count = draw(integers(min_value=25, max_value=50))
    target_date = date(2024, 1, 15)
    prices = []
    for h in range(count):
        price_mwh = draw(valid_price_values())
        prices.append(make_hourly_price(h % 24, price_mwh, target_date))
    return prices


@composite
def prices_with_value_below_range(draw):
    """Generate 24 HourlyPrice objects where at least one has price < 0."""
    target_date = date(2024, 1, 15)
    bad_hour = draw(integers(min_value=0, max_value=23))
    bad_value = draw(
        floats(min_value=-5000.0, max_value=-0.01, allow_nan=False, allow_infinity=False)
    )

    prices = []
    for h in range(HOURS_PER_DAY):
        if h == bad_hour:
            price_mwh = Decimal(str(round(bad_value, 2)))
        else:
            price_mwh = draw(valid_price_values())
        prices.append(make_hourly_price(h, price_mwh, target_date))
    return prices


@composite
def prices_with_value_above_range(draw):
    """Generate 24 HourlyPrice objects where at least one has price > 5000."""
    target_date = date(2024, 1, 15)
    bad_hour = draw(integers(min_value=0, max_value=23))
    bad_value = draw(
        floats(min_value=5000.01, max_value=50000.0, allow_nan=False, allow_infinity=False)
    )

    prices = []
    for h in range(HOURS_PER_DAY):
        if h == bad_hour:
            price_mwh = Decimal(str(round(bad_value, 2)))
        else:
            price_mwh = draw(valid_price_values())
        prices.append(make_hourly_price(h, price_mwh, target_date))
    return prices


@composite
def prices_with_wrong_types(draw):
    """Generate a list of 24 items where at least one is not an HourlyPrice."""
    target_date = date(2024, 1, 15)
    bad_index = draw(integers(min_value=0, max_value=23))

    # Generate invalid items of various types
    bad_item = draw(one_of(
        text(),
        integers(),
        just(None),
        just({"hour": 5, "price_pln_mwh": Decimal("100")}),
        just([1, 2, 3]),
    ))

    prices = []
    for h in range(HOURS_PER_DAY):
        if h == bad_index:
            prices.append(bad_item)
        else:
            price_mwh = draw(valid_price_values())
            prices.append(make_hourly_price(h, price_mwh, target_date))
    return prices


@composite
def valid_hourly_prices(draw):
    """Generate a valid list of 24 HourlyPrice objects."""
    target_date = date(2024, 1, 15)
    prices = []
    for h in range(HOURS_PER_DAY):
        price_mwh = draw(valid_price_values())
        prices.append(make_hourly_price(h, price_mwh, target_date))
    return prices


# --- Property 1 Tests ---


class TestProperty1PriceParsingAndStatistics:
    """Property 1: Parsowanie i statystyki cen RCE.

    **Validates: Requirements 1.2, 1.3**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_parsing_produces_exactly_24_hourly_prices(self, data):
        """For any valid API response with 24 price values in [0, 5000],
        parsing produces exactly 24 HourlyPrice objects.

        **Validates: Requirements 1.2**
        """
        api_response, target_date, _ = data

        # Use the RCEApiClient._parse_response method
        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        assert len(result) == HOURS_PER_DAY

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_parsed_hours_cover_0_to_23(self, data):
        """For any valid API response, parsed results cover all hours 0-23.

        **Validates: Requirements 1.2**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        hours = {p.hour for p in result}
        assert hours == set(range(HOURS_PER_DAY))

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_parsed_prices_match_input_values(self, data):
        """For any valid API response, parsed price_pln_mwh values match
        the input values from the API response.

        **Validates: Requirements 1.2**
        """
        api_response, target_date, input_prices = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        # Sort by hour for comparison
        result_sorted = sorted(result, key=lambda p: p.hour)

        for i, hp in enumerate(result_sorted):
            expected = Decimal(str(float(input_prices[i])))
            assert hp.price_pln_mwh == expected

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_statistics_min_is_correct(self, data):
        """For any valid parsed prices, min_price equals the minimum of all prices.

        **Validates: Requirements 1.3**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        stats = compute_price_stats(result)
        actual_min = min(p.price_pln_mwh for p in result)

        assert stats.min_price == actual_min

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_statistics_max_is_correct(self, data):
        """For any valid parsed prices, max_price equals the maximum of all prices.

        **Validates: Requirements 1.3**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        stats = compute_price_stats(result)
        actual_max = max(p.price_pln_mwh for p in result)

        assert stats.max_price == actual_max

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_statistics_avg_is_correct(self, data):
        """For any valid parsed prices, avg_price equals the arithmetic mean.

        **Validates: Requirements 1.3**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        stats = compute_price_stats(result)
        actual_avg = sum(p.price_pln_mwh for p in result) / HOURS_PER_DAY

        assert stats.avg_price == actual_avg

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_statistics_min_hour_has_min_price(self, data):
        """For any valid parsed prices, the hour reported as min_hour
        actually has the minimum price.

        **Validates: Requirements 1.3**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        stats = compute_price_stats(result)
        # The price at min_hour should equal min_price
        min_hour_price = next(
            p.price_pln_mwh for p in result if p.hour == stats.min_hour
        )
        assert min_hour_price == stats.min_price

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_statistics_max_hour_has_max_price(self, data):
        """For any valid parsed prices, the hour reported as max_hour
        actually has the maximum price.

        **Validates: Requirements 1.3**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        stats = compute_price_stats(result)
        # The price at max_hour should equal max_price
        max_hour_price = next(
            p.price_pln_mwh for p in result if p.hour == stats.max_hour
        )
        assert max_hour_price == stats.max_price

    @PROPERTY_TEST_SETTINGS
    @given(data=valid_api_response())
    def test_price_pln_kwh_conversion_correct(self, data):
        """For any valid parsed prices, price_pln_kwh == price_pln_mwh / 1000.

        **Validates: Requirements 1.2**
        """
        api_response, target_date, _ = data

        client = RCEApiClient.__new__(RCEApiClient)
        result = client._parse_response(api_response, target_date)

        for hp in result:
            expected_kwh = (hp.price_pln_mwh / MWH_TO_KWH_DIVISOR).quantize(
                Decimal("0.000001"), rounding=ROUND_HALF_UP
            )
            assert hp.price_pln_kwh == expected_kwh


# --- Property 2 Tests ---


class TestProperty2ValidationRejectsInvalidData:
    """Property 2: Walidacja danych wejściowych odrzuca nieprawidłowe dane.

    **Validates: Requirements 1.8, 9.1, 9.2**
    """

    @PROPERTY_TEST_SETTINGS
    @given(prices=too_few_prices())
    def test_rejects_fewer_than_24_values(self, prices):
        """For any list with fewer than 24 HourlyPrice objects,
        the validator rejects the entire dataset.

        **Validates: Requirements 1.8, 9.1**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is False

    @PROPERTY_TEST_SETTINGS
    @given(prices=too_many_prices())
    def test_rejects_more_than_24_values(self, prices):
        """For any list with more than 24 HourlyPrice objects,
        the validator rejects the entire dataset.

        **Validates: Requirements 1.8, 9.1**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is False

    @PROPERTY_TEST_SETTINGS
    @given(prices=prices_with_value_below_range())
    def test_rejects_values_below_zero(self, prices):
        """For any dataset containing a price < 0 PLN/MWh,
        the validator rejects the entire dataset.

        **Validates: Requirements 9.1, 9.2**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is False

    @PROPERTY_TEST_SETTINGS
    @given(prices=prices_with_value_above_range())
    def test_rejects_values_above_5000(self, prices):
        """For any dataset containing a price > 5000 PLN/MWh,
        the validator rejects the entire dataset.

        **Validates: Requirements 9.1, 9.2**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is False

    @PROPERTY_TEST_SETTINGS
    @given(prices=prices_with_wrong_types())
    def test_rejects_wrong_types(self, prices):
        """For any dataset containing items that are not HourlyPrice objects,
        the validator rejects the entire dataset.

        **Validates: Requirements 9.1**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is False

    @PROPERTY_TEST_SETTINGS
    @given(prices=valid_hourly_prices())
    def test_valid_data_always_passes(self, prices):
        """For any valid dataset with 24 HourlyPrice objects in range [0, 5000],
        the validator accepts the dataset.

        **Validates: Requirements 1.8, 9.1, 9.2**
        """
        validator = PriceValidator()
        assert validator.validate(prices) is True

    @PROPERTY_TEST_SETTINGS
    @given(
        invalid_input=one_of(
            none(),
            text(),
            integers(),
            just({}),
            just(3.14),
        )
    )
    def test_rejects_non_list_inputs(self, invalid_input):
        """For any input that is not a list, the validator rejects it.

        **Validates: Requirements 9.1**
        """
        validator = PriceValidator()
        assert validator.validate(invalid_input) is False
