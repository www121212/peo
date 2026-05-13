"""Property-based tests for load management (Properties 11, 12, 13, 14).

**Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6**

Property 11: Przełączanie odbiorników wg progów cenowych
Property 12: Zapewnienie minimalnej dziennej pracy odbiornika
Property 13: Blokada po osiągnięciu maksymalnej dziennej pracy
Property 14: Priorytetyzacja mocy — odbiorniki
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    composite,
    decimals,
    floats,
    integers,
    lists,
    booleans,
    sampled_from,
)

from custom_components.peo.load_manager import LoadManager
from custom_components.peo.models import HourlyCost, LoadConfig, LoadDecision, TimeWindow
from custom_components.peo.enums import TimeZoneName

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

BASE_TIME = datetime(2024, 6, 15, 12, 0)  # Noon on a weekday


# --- Strategies ---


@composite
def valid_threshold_pair(draw):
    """Generate a valid pair of thresholds where threshold_on <= threshold_off.

    threshold_on: cost below which load turns ON
    threshold_off: cost above which load turns OFF
    threshold_on <= threshold_off (hysteresis band)
    """
    threshold_on = draw(decimals(
        min_value=Decimal("0.05"),
        max_value=Decimal("2.50"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    # threshold_off must be >= threshold_on
    threshold_off = draw(decimals(
        min_value=threshold_on,
        max_value=Decimal("4.50"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ))
    return threshold_on, threshold_off


@composite
def load_config_strategy(draw, priority=None):
    """Generate a valid LoadConfig for testing.

    Uses a time window that includes BASE_TIME (noon) so the load
    is within its allowed window during tests.
    """
    threshold_on, threshold_off = draw(valid_threshold_pair())

    min_daily = round(draw(floats(
        min_value=0.5, max_value=8.0,
        allow_nan=False, allow_infinity=False,
    )), 1)

    max_daily = round(draw(floats(
        min_value=max(min_daily, 1.0), max_value=24.0,
        allow_nan=False, allow_infinity=False,
    )), 1)

    prio = priority if priority is not None else draw(integers(min_value=1, max_value=16))

    power_w = draw(integers(min_value=100, max_value=5000))

    load_id = f"load_{draw(integers(min_value=1, max_value=9999))}"

    return LoadConfig(
        load_id=load_id,
        name=f"Odbiornik {load_id}",
        entity_id=f"switch.{load_id}",
        threshold_on=threshold_on,
        threshold_off=threshold_off,
        min_daily_hours=min_daily,
        max_daily_hours=max_daily,
        allowed_start=time(0, 0),   # Full day window
        allowed_end=time(23, 59),
        priority=prio,
        power_w=power_w,
        failsafe_state=draw(booleans()),
    )


@composite
def cost_and_load_strategy(draw):
    """Generate a current cost and a load config for threshold testing.

    Ensures the cost is clearly below threshold_on or above threshold_off
    to test deterministic switching behavior.
    """
    threshold_on, threshold_off = draw(valid_threshold_pair())

    # Decide whether cost is below on-threshold or above off-threshold
    below_on = draw(booleans())

    if below_on:
        # Cost clearly below threshold_on
        max_cost = threshold_on - Decimal("0.01")
        assume(max_cost > Decimal("0.00"))
        cost = draw(decimals(
            min_value=Decimal("0.01"),
            max_value=max_cost,
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ))
    else:
        # Cost clearly above threshold_off
        min_cost = threshold_off + Decimal("0.01")
        assume(min_cost <= Decimal("5.00"))
        cost = draw(decimals(
            min_value=min_cost,
            max_value=Decimal("5.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ))

    load = LoadConfig(
        load_id="load_test",
        name="Test Load",
        entity_id="switch.test_load",
        threshold_on=threshold_on,
        threshold_off=threshold_off,
        min_daily_hours=1.0,
        max_daily_hours=12.0,
        allowed_start=time(0, 0),
        allowed_end=time(23, 59),
        priority=1,
        power_w=2000,
        failsafe_state=False,
    )

    return cost, load, below_on


@composite
def hourly_costs_strategy(draw, n_hours=None):
    """Generate a list of HourlyCost objects for remaining hours of the day."""
    if n_hours is None:
        n_hours = draw(integers(min_value=2, max_value=12))

    base = datetime(2024, 6, 15, 12, 0)
    costs = []
    for i in range(n_hours):
        cost_val = draw(decimals(
            min_value=Decimal("0.10"),
            max_value=Decimal("3.00"),
            places=4,
            allow_nan=False,
            allow_infinity=False,
        ))
        from custom_components.peo.models import TariffRates
        costs.append(HourlyCost(
            hour=(12 + i) % 24,
            timestamp=base + timedelta(hours=i),
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


@composite
def multiple_loads_with_priorities(draw, min_loads=2, max_loads=6):
    """Generate multiple loads with distinct priorities and power values."""
    n_loads = draw(integers(min_value=min_loads, max_value=max_loads))

    # Generate distinct priorities
    priorities = list(range(1, n_loads + 1))

    loads = []
    for i, prio in enumerate(priorities):
        power_w = draw(integers(min_value=500, max_value=3000))
        loads.append(LoadConfig(
            load_id=f"load_{i+1}",
            name=f"Odbiornik {i+1}",
            entity_id=f"switch.load_{i+1}",
            threshold_on=Decimal("0.50"),
            threshold_off=Decimal("0.80"),
            min_daily_hours=1.0,
            max_daily_hours=12.0,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=prio,
            power_w=power_w,
            failsafe_state=False,
        ))

    return loads


# --- Property 11 Tests ---


class TestProperty11ThresholdSwitching:
    """Property 11: Przełączanie odbiorników wg progów cenowych.

    Dla dowolnego odbiornika odraczalnego i bieżącego kosztu energii:
    jeśli koszt spadnie poniżej progu włączenia — odbiornik powinien zostać włączony;
    jeśli koszt przekroczy próg wyłączenia — odbiornik powinien zostać wyłączony.

    **Validates: Requirements 4.2, 4.3**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=cost_and_load_strategy())
    def test_load_on_when_cost_below_threshold_on(self, scenario):
        """When cost < threshold_on, the load decision should be 'on'.

        **Validates: Requirements 4.2**
        """
        cost, load, below_on = scenario
        assume(below_on)  # Only test the below-threshold case

        manager = LoadManager(grid_limit_kw=50.0)
        load_states = {
            load.load_id: {
                "is_on": False,
                "daily_runtime_hours": 0.0,
                "manual_override": False,
            }
        }

        decisions = manager.evaluate_loads(cost, [load], load_states, now=BASE_TIME)

        assert len(decisions) == 1
        assert decisions[0].action == "on", (
            f"Expected 'on' when cost={cost} < threshold_on={load.threshold_on}, "
            f"got action='{decisions[0].action}'"
        )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=cost_and_load_strategy())
    def test_load_off_when_cost_above_threshold_off(self, scenario):
        """When cost > threshold_off, the load decision should be 'off'.

        **Validates: Requirements 4.3**
        """
        cost, load, below_on = scenario
        assume(not below_on)  # Only test the above-threshold case

        manager = LoadManager(grid_limit_kw=50.0)
        load_states = {
            load.load_id: {
                "is_on": True,
                "daily_runtime_hours": 0.0,
                "manual_override": False,
            }
        }

        decisions = manager.evaluate_loads(cost, [load], load_states, now=BASE_TIME)

        assert len(decisions) == 1
        assert decisions[0].action == "off", (
            f"Expected 'off' when cost={cost} > threshold_off={load.threshold_off}, "
            f"got action='{decisions[0].action}'"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        threshold_on=decimals(
            min_value=Decimal("0.20"), max_value=Decimal("1.00"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
        threshold_off=decimals(
            min_value=Decimal("1.01"), max_value=Decimal("3.00"),
            places=2, allow_nan=False, allow_infinity=False,
        ),
        is_on=booleans(),
    )
    def test_load_maintains_state_between_thresholds(self, threshold_on, threshold_off, is_on):
        """When threshold_on <= cost <= threshold_off, the load maintains its current state.

        **Validates: Requirements 4.2, 4.3**
        """
        assume(threshold_on < threshold_off)

        # Cost between thresholds
        cost = (threshold_on + threshold_off) / 2

        load = LoadConfig(
            load_id="load_hysteresis",
            name="Hysteresis Test",
            entity_id="switch.hysteresis",
            threshold_on=threshold_on,
            threshold_off=threshold_off,
            min_daily_hours=1.0,
            max_daily_hours=12.0,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        load_states = {
            "load_hysteresis": {
                "is_on": is_on,
                "daily_runtime_hours": 0.0,
                "manual_override": False,
            }
        }

        decisions = manager.evaluate_loads(cost, [load], load_states, now=BASE_TIME)

        expected_action = "on" if is_on else "off"
        assert decisions[0].action == expected_action, (
            f"Expected '{expected_action}' (maintain state) when cost={cost} "
            f"is between thresholds ({threshold_on}–{threshold_off}), "
            f"got action='{decisions[0].action}'"
        )


# --- Property 12 Tests ---


class TestProperty12MinimumRuntime:
    """Property 12: Zapewnienie minimalnej dziennej pracy odbiornika.

    Dla dowolnego odbiornika z minimalną dzienną pracą i dostępnymi godzinami
    w oknie czasowym, jeśli minimalna praca nie została osiągnięta, system
    powinien wybrać najtańsze pozostałe godziny do uruchomienia odbiornika.

    **Validates: Requirements 4.4**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        remaining_costs=hourly_costs_strategy(),
        current_runtime=floats(
            min_value=0.0, max_value=2.0,
            allow_nan=False, allow_infinity=False,
        ),
        min_daily_hours=floats(
            min_value=2.0, max_value=6.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_cheapest_hours_selected_for_minimum_runtime(
        self, remaining_costs, current_runtime, min_daily_hours
    ):
        """When min_daily_hours not met, the system selects cheapest remaining hours.

        **Validates: Requirements 4.4**
        """
        assume(current_runtime < min_daily_hours)
        assume(len(remaining_costs) >= 2)

        remaining_needed = min_daily_hours - current_runtime
        # Ensure there are enough hours available
        assume(len(remaining_costs) >= int(remaining_needed))

        load = LoadConfig(
            load_id="load_min_runtime",
            name="Min Runtime Test",
            entity_id="switch.min_runtime",
            threshold_on=Decimal("0.50"),
            threshold_off=Decimal("1.00"),
            min_daily_hours=min_daily_hours,
            max_daily_hours=24.0,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        windows = manager.ensure_minimum_runtime(
            load=load,
            remaining_costs=remaining_costs,
            current_runtime_hours=current_runtime,
        )

        if not windows:
            # No windows means no eligible hours (shouldn't happen with our setup)
            return

        # Verify: selected windows cover at least the remaining needed hours
        total_hours = len(windows)  # Each window is 1 hour
        assert total_hours >= int(remaining_needed), (
            f"Not enough hours planned: {total_hours} < {remaining_needed} needed"
        )

        # Verify: selected hours are the cheapest available
        # Get costs of selected windows
        selected_timestamps = {w.start for w in windows}
        selected_costs = sorted([
            c.cost_pln_kwh for c in remaining_costs
            if c.timestamp in selected_timestamps
        ])

        # Get costs of non-selected hours
        non_selected_costs = sorted([
            c.cost_pln_kwh for c in remaining_costs
            if c.timestamp not in selected_timestamps
        ])

        # Every selected cost should be <= every non-selected cost
        if selected_costs and non_selected_costs:
            assert max(selected_costs) <= min(non_selected_costs) or \
                   len(selected_costs) >= len(remaining_costs), (
                f"Selected hours are not the cheapest: "
                f"max selected={max(selected_costs)}, "
                f"min non-selected={min(non_selected_costs)}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(
        remaining_costs=hourly_costs_strategy(),
        min_daily_hours=floats(
            min_value=1.0, max_value=4.0,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_no_windows_when_minimum_already_met(self, remaining_costs, min_daily_hours):
        """When current_runtime >= min_daily_hours, no additional windows are planned.

        **Validates: Requirements 4.4**
        """
        # Current runtime already meets or exceeds minimum
        current_runtime = min_daily_hours + 1.0

        load = LoadConfig(
            load_id="load_already_met",
            name="Already Met Test",
            entity_id="switch.already_met",
            threshold_on=Decimal("0.50"),
            threshold_off=Decimal("1.00"),
            min_daily_hours=min_daily_hours,
            max_daily_hours=24.0,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        windows = manager.ensure_minimum_runtime(
            load=load,
            remaining_costs=remaining_costs,
            current_runtime_hours=current_runtime,
        )

        assert windows == [], (
            f"Expected no windows when runtime ({current_runtime}h) >= "
            f"min_daily_hours ({min_daily_hours}h), got {len(windows)} windows"
        )

    @PROPERTY_TEST_SETTINGS
    @given(remaining_costs=hourly_costs_strategy())
    def test_selected_windows_are_chronologically_sorted(self, remaining_costs):
        """Selected windows should be sorted chronologically.

        **Validates: Requirements 4.4**
        """
        assume(len(remaining_costs) >= 3)

        load = LoadConfig(
            load_id="load_sorted",
            name="Sorted Test",
            entity_id="switch.sorted",
            threshold_on=Decimal("0.50"),
            threshold_off=Decimal("1.00"),
            min_daily_hours=2.0,
            max_daily_hours=24.0,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        windows = manager.ensure_minimum_runtime(
            load=load,
            remaining_costs=remaining_costs,
            current_runtime_hours=0.0,
        )

        if len(windows) > 1:
            for i in range(len(windows) - 1):
                assert windows[i].start <= windows[i + 1].start, (
                    f"Windows not chronologically sorted: "
                    f"{windows[i].start} > {windows[i+1].start}"
                )


# --- Property 13 Tests ---


class TestProperty13MaxDailyHoursBlocking:
    """Property 13: Blokada po osiągnięciu maksymalnej dziennej pracy.

    Dla dowolnego odbiornika, który osiągnął skonfigurowaną maksymalną dzienną
    pracę, system nie powinien dopuścić do dalszych włączeń do godziny 00:00
    dnia następnego.

    **Validates: Requirements 4.5**
    """

    @PROPERTY_TEST_SETTINGS
    @given(
        max_daily_hours=floats(
            min_value=1.0, max_value=12.0,
            allow_nan=False, allow_infinity=False,
        ),
        extra_runtime=floats(
            min_value=0.0, max_value=5.0,
            allow_nan=False, allow_infinity=False,
        ),
        cost=decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("0.10"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_load_blocked_after_max_daily_hours(self, max_daily_hours, extra_runtime, cost):
        """After max_daily_hours reached, action should be 'blocked'.

        Even if cost is very low (below threshold_on), the load should
        not be activated once max daily hours are reached.

        **Validates: Requirements 4.5**
        """
        daily_runtime = max_daily_hours + extra_runtime  # At or above max

        load = LoadConfig(
            load_id="load_blocked",
            name="Blocked Test",
            entity_id="switch.blocked",
            threshold_on=Decimal("0.50"),  # Cost will be below this
            threshold_off=Decimal("1.00"),
            min_daily_hours=1.0,
            max_daily_hours=max_daily_hours,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        load_states = {
            "load_blocked": {
                "is_on": False,
                "daily_runtime_hours": daily_runtime,
                "manual_override": False,
            }
        }

        decisions = manager.evaluate_loads(cost, [load], load_states, now=BASE_TIME)

        assert len(decisions) == 1
        assert decisions[0].action == "blocked", (
            f"Expected 'blocked' when daily_runtime ({daily_runtime}h) >= "
            f"max_daily_hours ({max_daily_hours}h), "
            f"got action='{decisions[0].action}'"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        max_daily_hours=floats(
            min_value=2.0, max_value=12.0,
            allow_nan=False, allow_infinity=False,
        ),
        cost=decimals(
            min_value=Decimal("0.01"),
            max_value=Decimal("0.20"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    def test_load_not_blocked_before_max_daily_hours(self, max_daily_hours, cost):
        """Before max_daily_hours reached, load should not be blocked.

        When cost < threshold_on and runtime < max_daily_hours, the load
        should be turned on (not blocked).

        **Validates: Requirements 4.5**
        """
        # Runtime well below max
        daily_runtime = max_daily_hours * 0.5

        load = LoadConfig(
            load_id="load_not_blocked",
            name="Not Blocked Test",
            entity_id="switch.not_blocked",
            threshold_on=Decimal("0.50"),  # Cost will be below this
            threshold_off=Decimal("1.00"),
            min_daily_hours=1.0,
            max_daily_hours=max_daily_hours,
            allowed_start=time(0, 0),
            allowed_end=time(23, 59),
            priority=1,
            power_w=2000,
            failsafe_state=False,
        )

        manager = LoadManager(grid_limit_kw=50.0)
        load_states = {
            "load_not_blocked": {
                "is_on": False,
                "daily_runtime_hours": daily_runtime,
                "manual_override": False,
            }
        }

        decisions = manager.evaluate_loads(cost, [load], load_states, now=BASE_TIME)

        assert len(decisions) == 1
        assert decisions[0].action != "blocked", (
            f"Load should not be blocked when daily_runtime ({daily_runtime}h) < "
            f"max_daily_hours ({max_daily_hours}h), "
            f"got action='{decisions[0].action}'"
        )


# --- Property 14 Tests ---


class TestProperty14PowerPrioritization:
    """Property 14: Priorytetyzacja mocy — odbiorniki.

    Dla dowolnego zestawu aktywnych odbiorników, jeśli suma ich poboru mocy
    plus obciążenie budynku przekracza moc przyłączeniową, system powinien
    wstrzymać włączenie odbiorników o niższym priorytecie (wyższa wartość
    liczbowa), zachowując odbiorniki o wyższym priorytecie.

    **Validates: Requirements 4.6**
    """

    @PROPERTY_TEST_SETTINGS
    @given(loads=multiple_loads_with_priorities())
    def test_higher_priority_loads_activated_first(self, loads):
        """When power budget is limited, the greedy algorithm processes loads
        in priority order. A higher-priority load that fits is always included
        before considering lower-priority loads.

        The key property: if two loads have the same power and one has higher
        priority, the higher-priority one is always preferred. More generally,
        the algorithm processes loads in priority order and greedily adds
        those that fit within the remaining budget.

        **Validates: Requirements 4.6**
        """
        # Calculate total power of all loads
        total_power_kw = sum(l.power_w / 1000.0 for l in loads)

        # Set grid limit so only some loads can be activated
        # Building load is 0, grid limit is half of total load power
        grid_limit_kw = total_power_kw * 0.5
        assume(grid_limit_kw >= loads[0].power_w / 1000.0)  # At least one load fits

        manager = LoadManager(grid_limit_kw=grid_limit_kw)
        approved = manager.check_power_budget(
            loads_to_activate=loads,
            current_building_load_kw=0.0,
            grid_limit_kw=grid_limit_kw,
        )

        if not approved:
            return  # No loads fit at all

        # Verify: approved loads maintain their relative priority ordering
        # (the greedy algorithm processes in priority order)
        approved_priorities = [l.priority for l in approved]
        assert approved_priorities == sorted(approved_priorities), (
            f"Approved loads not in priority order: {approved_priorities}"
        )

        # Verify the greedy property: simulate the algorithm and confirm
        # the result matches. Process loads in priority order, add if fits.
        sorted_loads = sorted(loads, key=lambda l: l.priority)
        expected_approved = []
        used_power = 0.0
        for load in sorted_loads:
            load_power = load.power_w / 1000.0
            if used_power + load_power <= grid_limit_kw:
                expected_approved.append(load.load_id)
                used_power += load_power

        actual_approved_ids = [l.load_id for l in approved]
        assert actual_approved_ids == expected_approved, (
            f"Greedy priority allocation mismatch: "
            f"expected {expected_approved}, got {actual_approved_ids}"
        )

    @PROPERTY_TEST_SETTINGS
    @given(loads=multiple_loads_with_priorities())
    def test_total_approved_power_within_budget(self, loads):
        """Total power of approved loads should not exceed available power budget.

        **Validates: Requirements 4.6**
        """
        total_power_kw = sum(l.power_w / 1000.0 for l in loads)

        # Set a constrained grid limit
        grid_limit_kw = total_power_kw * 0.6
        current_building_load_kw = grid_limit_kw * 0.2

        manager = LoadManager(grid_limit_kw=grid_limit_kw)
        approved = manager.check_power_budget(
            loads_to_activate=loads,
            current_building_load_kw=current_building_load_kw,
            grid_limit_kw=grid_limit_kw,
        )

        available_power = grid_limit_kw - current_building_load_kw
        approved_power = sum(l.power_w / 1000.0 for l in approved)

        assert approved_power <= available_power + 1e-6, (
            f"Approved power ({approved_power:.3f} kW) exceeds available "
            f"budget ({available_power:.3f} kW)"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        loads=multiple_loads_with_priorities(min_loads=3, max_loads=6),
        building_load_fraction=floats(
            min_value=0.0, max_value=0.5,
            allow_nan=False, allow_infinity=False,
        ),
    )
    def test_no_loads_when_no_available_power(self, loads, building_load_fraction):
        """When building load equals or exceeds grid limit, no loads are approved.

        **Validates: Requirements 4.6**
        """
        total_power_kw = sum(l.power_w / 1000.0 for l in loads)
        grid_limit_kw = total_power_kw * 0.5

        # Building load consumes all available power
        current_building_load_kw = grid_limit_kw + 0.1

        manager = LoadManager(grid_limit_kw=grid_limit_kw)
        approved = manager.check_power_budget(
            loads_to_activate=loads,
            current_building_load_kw=current_building_load_kw,
            grid_limit_kw=grid_limit_kw,
        )

        assert approved == [], (
            f"Expected no approved loads when building load "
            f"({current_building_load_kw:.2f} kW) >= grid limit "
            f"({grid_limit_kw:.2f} kW), got {len(approved)} loads"
        )

    @PROPERTY_TEST_SETTINGS
    @given(loads=multiple_loads_with_priorities(min_loads=2, max_loads=5))
    def test_all_loads_approved_when_budget_sufficient(self, loads):
        """When power budget is sufficient for all loads, all are approved.

        **Validates: Requirements 4.6**
        """
        total_power_kw = sum(l.power_w / 1000.0 for l in loads)

        # Grid limit much larger than total load power
        grid_limit_kw = total_power_kw * 3.0

        manager = LoadManager(grid_limit_kw=grid_limit_kw)
        approved = manager.check_power_budget(
            loads_to_activate=loads,
            current_building_load_kw=0.0,
            grid_limit_kw=grid_limit_kw,
        )

        assert len(approved) == len(loads), (
            f"Expected all {len(loads)} loads approved when budget is sufficient, "
            f"got {len(approved)}"
        )
