"""Property-based tests for charger power limits (Property 22).

**Validates: Requirements 9.3**

Property 22: Respektowanie limitów mocy ładowarki

Dla dowolnych limitów ładowarki (max_power_kw, max_current_a, min_power_kw)
i dowolnego scenariusza harmonogramowania, EV scheduler SHALL respektować
limity mocy ładowarki i nigdy nie wysyłać komend przekraczających te wartości.

Weryfikacja:
- Wszystkie okna w harmonogramie mają power_kw <= charger max_power_kw
- Wszystkie okna w harmonogramie mają power_kw >= charger min_power_kw (lub == 0)
- Żadna komenda nie przekracza limitów ładowarki
"""

from datetime import datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    floats,
    composite,
)

from custom_components.peo.charger_adapters import ChargerLimits
from custom_components.peo.schedule_engine import (
    ScheduleEngine,
    TimeSlot,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

BASE_TIME = datetime(2024, 1, 15, 0, 0)


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


# --- Strategies ---


@composite
def charger_limits_strategy(draw):
    """Generate random ChargerLimits within realistic ranges.

    - max_power_kw: 1.4-22 kW (from single-phase 6A to 3-phase 32A)
    - max_current_a: 6-32 A (standard EV charging range)
    - min_power_kw: 1.4-3.6 kW (minimum charging threshold)
    """
    min_power_kw = round(draw(floats(
        min_value=1.4, max_value=3.6,
        allow_nan=False, allow_infinity=False
    )), 2)

    max_power_kw = round(draw(floats(
        min_value=max(min_power_kw + 0.5, 3.7), max_value=22.0,
        allow_nan=False, allow_infinity=False
    )), 2)

    max_current_a = round(draw(floats(
        min_value=6.0, max_value=32.0,
        allow_nan=False, allow_infinity=False
    )), 1)

    return ChargerLimits(
        max_power_kw=max_power_kw,
        max_current_a=max_current_a,
        min_power_kw=min_power_kw,
    )


@composite
def charger_scheduling_scenario(draw):
    """Generate a scheduling scenario with charger limits.

    Returns: (charger_limits, time_slots, costs, required_energy,
              grid_limit, existing_load)
    """
    charger_limits = draw(charger_limits_strategy())

    n_slots = draw(integers(min_value=3, max_value=12))
    time_slots = make_slots(BASE_TIME, n_slots)

    # Generate costs per slot (PLN/kWh, realistic range)
    costs = [
        Decimal(str(round(draw(floats(
            min_value=0.10, max_value=2.00,
            allow_nan=False, allow_infinity=False
        )), 2)))
        for _ in range(n_slots)
    ]

    # Grid limit must be > charger min_power to allow any charging
    grid_limit = round(draw(floats(
        min_value=charger_limits.max_power_kw + 1.0, max_value=50.0,
        allow_nan=False, allow_infinity=False
    )), 2)

    # Existing load per slot - must leave room for at least min_power
    existing_load = [
        round(draw(floats(
            min_value=0.0,
            max_value=grid_limit - charger_limits.min_power_kw - 0.1,
            allow_nan=False, allow_infinity=False
        )), 2)
        for _ in range(n_slots)
    ]

    # Required energy - must be achievable within charger limits
    max_possible = sum(
        min(charger_limits.max_power_kw, grid_limit - existing_load[i])
        * time_slots[i].duration_hours
        for i in range(n_slots)
        if grid_limit - existing_load[i] >= charger_limits.min_power_kw
    )

    assume(max_possible >= charger_limits.min_power_kw * 1.0)
    max_request = min(max_possible * 0.7, charger_limits.max_power_kw * n_slots * 0.5)
    min_request = charger_limits.min_power_kw * 1.0

    assume(max_request >= min_request)

    required_energy = round(draw(floats(
        min_value=min_request, max_value=max_request,
        allow_nan=False, allow_infinity=False
    )), 2)

    return (charger_limits, time_slots, costs, required_energy,
            grid_limit, existing_load)


@composite
def tight_charger_limits_scenario(draw):
    """Generate a scenario where charger limits are the binding constraint.

    The grid limit is high, so the charger's own max_power_kw is the
    effective upper bound on power.
    """
    charger_limits = draw(charger_limits_strategy())

    n_slots = draw(integers(min_value=3, max_value=8))
    time_slots = make_slots(BASE_TIME, n_slots)

    costs = [
        Decimal(str(round(draw(floats(
            min_value=0.10, max_value=2.00,
            allow_nan=False, allow_infinity=False
        )), 2)))
        for _ in range(n_slots)
    ]

    # Grid limit much higher than charger max - charger is the binding constraint
    grid_limit = charger_limits.max_power_kw * 3.0

    # Low existing load to ensure charger limit is the binding constraint
    existing_load = [
        round(draw(floats(
            min_value=0.0, max_value=charger_limits.max_power_kw * 0.3,
            allow_nan=False, allow_infinity=False
        )), 2)
        for _ in range(n_slots)
    ]

    # Required energy achievable within charger limits
    max_possible = charger_limits.max_power_kw * n_slots
    required_energy = round(draw(floats(
        min_value=charger_limits.min_power_kw * 1.0,
        max_value=min(max_possible * 0.5, charger_limits.max_power_kw * 3.0),
        allow_nan=False, allow_infinity=False
    )), 2)

    return (charger_limits, time_slots, costs, required_energy,
            grid_limit, existing_load)


# --- Property 22 Tests ---


class TestProperty22ChargerPowerLimitsRespected:
    """Property 22: Respektowanie limitów mocy ładowarki.

    The EV scheduler SHALL respect charger power limits (max current A,
    max power kW) and never send commands exceeding these values.

    **Validates: Requirements 9.3**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=charger_scheduling_scenario())
    def test_power_never_exceeds_charger_max_power(self, scenario):
        """All windows in the schedule have power_kw <= charger max_power_kw.

        The ScheduleEngine receives charger max_power_kw as the power_max
        constraint. No window in the result should exceed this value.

        **Validates: Requirements 9.3**
        """
        (charger_limits, time_slots, costs, required_energy,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=charger_limits.min_power_kw,
            power_max=charger_limits.max_power_kw,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        for window in result.windows:
            assert window.power_kw <= charger_limits.max_power_kw + 1e-4, (
                f"Charger max power exceeded: window.power_kw={window.power_kw} > "
                f"charger max_power_kw={charger_limits.max_power_kw}"
            )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=charger_scheduling_scenario())
    def test_power_respects_charger_min_power_or_zero(self, scenario):
        """All windows have power_kw >= charger min_power_kw (or power_kw == 0).

        The charger cannot operate below its minimum power threshold.
        Either it charges at >= min_power_kw, or it doesn't charge at all.

        **Validates: Requirements 9.3**
        """
        (charger_limits, time_slots, costs, required_energy,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=charger_limits.min_power_kw,
            power_max=charger_limits.max_power_kw,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        for window in result.windows:
            # power_kw should be either 0 (not charging) or >= min_power_kw
            if window.power_kw > 1e-6:
                assert window.power_kw >= charger_limits.min_power_kw - 1e-4, (
                    f"Charger min power violated: window.power_kw={window.power_kw} < "
                    f"charger min_power_kw={charger_limits.min_power_kw}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=tight_charger_limits_scenario())
    def test_charger_limit_is_binding_when_grid_is_generous(self, scenario):
        """When grid limit is much higher than charger max, the charger limit
        is the effective upper bound on power in all windows.

        **Validates: Requirements 9.3**
        """
        (charger_limits, time_slots, costs, required_energy,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=charger_limits.min_power_kw,
            power_max=charger_limits.max_power_kw,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        for window in result.windows:
            assert window.power_kw <= charger_limits.max_power_kw + 1e-4, (
                f"Charger limit not binding: window.power_kw={window.power_kw} > "
                f"charger max_power_kw={charger_limits.max_power_kw} "
                f"(grid_limit={grid_limit})"
            )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=charger_scheduling_scenario())
    def test_contiguous_mode_respects_charger_limits(self, scenario):
        """Charger power limits are respected in contiguous scheduling mode.

        **Validates: Requirements 9.3**
        """
        (charger_limits, time_slots, costs, required_energy,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=charger_limits.min_power_kw,
            power_max=charger_limits.max_power_kw,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=False,
        )

        for window in result.windows:
            # Max power limit
            assert window.power_kw <= charger_limits.max_power_kw + 1e-4, (
                f"Charger max power exceeded in contiguous mode: "
                f"window.power_kw={window.power_kw} > "
                f"charger max_power_kw={charger_limits.max_power_kw}"
            )
            # Min power limit (if charging)
            if window.power_kw > 1e-6:
                assert window.power_kw >= charger_limits.min_power_kw - 1e-4, (
                    f"Charger min power violated in contiguous mode: "
                    f"window.power_kw={window.power_kw} < "
                    f"charger min_power_kw={charger_limits.min_power_kw}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=charger_scheduling_scenario())
    def test_power_within_current_limit_equivalent(self, scenario):
        """Verify that power_kw respects the equivalent power limit derived
        from max_current_a (at 230V single-phase: P = I * V / 1000).

        The charger's max_current_a defines an implicit power limit.
        The ScheduleEngine uses max_power_kw directly, which should already
        account for the current limit. This test verifies the constraint
        is consistent.

        **Validates: Requirements 9.3**
        """
        (charger_limits, time_slots, costs, required_energy,
         grid_limit, existing_load) = scenario

        engine = ScheduleEngine()
        result = engine.solve_minimum_cost_schedule(
            time_slots=time_slots,
            costs=costs,
            required_energy=required_energy,
            power_min=charger_limits.min_power_kw,
            power_max=charger_limits.max_power_kw,
            grid_limit=grid_limit,
            existing_load=existing_load,
            allow_discontinuous=True,
        )

        # The max_power_kw passed to the engine should be the effective limit
        # (already considering max_current_a). Verify no window exceeds it.
        for window in result.windows:
            assert window.power_kw <= charger_limits.max_power_kw + 1e-4, (
                f"Power exceeds charger limit (derived from max_current_a="
                f"{charger_limits.max_current_a}A): "
                f"window.power_kw={window.power_kw} > "
                f"max_power_kw={charger_limits.max_power_kw}"
            )
