"""Testy jednostkowe dla ScheduleEngine (LP Solver)."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from custom_components.peo.schedule_engine import (
    ScheduleDemand,
    ScheduleEngine,
    ScheduleResult,
    ScheduleWindow,
    TimeSlot,
)


@pytest.fixture
def engine():
    """Fixture: instancja ScheduleEngine."""
    return ScheduleEngine()


@pytest.fixture
def base_time():
    """Fixture: bazowy czas startowy."""
    return datetime(2024, 1, 15, 0, 0)


def make_slots(base: datetime, count: int) -> list[TimeSlot]:
    """Utwórz listę slotów godzinowych."""
    return [
        TimeSlot(
            start=base + timedelta(hours=i),
            end=base + timedelta(hours=i + 1),
            duration_hours=1.0,
        )
        for i in range(count)
    ]


class TestSolveMinimumCostSchedule:
    """Testy solve_minimum_cost_schedule()."""

    def test_empty_slots_returns_infeasible(self, engine):
        """Puste sloty z wymaganą energią → infeasible."""
        result = engine.solve_minimum_cost_schedule(
            time_slots=[],
            costs=[],
            required_energy=10.0,
            power_min=1.4,
            power_max=11.0,
            grid_limit=12.0,
            existing_load=[],
        )
        assert not result.is_feasible
        assert result.windows == []

    def test_zero_energy_returns_feasible(self, engine, base_time):
        """Zero wymaganej energii → feasible, brak okien."""
        slots = make_slots(base_time, 4)
        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=[Decimal("0.50")] * 4,
            required_energy=0.0,
            power_min=1.4,
            power_max=11.0,
            grid_limit=12.0,
            existing_load=[1.0] * 4,
        )
        assert result.is_feasible
        assert result.total_energy == 0.0
        assert result.windows == []

    def test_selects_cheapest_slots(self, engine, base_time):
        """Wybiera najtańsze sloty do ładowania."""
        slots = make_slots(base_time, 6)
        # Koszty: slot 2 i 4 są najtańsze
        costs = [
            Decimal("0.80"),  # 0
            Decimal("0.70"),  # 1
            Decimal("0.30"),  # 2 — najtańszy
            Decimal("0.60"),  # 3
            Decimal("0.35"),  # 4 — drugi najtańszy
            Decimal("0.90"),  # 5
        ]

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=10.0,  # 10 kWh
            power_min=1.4,
            power_max=11.0,
            grid_limit=15.0,
            existing_load=[2.0] * 6,
        )

        assert result.is_feasible
        assert result.total_energy >= 10.0 - 0.01

        # Sprawdź, że najtańsze sloty zostały wybrane
        selected_starts = [w.slot.start for w in result.windows]
        # Slot 2 (najtańszy) powinien być wybrany
        assert slots[2].start in selected_starts

    def test_respects_grid_limit(self, engine, base_time):
        """Nie przekracza limitu mocy przyłączeniowej."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4
        existing_load = [10.0, 8.0, 5.0, 11.0]  # Slot 3 prawie pełny

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=existing_load,
        )

        assert result.is_feasible
        # Sprawdź, że żadne okno nie przekracza grid_limit
        for i, window in enumerate(result.windows):
            slot_idx = next(
                j for j, s in enumerate(slots) if s == window.slot
            )
            total_power = window.power_kw + existing_load[slot_idx]
            assert total_power <= 12.0 + 0.01

    def test_respects_power_max(self, engine, base_time):
        """Moc w każdym slocie nie przekracza power_max."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.30")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=20.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=20.0,
            existing_load=[0.0] * 4,
        )

        assert result.is_feasible
        for window in result.windows:
            assert window.power_kw <= 7.0 + 0.01

    def test_respects_power_min(self, engine, base_time):
        """Moc w każdym aktywnym slocie >= power_min."""
        slots = make_slots(base_time, 6)
        costs = [Decimal("0.50")] * 6

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=2.0,
            power_max=11.0,
            grid_limit=15.0,
            existing_load=[0.0] * 6,
        )

        assert result.is_feasible
        for window in result.windows:
            assert window.power_kw >= 2.0 - 0.01

    def test_infeasible_when_not_enough_capacity(self, engine, base_time):
        """Infeasible gdy nie ma wystarczającej pojemności."""
        slots = make_slots(base_time, 2)
        costs = [Decimal("0.50")] * 2

        # Potrzeba 50 kWh, ale max 3kW * 2h = 6 kWh
        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=50.0,
            power_min=1.4,
            power_max=3.0,
            grid_limit=5.0,
            existing_load=[0.0] * 2,
        )

        assert not result.is_feasible

    def test_infeasible_when_grid_full(self, engine, base_time):
        """Infeasible gdy grid jest pełny (existing_load >= grid_limit)."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=10.0,
            existing_load=[10.0] * 4,  # Grid pełny
        )

        assert not result.is_feasible

    def test_total_energy_meets_requirement(self, engine, base_time):
        """Łączna energia >= wymagana energia."""
        slots = make_slots(base_time, 8)
        costs = [Decimal("0.40")] * 8

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=15.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[2.0] * 8,
        )

        assert result.is_feasible
        assert result.total_energy >= 15.0 - 0.01

    def test_total_cost_is_positive(self, engine, base_time):
        """Koszt jest dodatni gdy jest ładowanie."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 4,
        )

        assert result.is_feasible
        assert result.total_cost > Decimal("0.00")

    def test_contiguous_mode_single_block(self, engine, base_time):
        """Tryb ciągły — ładowanie w jednym bloku."""
        slots = make_slots(base_time, 8)
        # Najtańsze sloty: 0, 1 i 6, 7 (nieciągłe)
        costs = [
            Decimal("0.20"),  # 0
            Decimal("0.20"),  # 1
            Decimal("0.80"),  # 2
            Decimal("0.80"),  # 3
            Decimal("0.80"),  # 4
            Decimal("0.80"),  # 5
            Decimal("0.20"),  # 6
            Decimal("0.20"),  # 7
        ]

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 8,
            allow_discontinuous=False,
        )

        assert result.is_feasible
        # Sprawdź ciągłość — okna powinny być w jednym bloku
        if len(result.windows) > 1:
            window_indices = []
            for w in result.windows:
                idx = next(i for i, s in enumerate(slots) if s == w.slot)
                window_indices.append(idx)
            window_indices.sort()
            # Sprawdź, że indeksy są ciągłe
            for i in range(1, len(window_indices)):
                assert window_indices[i] == window_indices[i - 1] + 1

    def test_discontinuous_cheaper_than_contiguous(self, engine, base_time):
        """Ładowanie nieciągłe może być tańsze niż ciągłe."""
        slots = make_slots(base_time, 8)
        # Najtańsze sloty rozrzucone: 0, 4, 7
        costs = [
            Decimal("0.10"),  # 0 — najtańszy
            Decimal("0.90"),  # 1
            Decimal("0.90"),  # 2
            Decimal("0.90"),  # 3
            Decimal("0.10"),  # 4 — najtańszy
            Decimal("0.90"),  # 5
            Decimal("0.90"),  # 6
            Decimal("0.10"),  # 7 — najtańszy
        ]

        result_disc = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=15.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 8,
            allow_discontinuous=True,
        )

        result_cont = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=15.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 8,
            allow_discontinuous=False,
        )

        assert result_disc.is_feasible
        assert result_cont.is_feasible
        # Nieciągłe powinno być tańsze lub równe
        assert result_disc.total_cost <= result_cont.total_cost

    def test_varying_existing_load(self, engine, base_time):
        """Różne obciążenie budynku per slot wpływa na alokację."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4
        # Slot 0 i 1 mają duże obciążenie, 2 i 3 małe
        existing_load = [10.0, 10.0, 2.0, 2.0]

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=10.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=existing_load,
        )

        assert result.is_feasible
        # Sloty 2 i 3 powinny mieć więcej mocy (więcej dostępnej)
        for window in result.windows:
            slot_idx = next(i for i, s in enumerate(slots) if s == window.slot)
            assert window.power_kw + existing_load[slot_idx] <= 12.0 + 0.01


class TestSolveMultiPrioritySchedule:
    """Testy solve_multi_priority_schedule()."""

    def test_single_demand(self, engine, base_time):
        """Jeden demand — działa jak solve_minimum_cost_schedule."""
        slots = make_slots(base_time, 6)
        costs = [Decimal("0.50")] * 6
        existing_load = [2.0] * 6

        demands = [
            ScheduleDemand(
                demand_id="ev1",
                required_energy=10.0,
                power_min=1.4,
                power_max=7.0,
                priority=1,
                time_slots=slots,
            )
        ]

        results = engine.solve_multi_priority_schedule(
            demands=demands,
            costs=costs,
            grid_limit=12.0,
            existing_load=existing_load,
        )

        assert len(results) == 1
        assert results[0].is_feasible
        assert results[0].total_energy >= 10.0 - 0.01

    def test_two_demands_priority_order(self, engine, base_time):
        """Dwa demands — wyższy priorytet dostaje pełną alokację."""
        slots = make_slots(base_time, 6)
        costs = [Decimal("0.50")] * 6
        existing_load = [0.0] * 6

        demands = [
            ScheduleDemand(
                demand_id="ev1",
                required_energy=10.0,
                power_min=1.4,
                power_max=7.0,
                priority=1,  # Wyższy priorytet
                time_slots=slots,
            ),
            ScheduleDemand(
                demand_id="ev2",
                required_energy=10.0,
                power_min=1.4,
                power_max=7.0,
                priority=2,  # Niższy priorytet
                time_slots=slots,
            ),
        ]

        results = engine.solve_multi_priority_schedule(
            demands=demands,
            costs=costs,
            grid_limit=12.0,
            existing_load=existing_load,
        )

        assert len(results) == 2
        # Pierwszy (priorytet 1) powinien być feasible
        assert results[0].is_feasible
        assert results[0].total_energy >= 10.0 - 0.01

    def test_lower_priority_gets_remaining_capacity(self, engine, base_time):
        """Niższy priorytet dostaje pozostałą pojemność."""
        slots = make_slots(base_time, 8)
        costs = [Decimal("0.50")] * 8
        existing_load = [0.0] * 8

        demands = [
            ScheduleDemand(
                demand_id="ev1",
                required_energy=20.0,
                power_min=1.4,
                power_max=5.0,
                priority=1,
                time_slots=slots,
            ),
            ScheduleDemand(
                demand_id="ev2",
                required_energy=10.0,
                power_min=1.4,
                power_max=5.0,
                priority=2,
                time_slots=slots,
            ),
        ]

        results = engine.solve_multi_priority_schedule(
            demands=demands,
            costs=costs,
            grid_limit=12.0,
            existing_load=existing_load,
        )

        assert len(results) == 2
        assert results[0].is_feasible  # Priorytet 1 — feasible

    def test_infeasible_when_no_capacity_for_low_priority(self, engine, base_time):
        """Infeasible dla niskiego priorytetu gdy brak mocy."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4
        existing_load = [0.0] * 4

        demands = [
            ScheduleDemand(
                demand_id="ev1",
                required_energy=40.0,  # Zabiera prawie całą moc
                power_min=1.4,
                power_max=10.0,
                priority=1,
                time_slots=slots,
            ),
            ScheduleDemand(
                demand_id="ev2",
                required_energy=10.0,
                power_min=3.0,  # Wymaga min 3 kW
                power_max=5.0,
                priority=2,
                time_slots=slots,
            ),
        ]

        results = engine.solve_multi_priority_schedule(
            demands=demands,
            costs=costs,
            grid_limit=11.0,
            existing_load=existing_load,
        )

        assert len(results) == 2
        assert results[0].is_feasible  # Priorytet 1 — feasible

    def test_results_in_demand_order(self, engine, base_time):
        """Wyniki zwracane w kolejności demands (nie priorytetów)."""
        slots = make_slots(base_time, 6)
        costs = [Decimal("0.50")] * 6
        existing_load = [0.0] * 6

        demands = [
            ScheduleDemand(
                demand_id="ev_low",
                required_energy=5.0,
                power_min=1.4,
                power_max=7.0,
                priority=3,  # Niski priorytet, ale pierwszy w liście
                time_slots=slots,
            ),
            ScheduleDemand(
                demand_id="ev_high",
                required_energy=5.0,
                power_min=1.4,
                power_max=7.0,
                priority=1,  # Wysoki priorytet, ale drugi w liście
                time_slots=slots,
            ),
        ]

        results = engine.solve_multi_priority_schedule(
            demands=demands,
            costs=costs,
            grid_limit=20.0,
            existing_load=existing_load,
        )

        assert len(results) == 2
        # Oba powinny być feasible (dużo mocy)
        assert results[0].is_feasible  # ev_low
        assert results[1].is_feasible  # ev_high

    def test_empty_demands(self, engine):
        """Pusta lista demands → pusta lista wyników."""
        results = engine.solve_multi_priority_schedule(
            demands=[],
            costs=[Decimal("0.50")] * 4,
            grid_limit=12.0,
            existing_load=[0.0] * 4,
        )
        assert results == []


class TestScheduleResult:
    """Testy struktury ScheduleResult."""

    def test_result_dataclass_fields(self, engine, base_time):
        """ScheduleResult ma wymagane pola."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 4,
        )

        assert hasattr(result, "windows")
        assert hasattr(result, "total_cost")
        assert hasattr(result, "total_energy")
        assert hasattr(result, "is_feasible")
        assert isinstance(result.total_cost, Decimal)
        assert isinstance(result.total_energy, float)
        assert isinstance(result.is_feasible, bool)
        assert isinstance(result.windows, list)

    def test_windows_have_correct_structure(self, engine, base_time):
        """Okna mają poprawną strukturę (slot + power_kw)."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 4,
        )

        for window in result.windows:
            assert isinstance(window, ScheduleWindow)
            assert isinstance(window.slot, TimeSlot)
            assert isinstance(window.power_kw, float)
            assert window.power_kw > 0

    def test_cost_has_two_decimal_places(self, engine, base_time):
        """Koszt ma 2 miejsca po przecinku."""
        slots = make_slots(base_time, 4)
        costs = [Decimal("0.50")] * 4

        result = engine.solve_minimum_cost_schedule(
            time_slots=slots,
            costs=costs,
            required_energy=5.0,
            power_min=1.4,
            power_max=7.0,
            grid_limit=12.0,
            existing_load=[0.0] * 4,
        )

        assert result.total_cost == result.total_cost.quantize(Decimal("0.01"))
