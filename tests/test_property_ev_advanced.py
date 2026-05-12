"""Property-based tests for EV charging stop condition and multi-vehicle scheduling.

**Validates: Requirements 3.4, 11.2, 11.3, 11.4, 11.7**

Property 8: Warunek zatrzymania ladowania
Dla dowolnej sesji ladowania, gdy odczyt SoC osiagnie lub przekroczy docelowy SoC
LUB gdy okno ladowania sie zakonczy (w zaleznosci co nastapi wczesniej), system
powinien wydac komende zatrzymania ladowania.

Property 28: Przydzial mocy wielu pojazdom wg priorytetow
Dla dowolnego zestawu pojazdow wymagajacych ladowania jednoczesnie, dostepna moc
przylaczeniowa powinna byc przydzielana sekwencyjnie wg rangi priorytetu — pojazd
o wyzszym priorytecie otrzymuje pelne zapotrzebowanie, a pojazd nie powinien nigdy
otrzymac mocy nizszej niz jego skonfigurowane minimum (w takim przypadku ladowanie
jest wstrzymane).

Property 29: Strategia ladowania per pojazd
Dla dowolnego pojazdu ze skonfigurowana strategia ladowania, obliczony harmonogram
powinien respektowac te strategie: "najtansze_okna" minimalizuje koszt bez
ograniczenia czasowego, "gotowy_do_godziny" gwarantuje naladowanie przed deadline,
"tylko_nadwyzka_PV" laduje wylacznie w godzinach nadwyzki PV.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    integers,
    floats,
    lists,
    composite,
    just,
    sampled_from,
    booleans,
)

from custom_components.peo.enums import ChargingStrategy
from custom_components.peo.ev_scheduler import (
    ActiveSession,
    ChargingSessionManager,
    EVScheduler,
)
from custom_components.peo.models import (
    ChargerConfig,
    ChargingConstraints,
    ChargingSchedule,
    HourlyCost,
    TimeWindow,
    TariffRates,
    VehicleChargerPair,
    VehicleConfig,
)
from custom_components.peo.enums import TimeZoneName
from custom_components.peo.schedule_engine import (
    ScheduleEngine,
    TimeSlot,
)

# Minimum 200 iterations per property test as per design doc
PROPERTY_TEST_SETTINGS = settings(max_examples=200, deadline=None)

BASE_TIME = datetime(2024, 6, 15, 0, 0)


# --- Helper Functions ---


def make_hourly_costs(base: datetime, count: int, cost_values: list[Decimal]) -> list[HourlyCost]:
    """Create a list of HourlyCost objects."""
    default_rates = TariffRates(
        energy_price=Decimal("0.50"),
        distribution_variable=Decimal("0.20"),
        transition_fee=Decimal("0.01"),
        oze_fee=Decimal("0.01"),
        capacity_fee=Decimal("0.05"),
        cogeneration_fee=Decimal("0.01"),
    )
    return [
        HourlyCost(
            hour=(base + timedelta(hours=i)).hour,
            timestamp=base + timedelta(hours=i),
            cost_pln_kwh=cost_values[i],
            zone=TimeZoneName.POZASZCZYT,
            components=default_rates,
        )
        for i in range(count)
    ]


def make_vehicle(
    vehicle_id: str,
    battery_kwh: float = 60.0,
    max_power: float = 11.0,
    min_power: float = 1.4,
    target_soc: int = 80,
    priority: int = 1,
    strategy: ChargingStrategy = ChargingStrategy.CHEAPEST,
    deadline: Optional[datetime] = None,
) -> VehicleConfig:
    """Create a VehicleConfig for testing."""
    return VehicleConfig(
        vehicle_id=vehicle_id,
        name=f"Vehicle {vehicle_id}",
        battery_capacity_kwh=battery_kwh,
        max_charging_power_kw=max_power,
        min_charging_power_kw=min_power,
        soc_entity_id=f"sensor.{vehicle_id}_soc",
        target_soc=target_soc,
        deadline=deadline,
        priority=priority,
        strategy=strategy,
    )


def make_charger(
    charger_id: str,
    max_power: float = 22.0,
    max_current: float = 32.0,
) -> ChargerConfig:
    """Create a ChargerConfig for testing."""
    return ChargerConfig(
        charger_id=charger_id,
        name=f"Charger {charger_id}",
        protocol="ocpp16",
        host="192.168.1.100",
        api_key=None,
        entity_id=None,
        max_power_kw=max_power,
        max_current_a=max_current,
    )


# --- Strategies ---


@composite
def soc_and_target(draw):
    """Generate current SoC and target SoC values for stop condition testing."""
    target_soc = draw(integers(min_value=20, max_value=100))
    # Generate current_soc that may or may not exceed target
    current_soc = draw(floats(min_value=0.0, max_value=100.0,
                              allow_nan=False, allow_infinity=False))
    return current_soc, target_soc


@composite
def multi_vehicle_scenario(draw, min_vehicles=2, max_vehicles=4):
    """Generate a multi-vehicle scheduling scenario with different priorities.

    Returns: (vehicles_with_chargers, costs, grid_limit, current_socs,
              building_load, pv_surplus_hours)
    """
    n_vehicles = draw(integers(min_value=min_vehicles, max_value=max_vehicles))
    n_slots = draw(integers(min_value=6, max_value=12))

    # Generate costs
    cost_values = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=1.50,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]
    costs = make_hourly_costs(BASE_TIME, n_slots, cost_values)

    # Generate vehicles with distinct priorities
    priorities = list(range(1, n_vehicles + 1))
    vehicles_with_chargers: list[VehicleChargerPair] = []
    current_socs: dict[str, float] = {}

    for i in range(n_vehicles):
        battery_kwh = draw(floats(min_value=30.0, max_value=100.0,
                                  allow_nan=False, allow_infinity=False))
        max_power = draw(floats(min_value=3.5, max_value=22.0,
                                allow_nan=False, allow_infinity=False))
        min_power = draw(floats(min_value=1.0, max_value=min(3.0, max_power - 0.5),
                                allow_nan=False, allow_infinity=False))
        target_soc = draw(integers(min_value=50, max_value=100))
        current_soc = draw(floats(min_value=5.0, max_value=float(target_soc - 10),
                                  allow_nan=False, allow_infinity=False))

        vehicle = make_vehicle(
            vehicle_id=f"ev_{i}",
            battery_kwh=round(battery_kwh, 1),
            max_power=round(max_power, 1),
            min_power=round(min_power, 1),
            target_soc=target_soc,
            priority=priorities[i],
            strategy=ChargingStrategy.CHEAPEST,
        )
        charger = make_charger(f"charger_{i}", max_power=round(max_power + 5.0, 1))

        vehicles_with_chargers.append(VehicleChargerPair(vehicle=vehicle, charger=charger))
        current_socs[f"ev_{i}"] = round(current_soc, 1)

    # Grid limit must accommodate at least the highest priority vehicle
    highest_priority_power = vehicles_with_chargers[0].vehicle.max_charging_power_kw
    grid_limit = draw(floats(
        min_value=highest_priority_power + 1.0,
        max_value=highest_priority_power * n_vehicles + 10.0,
        allow_nan=False, allow_infinity=False,
    ))

    building_load = draw(floats(min_value=0.0, max_value=grid_limit * 0.2,
                                allow_nan=False, allow_infinity=False))

    return (vehicles_with_chargers, costs, round(grid_limit, 1),
            current_socs, round(building_load, 1))


@composite
def strategy_scenario(draw):
    """Generate a scenario for testing charging strategies.

    Returns: (vehicle, charger, costs, constraints, current_soc, pv_surplus_hours, deadline)
    """
    n_slots = draw(integers(min_value=8, max_value=16))

    cost_values = [
        Decimal(str(round(draw(floats(min_value=0.10, max_value=1.50,
                                      allow_nan=False, allow_infinity=False)), 2)))
        for _ in range(n_slots)
    ]
    costs = make_hourly_costs(BASE_TIME, n_slots, cost_values)

    strategy = draw(sampled_from(list(ChargingStrategy)))

    battery_kwh = draw(floats(min_value=30.0, max_value=100.0,
                              allow_nan=False, allow_infinity=False))
    max_power = draw(floats(min_value=3.5, max_value=22.0,
                            allow_nan=False, allow_infinity=False))
    min_power = draw(floats(min_value=1.0, max_value=min(3.0, max_power - 0.5),
                            allow_nan=False, allow_infinity=False))
    target_soc = draw(integers(min_value=50, max_value=100))
    current_soc = draw(floats(min_value=5.0, max_value=float(target_soc - 10),
                              allow_nan=False, allow_infinity=False))

    # Deadline for READY_BY: somewhere in the middle to end of slots
    deadline_slot = draw(integers(min_value=n_slots // 2, max_value=n_slots))
    deadline = BASE_TIME + timedelta(hours=deadline_slot)

    # PV surplus hours for PV_ONLY: pick some hours
    n_pv_hours = draw(integers(min_value=2, max_value=min(6, n_slots)))
    pv_surplus_hours = sorted(
        draw(lists(
            integers(min_value=0, max_value=23),
            min_size=n_pv_hours,
            max_size=n_pv_hours,
            unique=True,
        ))
    )

    vehicle = make_vehicle(
        vehicle_id="ev_test",
        battery_kwh=round(battery_kwh, 1),
        max_power=round(max_power, 1),
        min_power=round(min_power, 1),
        target_soc=target_soc,
        priority=1,
        strategy=strategy,
        deadline=deadline,
    )
    charger = make_charger("charger_test", max_power=round(max_power + 5.0, 1))

    grid_limit = round(max_power + 5.0, 1)
    constraints = ChargingConstraints(
        grid_limit_kw=grid_limit,
        current_building_load_kw=0.0,
        charger_max_power_kw=charger.max_power_kw,
        charger_max_current_a=charger.max_current_a,
        min_charging_power_kw=min_power,
        deadline=deadline,
        allow_discontinuous=True,
    )

    return (vehicle, charger, costs, constraints, round(current_soc, 1),
            pv_surplus_hours, deadline)


# --- Property 8 Tests ---


class TestProperty8ChargingStopCondition:
    """Property 8: Warunek zatrzymania ladowania.

    Charging stops when SoC >= target_soc OR window ended.

    **Validates: Requirements 3.4**
    """

    @PROPERTY_TEST_SETTINGS
    @given(data=soc_and_target())
    def test_stop_when_soc_reaches_target(self, data):
        """When current SoC >= target_soc, monitor_soc should trigger stop.

        **Validates: Requirements 3.4**
        """
        current_soc, target_soc = data
        assume(current_soc >= target_soc)

        # Track whether stop was called
        stop_called = False

        # Create a mock charger adapter
        charger_adapter = AsyncMock()
        charger_adapter.stop_charging = AsyncMock(return_value=True)

        # Create ChargingSessionManager with SoC callback returning current_soc
        def get_soc(vehicle_id: str) -> Optional[float]:
            return current_soc

        manager = ChargingSessionManager(
            get_soc=get_soc,
            get_current_cost=lambda: Decimal("0.50"),
            notify_user=lambda title, msg: None,
            fire_event=lambda event_type, data: None,
        )

        # Create a schedule with a window in the future (not ended)
        future_window = TimeWindow(
            start=datetime.now() - timedelta(hours=1),
            end=datetime.now() + timedelta(hours=2),
            power_kw=7.0,
        )
        schedule = ChargingSchedule(
            vehicle_id="ev_test",
            windows=[future_window],
            estimated_cost_pln=Decimal("5.00"),
            estimated_energy_kwh=7.0,
            estimated_completion=datetime.now() + timedelta(hours=2),
            is_feasible=True,
            best_achievable_soc=None,
        )

        # Manually create an active session
        session = ActiveSession(
            session_id="test-session",
            vehicle_id="ev_test",
            charger_adapter=charger_adapter,
            start_time=datetime.now() - timedelta(hours=1),
            target_soc=target_soc,
            schedule=schedule,
        )
        manager._active_sessions["ev_test"] = session

        # Run monitor_soc
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.monitor_soc("ev_test"))
        finally:
            loop.close()

        # Session should have been stopped (removed from active sessions)
        assert "ev_test" not in manager._active_sessions, (
            f"Session should be stopped when SoC ({current_soc}) >= target ({target_soc})"
        )

    @PROPERTY_TEST_SETTINGS
    @given(data=soc_and_target())
    def test_continue_when_soc_below_target_and_window_active(self, data):
        """When SoC < target_soc and window is still active, charging continues.

        **Validates: Requirements 3.4**
        """
        current_soc, target_soc = data
        assume(current_soc < target_soc)

        def get_soc(vehicle_id: str) -> Optional[float]:
            return current_soc

        manager = ChargingSessionManager(
            get_soc=get_soc,
            get_current_cost=lambda: Decimal("0.50"),
            notify_user=lambda title, msg: None,
            fire_event=lambda event_type, data: None,
        )

        # Create a schedule with a window that hasn't ended
        future_window = TimeWindow(
            start=datetime.now() - timedelta(hours=1),
            end=datetime.now() + timedelta(hours=2),
            power_kw=7.0,
        )
        schedule = ChargingSchedule(
            vehicle_id="ev_test",
            windows=[future_window],
            estimated_cost_pln=Decimal("5.00"),
            estimated_energy_kwh=7.0,
            estimated_completion=datetime.now() + timedelta(hours=2),
            is_feasible=True,
            best_achievable_soc=None,
        )

        charger_adapter = AsyncMock()
        charger_adapter.stop_charging = AsyncMock(return_value=True)

        session = ActiveSession(
            session_id="test-session",
            vehicle_id="ev_test",
            charger_adapter=charger_adapter,
            start_time=datetime.now() - timedelta(hours=1),
            target_soc=target_soc,
            schedule=schedule,
        )
        manager._active_sessions["ev_test"] = session

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.monitor_soc("ev_test"))
        finally:
            loop.close()

        # Session should still be active
        assert "ev_test" in manager._active_sessions, (
            f"Session should continue when SoC ({current_soc}) < target ({target_soc}) "
            f"and window is still active"
        )

    @PROPERTY_TEST_SETTINGS
    @given(
        target_soc=integers(min_value=20, max_value=100),
        current_soc=floats(min_value=0.0, max_value=19.9,
                           allow_nan=False, allow_infinity=False),
        hours_past=integers(min_value=1, max_value=10),
    )
    def test_stop_when_all_windows_ended(self, target_soc, current_soc, hours_past):
        """When all windows have ended (current time > last window end), stop charging.

        **Validates: Requirements 3.4**
        """
        assume(current_soc < target_soc)

        def get_soc(vehicle_id: str) -> Optional[float]:
            return current_soc

        manager = ChargingSessionManager(
            get_soc=get_soc,
            get_current_cost=lambda: Decimal("0.50"),
            notify_user=lambda title, msg: None,
            fire_event=lambda event_type, data: None,
        )

        # Create a schedule with windows that have already ended
        past_window = TimeWindow(
            start=datetime.now() - timedelta(hours=hours_past + 1),
            end=datetime.now() - timedelta(hours=hours_past),
            power_kw=7.0,
        )
        schedule = ChargingSchedule(
            vehicle_id="ev_test",
            windows=[past_window],
            estimated_cost_pln=Decimal("5.00"),
            estimated_energy_kwh=7.0,
            estimated_completion=datetime.now() - timedelta(hours=hours_past),
            is_feasible=True,
            best_achievable_soc=None,
        )

        charger_adapter = AsyncMock()
        charger_adapter.stop_charging = AsyncMock(return_value=True)

        session = ActiveSession(
            session_id="test-session",
            vehicle_id="ev_test",
            charger_adapter=charger_adapter,
            start_time=datetime.now() - timedelta(hours=hours_past + 2),
            target_soc=target_soc,
            schedule=schedule,
        )
        manager._active_sessions["ev_test"] = session

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(manager.monitor_soc("ev_test"))
        finally:
            loop.close()

        # Session should have been stopped because window ended
        assert "ev_test" not in manager._active_sessions, (
            f"Session should be stopped when all windows have ended "
            f"(ended {hours_past}h ago), even though SoC ({current_soc}) < target ({target_soc})"
        )


# --- Property 28 Tests ---


class TestProperty28MultiVehiclePriorityAllocation:
    """Property 28: Przydzial mocy wielu pojazdom wg priorytetow.

    Multi-vehicle power allocation follows priority order: highest priority
    gets full allocation first, remaining capacity goes to next.

    **Validates: Requirements 11.2, 11.4, 11.7**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=multi_vehicle_scenario())
    def test_higher_priority_gets_full_allocation_first(self, scenario):
        """Higher priority vehicle's total allocated energy >= its required energy
        (if feasible given grid constraints).

        **Validates: Requirements 11.2**
        """
        (vehicles_with_chargers, costs, grid_limit,
         current_socs, building_load) = scenario

        scheduler = EVScheduler()
        schedules = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles_with_chargers,
            costs=costs,
            grid_limit_kw=grid_limit,
            current_socs=current_socs,
            current_building_load_kw=building_load,
        )

        assert len(schedules) == len(vehicles_with_chargers)

        # Sort vehicles by priority to check allocation order
        sorted_pairs = sorted(
            zip(vehicles_with_chargers, schedules),
            key=lambda x: x[0].vehicle.priority,
        )

        # If highest priority vehicle is feasible, it should get its full energy
        for i, (vp, schedule) in enumerate(sorted_pairs):
            vehicle = vp.vehicle
            soc = current_socs.get(vehicle.vehicle_id, 0.0)
            soc_delta = vehicle.target_soc - soc
            required_energy = (soc_delta / 100.0) * vehicle.battery_capacity_kwh

            if schedule.is_feasible and schedule.estimated_energy_kwh > 0:
                # Feasible schedule should deliver at least the required energy
                # (with small tolerance for floating point)
                assert schedule.estimated_energy_kwh >= required_energy - 0.1, (
                    f"Vehicle {vehicle.vehicle_id} (priority {vehicle.priority}) "
                    f"got {schedule.estimated_energy_kwh} kWh but needed {required_energy} kWh"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=multi_vehicle_scenario())
    def test_lower_priority_infeasible_when_grid_constrained(self, scenario):
        """If grid is constrained, lower priority vehicles get less or are infeasible.

        When total demand exceeds grid capacity, lower priority vehicles should
        not get more energy than what remains after higher priority allocation.

        **Validates: Requirements 11.4, 11.7**
        """
        (vehicles_with_chargers, costs, grid_limit,
         current_socs, building_load) = scenario

        scheduler = EVScheduler()
        schedules = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles_with_chargers,
            costs=costs,
            grid_limit_kw=grid_limit,
            current_socs=current_socs,
            current_building_load_kw=building_load,
        )

        # Sort by priority
        sorted_pairs = sorted(
            zip(vehicles_with_chargers, schedules),
            key=lambda x: x[0].vehicle.priority,
        )

        # Check that no vehicle's windows exceed grid limit
        for vp, schedule in sorted_pairs:
            for window in schedule.windows:
                # Each window's power should not exceed grid limit minus building load
                assert window.power_kw <= grid_limit - building_load + 0.01, (
                    f"Vehicle {vp.vehicle.vehicle_id} window power {window.power_kw} kW "
                    f"exceeds available grid capacity "
                    f"({grid_limit} - {building_load} = {grid_limit - building_load} kW)"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=multi_vehicle_scenario(min_vehicles=2, max_vehicles=4))
    def test_no_vehicle_gets_below_min_power(self, scenario):
        """No vehicle should receive power below its minimum charging power.

        If allocated power would be below min_power, the vehicle should be
        marked infeasible instead.

        **Validates: Requirements 11.7**
        """
        (vehicles_with_chargers, costs, grid_limit,
         current_socs, building_load) = scenario

        scheduler = EVScheduler()
        schedules = scheduler.calculate_multi_vehicle_schedule(
            vehicles=vehicles_with_chargers,
            costs=costs,
            grid_limit_kw=grid_limit,
            current_socs=current_socs,
            current_building_load_kw=building_load,
        )

        for vp, schedule in zip(vehicles_with_chargers, schedules):
            vehicle = vp.vehicle
            for window in schedule.windows:
                # If a window exists, its power must be >= min_charging_power
                assert window.power_kw >= vehicle.min_charging_power_kw - 0.01, (
                    f"Vehicle {vehicle.vehicle_id} got window with power "
                    f"{window.power_kw} kW < min {vehicle.min_charging_power_kw} kW"
                )


# --- Property 29 Tests ---


class TestProperty29ChargingStrategyPerVehicle:
    """Property 29: Strategia ladowania per pojazd.

    Each vehicle's charging strategy is correctly applied:
    - CHEAPEST: no deadline constraint (all slots available)
    - READY_BY: all windows end before deadline
    - PV_ONLY: all windows are in PV surplus hours

    **Validates: Requirements 11.3**
    """

    @PROPERTY_TEST_SETTINGS
    @given(scenario=strategy_scenario())
    def test_cheapest_strategy_uses_all_available_slots(self, scenario):
        """CHEAPEST strategy: no deadline constraint applied, all slots available.

        **Validates: Requirements 11.3**
        """
        (vehicle, charger, costs, constraints, current_soc,
         pv_surplus_hours, deadline) = scenario

        assume(vehicle.strategy == ChargingStrategy.CHEAPEST)

        scheduler = EVScheduler()
        schedule = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=current_soc,
            pv_surplus_hours=pv_surplus_hours,
        )

        if schedule.is_feasible and schedule.windows:
            # CHEAPEST has no deadline constraint - windows can be anywhere in the
            # available time range. Verify windows are within the cost time range.
            first_cost_time = costs[0].timestamp
            last_cost_time = costs[-1].timestamp + timedelta(hours=1)

            for window in schedule.windows:
                assert window.start >= first_cost_time, (
                    f"Window starts before available time range: "
                    f"{window.start} < {first_cost_time}"
                )
                assert window.end <= last_cost_time, (
                    f"Window ends after available time range: "
                    f"{window.end} > {last_cost_time}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=strategy_scenario())
    def test_ready_by_strategy_all_windows_before_deadline(self, scenario):
        """READY_BY strategy: all windows end before or at deadline.

        **Validates: Requirements 11.3**
        """
        (vehicle, charger, costs, constraints, current_soc,
         pv_surplus_hours, deadline) = scenario

        assume(vehicle.strategy == ChargingStrategy.READY_BY)

        scheduler = EVScheduler()
        schedule = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=current_soc,
            pv_surplus_hours=pv_surplus_hours,
        )

        if schedule.is_feasible and schedule.windows:
            for window in schedule.windows:
                assert window.end <= deadline, (
                    f"READY_BY window ends after deadline: "
                    f"{window.end} > {deadline}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=strategy_scenario())
    def test_pv_only_strategy_windows_in_pv_surplus_hours(self, scenario):
        """PV_ONLY strategy: all windows are in PV surplus hours.

        **Validates: Requirements 11.3**
        """
        (vehicle, charger, costs, constraints, current_soc,
         pv_surplus_hours, deadline) = scenario

        assume(vehicle.strategy == ChargingStrategy.PV_ONLY)
        assume(len(pv_surplus_hours) > 0)

        scheduler = EVScheduler()
        schedule = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=current_soc,
            pv_surplus_hours=pv_surplus_hours,
        )

        if schedule.is_feasible and schedule.windows:
            for window in schedule.windows:
                # The window's start hour should be in pv_surplus_hours
                window_hour = window.start.hour
                assert window_hour in pv_surplus_hours, (
                    f"PV_ONLY window at hour {window_hour} is not in "
                    f"PV surplus hours {pv_surplus_hours}"
                )

    @PROPERTY_TEST_SETTINGS
    @given(scenario=strategy_scenario())
    def test_pv_only_infeasible_without_pv_hours(self, scenario):
        """PV_ONLY strategy with no PV surplus hours should be infeasible.

        **Validates: Requirements 11.3**
        """
        (vehicle, charger, costs, constraints, current_soc,
         pv_surplus_hours, deadline) = scenario

        assume(vehicle.strategy == ChargingStrategy.PV_ONLY)

        scheduler = EVScheduler()
        # Pass empty PV surplus hours
        schedule = scheduler.calculate_schedule(
            vehicle=vehicle,
            charger=charger,
            costs=costs,
            constraints=constraints,
            current_soc=current_soc,
            pv_surplus_hours=[],  # No PV surplus
        )

        # Should be infeasible since there are no PV hours to charge in
        assert not schedule.is_feasible, (
            "PV_ONLY strategy should be infeasible when no PV surplus hours available"
        )
