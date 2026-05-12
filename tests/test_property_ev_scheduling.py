"""Property-based tests for EV scheduling (ScheduleEngine).

**Validates: Requirements 3.1, 3.5, 3.10, 3.13**

Property 6: Optymalne okno ladowania EV minimalizuje koszt
Dla dowolnego profilu cenowego (24h), wymagan ladowania (docelowy SoC, moc, deadline)
i ograniczen (moc przylaczeniowa, obciazenie budynku), obliczony harmonogram ladowania
powinien miec laczny koszt nie wyzszy niz koszt dowolnego innego dopuszczalnego
harmonogramu spelniajacego te same ograniczenia.

Property 7: Ladowanie niecigle vs ciagle - wybor tanszego
Dla dowolnego profilu cenowego, jesli laczny koszt ladowania w wielu nieciaglych
oknach jest nizszy niz koszt najtanszego ciaglego okna pokrywajacego wymagany czas
ladowania, algorytm powinien wybrac wariant nieciagly.

Property 9: Nieprzekraczanie mocy przylaczeniowej (EV)
Dla dowolnej kombinacji planowanej mocy ladowania EV i biezacego obciazenia budynku,
suma tych wartosci nie powinna nigdy przekroczyc skonfigurowanej mocy przylaczeniowej.

Property 10: Wykrywanie nieosiagalnosci docelowego SoC
Dla dowolnego scenariusza, w ktorym wymagana energia do naladowania przekracza
dostepna energie (ograniczona moca, czasem do deadline i moca przylaczeniowa),
system powinien wykryc nieosiagalnosc i raportowac is_feasible=False.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from itertools import combinations

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    floats,
    lists,
    composite,
    just,
    sampled_from,
)

from custom_components.peo.schedule_engine import (
    ScheduleEngine,
    ScheduleResult,
    ScheduleWindow,
    TimeSlot,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)


# --- Helper Functions ---


def make_slots(base: datetime, count: int) -> list[TimeSlot]:
    """Create a list of hourly time slots."""
    return [
        TimeSlot(
            start=base + timedelta(hours=i),
            end=base + timedelta(hours=i + 1),
            duration_hours=1.0,
        )
        for i in range(count)
    ]


BASE_TIME = datetime(2024, 1, 15, 0, 0)


def compute_schedule_cost(
    windows: list[ScheduleWindow],
    time_slots: list[TimeSlot],
    costs: list[Decimal],
) -> Decimal:
    """Compute the total cost of a schedule from its windows."""
    total = Decimal("0.00")
    for window in windows:
        for i, slot in enumerate(time_slots):
            if slot == window.slot:
                energy = Decimal(str(round(window.power_kw * slot.duration_hours, 6)))
                total += costs[i] * energy
                break
    return total


# --- Strategies ---


@composite
def ev_scheduling_scenario(draw, min_slots=3, max_slots=12):
    """Generate a valid EV scheduling scenario.

    Returns: (time_slots, costs, required_energy, power_min, power_max,
              grid_limit, existing_load)
    """
    n_slots = draw(integers(min_value=min_slots, max_value=max_slots))
    time_slots = make_slots(BASE_TIME, n_slots)

    # Generate costs per slot (PLN/kWh, realistic range)
    costs = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=2.00,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]

    # Power constraints
    power_min = draw(floats(min_value=1.0, max_value=3.0,
                            allow_nan=False, allow_infinity=False))
    power_max = draw(floats(min_value=max(power_min + 0.5, 3.5), max_value=22.0,
                            allow_nan=False, allow_infinity=False))

    # Grid limit must be > power_min to allow any charging
    grid_limit = draw(floats(min_value=power_max + 1.0, max_value=50.0,
                             allow_nan=False, allow_infinity=False))

    # Existing load per slot - must leave room for at least power_min
    existing_load = [
        round(draw(floats(min_value=0.0, max_value=grid_limit - power_min - 0.1,
                          allow_nan=False, allow_infinity=False)), 2)
        for _ in range(n_slots)
    ]

    # Required energy - must be achievable
    # Max possible energy = sum of min(power_max, grid_limit - load) * duration for each slot
    max_possible = sum(
        min(power_max, grid_limit - existing_load[i]) * time_slots[i].duration_hours
        for i in range(n_slots)
        if grid_limit - existing_load[i] >= power_min
    )

    # Ensure we request achievable energy (between power_min*1h and 80% of max)
    assume(max_possible >= power_min * 1.0)
    max_request = min(max_possible * 0.8, power_max * n_slots * 0.6)
    min_request = power_min * 1.0

    assume(max_request >= min_request)

    required_energy = round(draw(floats(
        min_value=min_request, max_value=max_request,
        allow_nan=False, allow_infinity=False
    )), 2)

    return (time_slots, costs, required_energy, power_min, power_max,
            grid_limit, existing_load)


@composite
def small_ev_scenario_for_brute_force(draw):
    """Generate a small scenario (3-5 slots) suitable for brute-force comparison."""
    n_slots = draw(integers(min_value=3, max_value=5))
    time_slots = make_slots(BASE_TIME, n_slots)

    # Generate varied costs to make optimization meaningful
    costs = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=1.50,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]

    power_min = 1.4
    power_max = 7.0
    grid_limit = 15.0

    # Low existing load to ensure feasibility
    existing_load = [
        round(draw(floats(min_value=0.0, max_value=5.0,
                          allow_nan=False, allow_infinity=False)), 2)
        for _ in range(n_slots)
    ]

    # Required energy - small enough to be achievable
    available_power = [min(power_max, grid_limit - existing_load[i])
                       for i in range(n_slots)]
    feasible_slots = [i for i in range(n_slots) if available_power[i] >= power_min]
    assume(len(feasible_slots) >= 1)

    max_possible = sum(available_power[i] for i in feasible_slots)
    assume(max_possible >= power_min)

    required_energy = round(draw(floats(
        min_value=power_min * 1.0,
        max_value=min(max_possible * 0.7, power_max * 2.0),
        allow_nan=False, allow_infinity=False
    )), 2)

    return (time_slots, costs, required_energy, power_min, power_max,
            grid_limit, existing_load)


@composite
def infeasible_ev_scenario(draw):
    """Generate a scenario where required energy exceeds max possible energy.

    This ensures the system must report is_feasible=False.
    """
    n_slots = draw(integers(min_value=2, max_value=8))
    time_slots = make_slots(BASE_TIME, n_slots)

    costs = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=2.00,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]

    power_min = draw(floats(min_value=1.0, max_value=3.0,
                            allow_nan=False, allow_infinity=False))
    power_max = draw(floats(min_value=max(power_min + 0.5, 3.5), max_value=11.0,
                            allow_nan=False, allow_infinity=False))

    grid_limit = draw(floats(min_value=power_max + 0.5, max_value=20.0,
                             allow_nan=False, allow_infinity=False))

    # Generate existing load that limits available power
    existing_load = [
        round(draw(floats(min_value=0.0, max_value=grid_limit - 0.5,
                          allow_nan=False, allow_infinity=False)), 2)
        for _ in range(n_slots)
    ]

    # Calculate max possible energy considering all constraints
    max_possible = 0.0
    for i in range(n_slots):
        avail = min(power_max, grid_limit - existing_load[i])
        if avail >= power_min:
            max_possible += avail * time_slots[i].duration_hours

    # Request MORE energy than is possible (at least 1.5x)
    required_energy = round(max_possible * draw(floats(
        min_value=1.5, max_value=5.0,
        allow_nan=False, allow_infinity=False
    )), 2)

    # Ensure we actually exceed capacity
    assume(required_energy > max_possible + 0.1)

    return (time_slots, costs, required_energy, power_min, power_max,
            grid_limit, existing_load)


@composite
def grid_limit_scenario(draw):
    """Generate a scenario focused on grid limit testing."""
    n_slots = draw(integers(min_value=3, max_value=10))
    time_slots = make_slots(BASE_TIME, n_slots)

    costs = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=2.00,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]

    power_min = 1.4
    power_max = draw(floats(min_value=5.0, max_value=22.0,
                            allow_nan=False, allow_infinity=False))

    grid_limit = draw(floats(min_value=power_min + 1.0, max_value=30.0,
                             allow_nan=False, allow_infinity=False))

    # Existing load varies - some slots near grid limit, some with room
    existing_load = [
        round(draw(floats(min_value=0.0, max_value=grid_limit - 0.5,
                          allow_nan=False, allow_infinity=False)), 2)
        for _ in range(n_slots)
    ]

    # Ensure at least one slot has room for power_min
    feasible_count = sum(1 for i in range(n_slots)
                         if grid_limit - existing_load[i] >= power_min)
    assume(feasible_count >= 1)

    # Small required energy to ensure feasibility
    max_possible = sum(
        min(power_max, grid_limit - existing_load[i])
        for i in range(n_slots)
        if grid_limit - existing_load[i] >= power_min
    )
    assume(max_possible >= power_min)

    required_energy = round(draw(floats(
        min_value=power_min * 1.0,
        max_value=min(max_possible * 0.5, power_max * 2.0),
        allow_nan=False, allow_infinity=False
    )), 2)

    return (time_slots, costs, required_energy, power_min, power_max,
            grid_limit, existing_load)


# --- Property 6 Tests ---


class TestProperty6OptimalChargingWindowMinimizesCost:
    """Property 6: Optymalne okno ladowania EV minimalizuje koszt.

    For any valid set of hourly costs and charging requirements, the selected
    charging window should have the minimum possible total cost among all
    feasible schedules.

    **Validates: Requirements 3.1**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=small_ev_scenario_for_brute_force())
    def test_no_single_slot_swap_improves_cost(self, scenario):
        """For any feasible schedule, swapping a used slot for an unused slot
        with lower cost should not produce a cheaper valid schedule.

        This verifies local optimality: the solver picks cheaper slots first.

        **Validates: Requirements 3.1**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        assume(result.is_feasible)
        assume(len(result.windows) > 0)

        # Get indices of used slots
        used_indices = set()
        for window in result.windows:
            for i, slot in enumerate(time_slots):
                if slot == window.slot:
                    used_indices.add(i)
                    break

        # Get indices of unused feasible slots
        unused_feasible = []
        for i in range(len(time_slots)):
            if i not in used_indices:
                avail = min(power_max, grid_limit - existing_load[i])
                if avail >= power_min:
                    unused_feasible.append(i)

        # For each unused slot, verify it's not cheaper than any used slot
        # (considering the greedy approach picks cheapest first)
        if unused_feasible and used_indices:
            min_unused_cost = min(float(costs[i]) for i in unused_feasible)
            max_used_cost = max(float(costs[i]) for i in used_indices)
            # The most expensive used slot should cost <= cheapest unused slot
            # (greedy picks cheapest first)
            assert max_used_cost <= min_unused_cost + 1e-9

    @PROPERTY_TEST_SETTINGS
    @given(scenario=small_ev_scenario_for_brute_force())
    def test_cost_not_higher_than_uniform_allocation(self, scenario):
        """The optimized schedule cost should not exceed the cost of
        uniformly distributing energy across all feasible slots.

        **Validates: Requirements 3.1**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        assume(result.is_feasible)

        # Calculate cost of uniform allocation across all feasible slots
        n = len(time_slots)
        feasible_slots = []
        for i in range(n):
            avail = min(power_max, grid_limit - existing_load[i])
            if avail >= power_min:
                feasible_slots.append(i)

        assume(len(feasible_slots) >= 1)

        # Distribute energy uniformly
        total_capacity = sum(
            min(power_max, grid_limit - existing_load[i])
            for i in feasible_slots
        )
        assume(total_capacity >= required_energy)

        uniform_cost = Decimal("0.00")
        remaining = required_energy
        for i in feasible_slots:
            avail = min(power_max, grid_limit - existing_load[i])
            energy_share = min(remaining, avail * time_slots[i].duration_hours)
            uniform_cost += costs[i] * Decimal(str(round(energy_share, 6)))
            remaining -= energy_share
            if remaining <= 0:
                break

        # Optimized cost should be <= uniform cost
        assert result.total_cost <= uniform_cost + Decimal("0.01")


# --- Property 7 Tests ---


class TestProperty7DiscontinuousVsContinuousCheaper:
    """Property 7: Ladowanie niecigle vs ciagle - wybor tanszego.

    For any scenario where discontinuous charging is allowed, the total cost
    should be <= the cost of the best contiguous schedule.

    **Validates: Requirements 3.5**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=ev_scheduling_scenario(min_slots=4, max_slots=10))
    def test_discontinuous_cost_leq_contiguous_cost(self, scenario):
        """For same inputs, discontinuous schedule cost <= contiguous schedule cost.

        **Validates: Requirements 3.5**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()

        result_disc = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        result_cont = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=False,
        )

        # If both are feasible, discontinuous should be <= contiguous
        if result_disc.is_feasible and result_cont.is_feasible:
            assert result_disc.total_cost <= result_cont.total_cost + Decimal("0.01")

    @PROPERTY_TEST_SETTINGS
    @given(scenario=ev_scheduling_scenario(min_slots=4, max_slots=10))
    def test_discontinuous_feasible_when_contiguous_feasible(self, scenario):
        """If contiguous is feasible, discontinuous must also be feasible.

        Discontinuous has strictly more freedom than contiguous.

        **Validates: Requirements 3.5**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()

        result_disc = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        result_cont = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=False,
        )

        # If contiguous is feasible, discontinuous must be too
        if result_cont.is_feasible:
            assert result_disc.is_feasible


# --- Property 9 Tests ---


class TestProperty9GridLimitNotExceeded:
    """Property 9: Nieprzekraczanie mocy przylaczeniowej (EV).

    For any schedule, the sum of charging power and existing building load
    never exceeds the configured grid limit.

    **Validates: Requirements 3.10**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=grid_limit_scenario())
    def test_power_plus_load_never_exceeds_grid_limit(self, scenario):
        """For every window in result, window.power_kw + existing_load[slot] <= grid_limit.

        **Validates: Requirements 3.10**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        # Check all windows respect grid limit
        for window in result.windows:
            slot_idx = None
            for i, slot in enumerate(time_slots):
                if slot == window.slot:
                    slot_idx = i
                    break
            assert slot_idx is not None
            total_power = window.power_kw + existing_load[slot_idx]
            assert total_power <= grid_limit + 1e-4, (
                f"Grid limit exceeded: {window.power_kw} + {existing_load[slot_idx]} "
                f"= {total_power} > {grid_limit}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=ev_scheduling_scenario())
    def test_grid_limit_respected_in_general_scenario(self, scenario):
        """Grid limit is respected across all general scheduling scenarios.

        **Validates: Requirements 3.10**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        for window in result.windows:
            for i, slot in enumerate(time_slots):
                if slot == window.slot:
                    total_power = window.power_kw + existing_load[i]
                    assert total_power <= grid_limit + 1e-4, (
                        f"Grid limit exceeded in slot {i}: "
                        f"{window.power_kw} + {existing_load[i]} = {total_power} > {grid_limit}"
                    )
                    break

    @PROPERTY_TEST_SETTINGS
    @given(scenario=grid_limit_scenario())
    def test_grid_limit_respected_contiguous_mode(self, scenario):
        """Grid limit is respected in contiguous scheduling mode.

        **Validates: Requirements 3.10**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=False,
        )

        for window in result.windows:
            for i, slot in enumerate(time_slots):
                if slot == window.slot:
                    total_power = window.power_kw + existing_load[i]
                    assert total_power <= grid_limit + 1e-4, (
                        f"Grid limit exceeded in contiguous mode slot {i}: "
                        f"{window.power_kw} + {existing_load[i]} = {total_power} > {grid_limit}"
                    )
                    break


# --- Property 10 Tests ---


class TestProperty10InfeasibilityDetection:
    """Property 10: Wykrywanie nieosiagalnosci docelowego SoC.

    For any scenario where the required energy cannot be delivered within
    the available time/power constraints, the system should report
    is_feasible == False.

    **Validates: Requirements 3.13**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=infeasible_ev_scenario())
    def test_reports_infeasible_when_energy_exceeds_capacity(self, scenario):
        """When required_energy > max possible energy, result.is_feasible == False.

        **Validates: Requirements 3.13**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        assert not result.is_feasible, (
            f"Expected infeasible but got feasible. "
            f"Required: {required_energy} kWh, "
            f"Max possible with constraints: check scenario"
        )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=infeasible_ev_scenario())
    def test_infeasible_contiguous_when_energy_exceeds_capacity(self, scenario):
        """Contiguous mode also reports infeasible when energy exceeds capacity.

        **Validates: Requirements 3.13**
        """
        (time_slots, costs, required_energy, power_min, power_max,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=False,
        )

        assert not result.is_feasible

    @PROPERTY_TEST_SETTINGS
    @given(
        n_slots=integers(min_value=2, max_value=6),
        power_max=floats(min_value=3.0, max_value=11.0,
                         allow_nan=False, allow_infinity=False),
    )
    def test_infeasible_when_grid_fully_loaded(self, n_slots, power_max):
        """When existing load fills the grid completely, result is infeasible.

        **Validates: Requirements 3.13**
        """
        time_slots = make_slots(BASE_TIME, n_slots)
        costs = [Decimal("0.50")] * n_slots
        grid_limit = 10.0
        power_min = 1.4

        # Existing load fills the grid - no room for even power_min
        existing_load = [grid_limit] * n_slots

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=5.0,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        assert not result.is_feasible

    @PROPERTY_TEST_SETTINGS
    @given(
        n_slots=integers(min_value=1, max_value=4),
        power_min=floats(min_value=5.0, max_value=15.0,
                         allow_nan=False, allow_infinity=False),
    )
    def test_infeasible_when_power_min_exceeds_available(self, n_slots, power_min):
        """When power_min exceeds available power in all slots, result is infeasible.

        **Validates: Requirements 3.13**
        """
        time_slots = make_slots(BASE_TIME, n_slots)
        costs = [Decimal("0.50")] * n_slots
        grid_limit = 10.0
        power_max = 22.0

        # Existing load leaves less than power_min available
        existing_load = [grid_limit - power_min + 1.0] * n_slots

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=5.0,
            power_min=power_min,
            power_max=power_max,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        assert not result.is_feasible
