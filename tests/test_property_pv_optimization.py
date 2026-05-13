"""Property-based tests for PV optimization (Properties 15, 16, 17, 18).

**Validates: Requirements 5.2, 5.3, 5.4, 5.6, 5.10**

Property 15: Obliczanie profilu nadwyżki PV
Property 16: Decyzja o trybie baterii
Property 17: Ograniczenie nocnego ładowania przy dużej prognozie PV
Property 18: Bezpieczeństwo minimalnego SoC baterii
"""

from datetime import datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    decimals,
    floats,
    integers,
    lists,
    booleans,
)

from custom_components.peo.pv_optimizer import PVOptimizer
from custom_components.peo.models import (
    BatteryConfig,
    BatteryStrategy,
    HourlyCost,
    HourlyPVForecast,
    TariffRates,
)
from custom_components.peo.enums import BatteryMode, TimeZoneName

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

BASE_TIME = datetime(2024, 6, 15, 0, 0)


# --- Strategies ---


@composite
def pv_forecast_strategy(draw, min_hours=1, max_hours=24):
    """Generate a list of HourlyPVForecast objects for up to 24 hours.

    Production values are realistic PV outputs (0-15 kWh per hour).
    """
    n_hours = draw(integers(min_value=min_hours, max_value=max_hours))
    # Choose which hours have PV production (typically daylight hours)
    forecasts = []
    used_hours = set()
    for i in range(n_hours):
        hour = draw(integers(min_value=0, max_value=23))
        if hour in used_hours:
            continue
        used_hours.add(hour)
        production = draw(floats(
            min_value=0.0, max_value=15.0,
            allow_nan=False, allow_infinity=False,
        ))
        forecasts.append(HourlyPVForecast(
            hour=hour,
            timestamp=BASE_TIME + timedelta(hours=hour),
            production_kwh=production,
        ))
    return forecasts


@composite
def pv_forecast_full_day_strategy(draw):
    """Generate PV forecast for all 24 hours (one entry per hour)."""
    forecasts = []
    for hour in range(24):
        production = draw(floats(
            min_value=0.0, max_value=15.0,
            allow_nan=False, allow_infinity=False,
        ))
        forecasts.append(HourlyPVForecast(
            hour=hour,
            timestamp=BASE_TIME + timedelta(hours=hour),
            production_kwh=production,
        ))
    return forecasts


@composite
def consumption_profile_strategy(draw):
    """Generate a 24-hour average consumption profile.

    Values represent average hourly consumption in kWh (0.1-5.0 kWh/h).
    """
    profile = []
    for _ in range(24):
        consumption = draw(floats(
            min_value=0.1, max_value=5.0,
            allow_nan=False, allow_infinity=False,
        ))
        profile.append(round(consumption, 2))
    return profile


@composite
def battery_config_strategy(draw):
    """Generate a valid BatteryConfig."""
    capacity = draw(floats(
        min_value=2.0, max_value=50.0,
        allow_nan=False, allow_infinity=False,
    ))
    max_charge = draw(floats(
        min_value=1.0, max_value=min(25.0, capacity),
        allow_nan=False, allow_infinity=False,
    ))
    max_discharge = draw(floats(
        min_value=1.0, max_value=min(25.0, capacity),
        allow_nan=False, allow_infinity=False,
    ))
    min_soc = draw(integers(min_value=5, max_value=30))
    degradation = draw(decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("0.50"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))

    return BatteryConfig(
        capacity_kwh=round(capacity, 1),
        max_charge_power_kw=round(max_charge, 1),
        max_discharge_power_kw=round(max_discharge, 1),
        min_soc_percent=min_soc,
        degradation_cost_pln_kwh=degradation,
        inverter_entity_id="sensor.inverter_power",
        soc_entity_id="sensor.battery_soc",
    )


@composite
def hourly_costs_24h_strategy(draw):
    """Generate 24 HourlyCost objects for a full day."""
    costs = []
    for hour in range(24):
        cost_val = draw(decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("2.00"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        ))
        costs.append(HourlyCost(
            hour=hour,
            timestamp=BASE_TIME + timedelta(hours=hour),
            cost_pln_kwh=cost_val,
            zone=TimeZoneName.POZASZCZYT,
            components=TariffRates(
                energy_price=cost_val,
                distribution_variable=Decimal("0.00"),
                transition_fee=Decimal("0.00"),
                oze_fee=Decimal("0.00"),
                capacity_fee=Decimal("0.00"),
                cogeneration_fee=Decimal("0.00"),
            ),
        ))
    return costs


# --- Property 15 Tests ---


class TestProperty15SurplusProfile:
    """Property 15: Obliczanie profilu nadwyżki PV.

    Dla dowolnej prognozy produkcji PV i średniego profilu zużycia,
    obliczony profil nadwyżki powinien być równy różnicy
    (produkcja - zużycie) dla każdej godziny.

    **Validates: Requirements 5.2**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        pv_forecast=pv_forecast_full_day_strategy(),
        avg_consumption=consumption_profile_strategy(),
    )
    def test_surplus_equals_production_minus_consumption(
        self, pv_forecast, avg_consumption
    ):
        """surplus[h] = pv_production[h] - avg_consumption[h] for all hours.

        **Validates: Requirements 5.2**
        """
        optimizer = PVOptimizer()
        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert len(surplus) == 24, f"Expected 24 values, got {len(surplus)}"

        # Build expected PV by hour
        pv_by_hour = {}
        for f in pv_forecast:
            if f.hour in pv_by_hour:
                pv_by_hour[f.hour] += f.production_kwh
            else:
                pv_by_hour[f.hour] = f.production_kwh

        for hour in range(24):
            expected_production = pv_by_hour.get(hour, 0.0)
            expected_consumption = avg_consumption[hour]
            expected_surplus = expected_production - expected_consumption

            assert abs(surplus[hour] - expected_surplus) < 1e-9, (
                f"Hour {hour}: surplus={surplus[hour]}, "
                f"expected={expected_surplus} "
                f"(production={expected_production}, consumption={expected_consumption})"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        pv_forecast=pv_forecast_strategy(min_hours=0, max_hours=12),
        avg_consumption=consumption_profile_strategy(),
    )
    def test_surplus_profile_always_24_elements(self, pv_forecast, avg_consumption):
        """Surplus profile always has exactly 24 elements regardless of input size.

        **Validates: Requirements 5.2**
        """
        optimizer = PVOptimizer()
        surplus = optimizer.calculate_surplus_profile(pv_forecast, avg_consumption)

        assert len(surplus) == 24, (
            f"Expected 24 elements, got {len(surplus)} "
            f"(pv_forecast had {len(pv_forecast)} entries)"
        )

    @PROPERTY_TEST_SETTINGS
    @given(avg_consumption=consumption_profile_strategy())
    def test_surplus_negative_when_no_pv(self, avg_consumption):
        """When there is no PV production, surplus should be negative (deficit).

        **Validates: Requirements 5.2**
        """
        optimizer = PVOptimizer()
        surplus = optimizer.calculate_surplus_profile([], avg_consumption)

        for hour in range(24):
            expected = -avg_consumption[hour]
            assert abs(surplus[hour] - expected) < 1e-9, (
                f"Hour {hour}: surplus={surplus[hour]}, expected={expected} "
                f"(no PV, consumption={avg_consumption[hour]})"
            )


# --- Property 16 Tests ---


class TestProperty16BatteryModeDecision:
    """Property 16: Decyzja o trybie baterii.

    Dla dowolnej kombinacji ceny energii z sieci i kosztu degradacji baterii:
    - jeśli current_soc <= min_soc → STANDBY (bezpieczeństwo)
    - jeśli cena < koszt degradacji → CHARGE (tanie ładowanie z sieci)
    - jeśli cena > (koszt degradacji + wartość PV do zmagazynowania) → DISCHARGE
    - w przeciwnym razie → STANDBY

    **Validates: Requirements 5.3, 5.4**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        grid_price=decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        degradation_cost=decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("1.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_soc=floats(
            min_value=5.0, max_value=30.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_standby_when_soc_at_minimum(self, grid_price, degradation_cost, min_soc):
        """When current_soc <= min_soc, battery mode is STANDBY (safety threshold).

        **Validates: Requirements 5.3, 5.4**
        """
        optimizer = PVOptimizer()

        # Test with current_soc exactly at min_soc
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=0.0,
            current_soc=min_soc,
            min_soc=min_soc,
        )
        assert mode == BatteryMode.STANDBY, (
            f"Expected STANDBY when current_soc ({min_soc}) == min_soc ({min_soc}), "
            f"got {mode}"
        )

        # Test with current_soc below min_soc
        below_soc = min_soc - 1.0
        if below_soc >= 0:
            mode_below = optimizer.determine_battery_mode(
                grid_price=grid_price,
                degradation_cost=degradation_cost,
                pv_available=0.0,
                current_soc=below_soc,
                min_soc=min_soc,
            )
            assert mode_below == BatteryMode.STANDBY, (
                f"Expected STANDBY when current_soc ({below_soc}) < min_soc ({min_soc}), "
                f"got {mode_below}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        degradation_cost=decimals(
            min_value=Decimal("0.20"),
            max_value=Decimal("1.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        current_soc=floats(
            min_value=40.0, max_value=95.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_charge_when_grid_price_below_degradation_cost(
        self, degradation_cost, current_soc
    ):
        """When grid_price < degradation_cost and SoC > min_soc, mode is CHARGE.

        **Validates: Requirements 5.3**
        """
        # Grid price clearly below degradation cost
        grid_price = degradation_cost - Decimal("0.01")
        assume(grid_price > Decimal("0.00"))

        optimizer = PVOptimizer()
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=0.0,
            current_soc=current_soc,
            min_soc=10.0,
        )

        assert mode == BatteryMode.CHARGE, (
            f"Expected CHARGE when grid_price ({grid_price}) < "
            f"degradation_cost ({degradation_cost}), got {mode}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        degradation_cost=decimals(
            min_value=Decimal("0.05"),
            max_value=Decimal("0.50"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        current_soc=floats(
            min_value=40.0, max_value=95.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_discharge_when_grid_price_above_threshold(
        self, degradation_cost, current_soc
    ):
        """When grid_price > discharge_threshold and SoC > min_soc, mode is DISCHARGE.

        With no PV available, discharge_threshold = degradation_cost.
        So grid_price > degradation_cost → DISCHARGE.

        **Validates: Requirements 5.4**
        """
        # Grid price clearly above degradation cost (no PV available)
        grid_price = degradation_cost + Decimal("0.10")

        optimizer = PVOptimizer()
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=0.0,
            current_soc=current_soc,
            min_soc=10.0,
        )

        assert mode == BatteryMode.DISCHARGE, (
            f"Expected DISCHARGE when grid_price ({grid_price}) > "
            f"degradation_cost ({degradation_cost}) with no PV, got {mode}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        grid_price=decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        degradation_cost=decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        pv_available=floats(
            min_value=0.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
        current_soc=floats(
            min_value=40.0, max_value=95.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_mode_priority_min_soc_first(
        self, grid_price, degradation_cost, pv_available, current_soc
    ):
        """Min SoC safety check has highest priority in mode decision.

        Regardless of price conditions, if current_soc <= min_soc → STANDBY.

        **Validates: Requirements 5.3, 5.4**
        """
        min_soc = current_soc + 5.0  # Ensure current_soc < min_soc
        assume(min_soc <= 100.0)

        optimizer = PVOptimizer()
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=pv_available,
            current_soc=current_soc,
            min_soc=min_soc,
        )

        assert mode == BatteryMode.STANDBY, (
            f"Expected STANDBY when current_soc ({current_soc}) < min_soc ({min_soc}), "
            f"regardless of price ({grid_price}) vs degradation ({degradation_cost}), "
            f"got {mode}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        grid_price=decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        degradation_cost=decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        pv_available=floats(
            min_value=0.0, max_value=10.0,
            allow_nan=False, allow_infinity=False,
        ),
        current_soc=floats(
            min_value=40.0, max_value=95.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_mode_is_always_valid_battery_mode(
        self, grid_price, degradation_cost, pv_available, current_soc
    ):
        """The returned mode is always a valid BatteryMode enum value.

        **Validates: Requirements 5.3, 5.4**
        """
        optimizer = PVOptimizer()
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=pv_available,
            current_soc=current_soc,
            min_soc=10.0,
        )

        assert mode in (BatteryMode.CHARGE, BatteryMode.DISCHARGE, BatteryMode.STANDBY), (
            f"Invalid battery mode: {mode}"
        )


# --- Property 17 Tests ---


class TestProperty17NightChargingLimitation:
    """Property 17: Ograniczenie nocnego ładowania przy dużej prognozie PV.

    Dla dowolnej prognozy PV przekraczającej dzienne zużycie bazowe,
    nocne ładowanie baterii z sieci powinno być ograniczone do poziomu SoC
    pozostawiającego co najmniej pojemność równą prognozowanej nadwyżce PV
    (nie mniej niż skonfigurowany minimalny SoC).

    **Validates: Requirements 5.6**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        battery=battery_config_strategy(),
        costs=hourly_costs_24h_strategy(),
    )
    def test_target_soc_below_100_when_pv_exceeds_consumption(self, battery, costs):
        """When PV production > daily consumption, target SoC should be < 100%.

        This ensures capacity is reserved for PV surplus storage.

        **Validates: Requirements 5.6**
        """
        # Create a scenario where PV clearly exceeds consumption
        # High PV production during daylight hours
        pv_forecast = []
        for hour in range(6, 18):  # 12 hours of PV
            pv_forecast.append(HourlyPVForecast(
                hour=hour,
                timestamp=BASE_TIME + timedelta(hours=hour),
                production_kwh=5.0,  # 5 kWh/h * 12h = 60 kWh total
            ))

        # Low consumption profile (total ~24 kWh/day)
        consumption_profile = [1.0] * 24  # 1 kWh/h * 24h = 24 kWh total

        # Total PV = 60 kWh > Total consumption = 24 kWh
        total_pv = sum(f.production_kwh for f in pv_forecast)
        total_consumption = sum(consumption_profile)
        assume(total_pv > total_consumption)

        optimizer = PVOptimizer()
        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery,
            consumption_profile=consumption_profile,
        )

        assert strategy.target_soc < 100, (
            f"Expected target_soc < 100% when PV ({total_pv} kWh) > "
            f"consumption ({total_consumption} kWh), got {strategy.target_soc}%"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        battery=battery_config_strategy(),
        costs=hourly_costs_24h_strategy(),
        pv_multiplier=floats(
            min_value=1.5, max_value=5.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_target_soc_leaves_room_for_pv_surplus(self, battery, costs, pv_multiplier):
        """When PV > consumption, target SoC leaves capacity for PV surplus.

        **Validates: Requirements 5.6**
        """
        # Create consumption profile
        consumption_profile = [1.0] * 24  # 24 kWh total
        total_consumption = 24.0

        # PV production exceeds consumption by multiplier
        total_pv_target = total_consumption * pv_multiplier
        pv_per_hour = total_pv_target / 12.0  # Spread over 12 daylight hours

        pv_forecast = []
        for hour in range(6, 18):
            pv_forecast.append(HourlyPVForecast(
                hour=hour,
                timestamp=BASE_TIME + timedelta(hours=hour),
                production_kwh=pv_per_hour,
            ))

        optimizer = PVOptimizer()
        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery,
            consumption_profile=consumption_profile,
        )

        # Target SoC should be less than 100% to leave room for PV
        assert strategy.target_soc < 100, (
            f"Expected target_soc < 100% when PV ({total_pv_target:.1f} kWh) > "
            f"consumption ({total_consumption} kWh) by factor {pv_multiplier:.1f}, "
            f"got {strategy.target_soc}%"
        )

        # Target SoC should still be >= min_soc
        effective_min_soc = max(5, min(30, battery.min_soc_percent))
        assert strategy.target_soc >= effective_min_soc, (
            f"Target SoC ({strategy.target_soc}%) should be >= "
            f"min_soc ({effective_min_soc}%)"
        )


# --- Property 18 Tests ---


class TestProperty18MinimumSoCSafety:
    """Property 18: Bezpieczeństwo minimalnego SoC baterii.

    Dla dowolnego scenariusza rozładowania baterii, SoC nie powinien nigdy
    spaść poniżej skonfigurowanego minimalnego poziomu bezpieczeństwa —
    system powinien przełączyć baterię w tryb oczekiwania przed osiągnięciem
    tego progu.

    **Validates: Requirements 5.10**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        battery=battery_config_strategy(),
        costs=hourly_costs_24h_strategy(),
        pv_forecast=pv_forecast_full_day_strategy(),
        avg_consumption=consumption_profile_strategy(),
    )
    def test_target_soc_never_below_min_soc(
        self, battery, costs, pv_forecast, avg_consumption
    ):
        """target_soc >= min_soc_percent always, regardless of scenario.

        **Validates: Requirements 5.10**
        """
        optimizer = PVOptimizer()
        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery,
            consumption_profile=avg_consumption,
        )

        # min_soc is clamped to MIN_SOC_RANGE (5-30)
        effective_min_soc = max(5, min(30, battery.min_soc_percent))

        assert strategy.target_soc >= effective_min_soc, (
            f"target_soc ({strategy.target_soc}%) is below min_soc "
            f"({effective_min_soc}%) for battery config: "
            f"capacity={battery.capacity_kwh}, min_soc_percent={battery.min_soc_percent}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        min_soc_percent=integers(min_value=5, max_value=30),
        grid_price=decimals(
            min_value=Decimal("0.50"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        degradation_cost=decimals(
            min_value=Decimal("0.05"),
            max_value=Decimal("0.30"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_standby_at_min_soc_prevents_discharge(
        self, min_soc_percent, grid_price, degradation_cost
    ):
        """Battery switches to STANDBY at min_soc, preventing further discharge.

        Even when grid price is high (favorable for discharge), if SoC is at
        or below min_soc, the mode must be STANDBY.

        **Validates: Requirements 5.10**
        """
        optimizer = PVOptimizer()

        # Test at exactly min_soc
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=0.0,
            current_soc=float(min_soc_percent),
            min_soc=float(min_soc_percent),
        )

        assert mode == BatteryMode.STANDBY, (
            f"Expected STANDBY at min_soc ({min_soc_percent}%), "
            f"even with high grid_price ({grid_price}), got {mode}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        min_soc_percent=integers(min_value=5, max_value=30),
        soc_below_min=floats(
            min_value=0.0, max_value=4.9,
            allow_nan=False, allow_infinity=False,
        ),
        grid_price=decimals(
            min_value=Decimal("0.50"),
            max_value=Decimal("3.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        degradation_cost=decimals(
            min_value=Decimal("0.05"),
            max_value=Decimal("0.30"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_standby_below_min_soc(
        self, min_soc_percent, soc_below_min, grid_price, degradation_cost
    ):
        """Battery is always STANDBY when SoC is below min_soc.

        **Validates: Requirements 5.10**
        """
        current_soc = min_soc_percent - soc_below_min - 0.1
        assume(current_soc >= 0.0)

        optimizer = PVOptimizer()
        mode = optimizer.determine_battery_mode(
            grid_price=grid_price,
            degradation_cost=degradation_cost,
            pv_available=0.0,
            current_soc=current_soc,
            min_soc=float(min_soc_percent),
        )

        assert mode == BatteryMode.STANDBY, (
            f"Expected STANDBY when current_soc ({current_soc}%) < "
            f"min_soc ({min_soc_percent}%), got {mode}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        battery=battery_config_strategy(),
        costs=hourly_costs_24h_strategy(),
    )
    def test_strategy_target_soc_respects_min_soc_with_no_pv(self, battery, costs):
        """Even with no PV production, target_soc >= min_soc.

        **Validates: Requirements 5.10**
        """
        # No PV production at all
        pv_forecast = []
        consumption_profile = [2.0] * 24  # Moderate consumption

        optimizer = PVOptimizer()
        strategy = optimizer.calculate_battery_strategy(
            pv_forecast=pv_forecast,
            costs=costs,
            battery=battery,
            consumption_profile=consumption_profile,
        )

        effective_min_soc = max(5, min(30, battery.min_soc_percent))

        assert strategy.target_soc >= effective_min_soc, (
            f"target_soc ({strategy.target_soc}%) below min_soc "
            f"({effective_min_soc}%) with no PV production"
        )
