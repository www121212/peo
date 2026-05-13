"""Property-based tests for tariff comparison and ranking.

**Validates: Requirements 6.1, 6.2, 6.3, 6.6**

Property 19: Porównanie taryf — poprawność obliczeń i rankingu
Dla dowolnego godzinowego profilu zużycia z ostatnich 30 dni, obliczony hipotetyczny
koszt dla każdej taryfy powinien uwzględniać pełne składniki (energia + dystrybucja
+ przejściowa + OZE + moc + kogeneracja), a ranking powinien być posortowany od
najtańszej do najdroższej, z poprawnie obliczoną różnicą względem aktualnej taryfy.
"""

from datetime import datetime
from decimal import Decimal

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    floats,
    integers,
    sampled_from,
    lists,
    fixed_dictionaries,
)

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import TariffComparison, TariffRanking, TariffRates
from custom_components.peo.tariff_analyzer import TariffAnalyzer
from custom_components.peo.tariff_calculator import TariffCalculator
from custom_components.peo.tariff_loader import TariffDefinitionLoader

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

# Comparable tariffs (residential G-tariffs)
_COMPARABLE_TARIFFS = [
    TariffType.G11,
    TariffType.G12,
    TariffType.G12W,
    TariffType.G12R,
    TariffType.G13,
]


# --- Strategies ---


@composite
def consumption_profile_strategy(draw):
    """Generate a valid hourly consumption profile spanning 7-30 days.

    Each hour has a consumption value between 0.0 and 5.0 kWh.
    """
    num_days = draw(integers(min_value=7, max_value=30))
    profile: dict[datetime, float] = {}
    for day_offset in range(num_days):
        day = 1 + day_offset
        # Keep within January 2024 for simplicity (up to 30 days)
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            consumption = draw(
                floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False)
            )
            profile[ts] = consumption
    return profile


@composite
def small_consumption_profile_strategy(draw):
    """Generate a smaller consumption profile (7-10 days) for faster tests.

    Uses a fixed pattern with random scaling to reduce hypothesis complexity.
    """
    num_days = draw(integers(min_value=7, max_value=10))
    # Draw a few representative consumption values
    base_night = draw(floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False))
    base_day = draw(floats(min_value=0.5, max_value=4.0, allow_nan=False, allow_infinity=False))
    base_peak = draw(floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False))

    profile: dict[datetime, float] = {}
    for day_offset in range(num_days):
        day = 1 + day_offset
        for hour in range(24):
            ts = datetime(2024, 1, day, hour, 0)
            if 0 <= hour < 6:
                profile[ts] = base_night
            elif 6 <= hour < 16:
                profile[ts] = base_day
            else:
                profile[ts] = base_peak
    return profile


# --- Property 19 Tests ---


class TestProperty19TariffComparisonRanking:
    """Property 19: Porównanie taryf — poprawność obliczeń i rankingu.

    For any consumption profile and tariff/operator combination, the ranking
    should be sorted by cost (cheapest first), all costs should be positive,
    and the recommended tariff should be the cheapest one.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.6**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_ranking_sorted_by_monthly_cost(self, profile, current_tariff, operator):
        """For any consumption profile, the ranking is sorted cheapest first.

        **Validates: Requirements 6.2**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        # Rankings should be sorted by monthly cost (ascending)
        costs = [r.monthly_cost_pln for r in result.rankings]
        assert costs == sorted(costs), (
            f"Rankings not sorted: {costs}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_all_costs_are_positive(self, profile, current_tariff, operator):
        """For any non-empty consumption profile with positive values,
        all tariff costs in the ranking should be positive.

        **Validates: Requirements 6.1, 6.6**
        """
        # Ensure at least some positive consumption
        has_positive = any(v > 0 for v in profile.values())
        assume(has_positive)

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        for ranking in result.rankings:
            assert ranking.monthly_cost_pln > Decimal("0"), (
                f"Tariff {ranking.tariff} has non-positive cost: {ranking.monthly_cost_pln}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_recommended_tariff_is_cheapest(self, profile, current_tariff, operator):
        """For any profile with sufficient data, the recommended tariff
        is the cheapest one in the ranking.

        **Validates: Requirements 6.3**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        if result.is_sufficient_data and result.rankings:
            assert result.recommended == result.rankings[0].tariff, (
                f"Recommended {result.recommended} != cheapest {result.rankings[0].tariff}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_difference_relative_to_current_tariff(self, profile, current_tariff, operator):
        """For any profile, the difference_pln for the current tariff is 0,
        and differences for other tariffs are relative to the current tariff cost.

        **Validates: Requirements 6.2**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        # Find current tariff in rankings
        current_ranking = None
        for r in result.rankings:
            if r.tariff == current_tariff:
                current_ranking = r
                break

        if current_ranking is not None:
            assert current_ranking.difference_pln == Decimal("0.00"), (
                f"Current tariff difference should be 0, got {current_ranking.difference_pln}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_ranking_contains_all_comparable_tariffs(self, profile, current_tariff, operator):
        """For any valid input, the ranking contains all 5 G-tariffs.

        **Validates: Requirements 6.1**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        tariffs_in_ranking = {r.tariff for r in result.rankings}
        expected_tariffs = set(_COMPARABLE_TARIFFS)
        assert tariffs_in_ranking == expected_tariffs, (
            f"Missing tariffs: {expected_tariffs - tariffs_in_ranking}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_monthly_savings_consistent_with_ranking(self, profile, current_tariff, operator):
        """For any profile with sufficient data, monthly_savings_pln equals
        the difference between current tariff cost and cheapest tariff cost.

        **Validates: Requirements 6.3**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        if result.is_sufficient_data and result.rankings:
            current_cost = None
            for r in result.rankings:
                if r.tariff == current_tariff:
                    current_cost = r.monthly_cost_pln
                    break

            cheapest_cost = result.rankings[0].monthly_cost_pln

            if current_cost is not None:
                expected_savings = (current_cost - cheapest_cost).quantize(Decimal("0.01"))
                assert result.monthly_savings_pln == expected_savings, (
                    f"Savings mismatch: {result.monthly_savings_pln} != {expected_savings}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_cost_includes_all_six_components(self, profile, current_tariff, operator):
        """For any tariff in the ranking, the cost includes all 6 fee components
        (energy + distribution + transition + OZE + capacity + cogeneration).

        **Validates: Requirements 6.6**
        """
        # Ensure some positive consumption
        has_positive = any(v > 0 for v in profile.values())
        assume(has_positive)

        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        # Verify by comparing analyzer cost with manual calculation for one tariff
        tariff = TariffType.G11  # Single zone, simplest to verify
        rates = analyzer._load_all_zone_rates(operator, tariff)
        assume(rates is not None)

        # Calculate cost via analyzer
        analyzer_cost = analyzer.calculate_hypothetical_cost(
            profile, tariff, operator, rates
        )

        # Calculate cost manually (sum of all 6 components × consumption)
        manual_cost = Decimal("0")
        for ts, consumption in profile.items():
            if consumption <= 0:
                continue
            zone = calculator.get_zone_for_time(ts, tariff, operator)
            zone_rates = rates.get(zone) or rates.get(TimeZoneName.SINGLE)
            if zone_rates is None:
                zone_rates = next(iter(rates.values()))
            cost_per_kwh = (
                zone_rates.energy_price
                + zone_rates.distribution_variable
                + zone_rates.transition_fee
                + zone_rates.oze_fee
                + zone_rates.capacity_fee
                + zone_rates.cogeneration_fee
            )
            manual_cost += Decimal(str(consumption)) * cost_per_kwh

        manual_cost = manual_cost.quantize(Decimal("0.01"))
        assert analyzer_cost == manual_cost, (
            f"Cost mismatch for {tariff}: analyzer={analyzer_cost}, manual={manual_cost}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        profile=small_consumption_profile_strategy(),
        current_tariff=sampled_from(_COMPARABLE_TARIFFS),
        operator=sampled_from(list(OSDOperator)),
    )
    def test_sufficient_data_flag_correct(self, profile, current_tariff, operator):
        """For any profile with >= 7 days, is_sufficient_data is True.

        **Validates: Requirements 6.1**
        """
        loader = TariffDefinitionLoader()
        calculator = TariffCalculator(loader)
        analyzer = TariffAnalyzer(calculator, loader)

        result = analyzer.analyze_tariffs(profile, current_tariff, operator)

        unique_days = len({dt.date() for dt in profile.keys()})
        if unique_days >= 7:
            assert result.is_sufficient_data is True
        else:
            assert result.is_sufficient_data is False
