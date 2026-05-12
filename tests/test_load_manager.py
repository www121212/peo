"""Testy jednostkowe dla LoadManager."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest

from custom_components.peo.load_manager import LoadManager
from custom_components.peo.models import HourlyCost, LoadConfig, LoadDecision, TimeWindow
from custom_components.peo.enums import TimeZoneName
from custom_components.peo.models import TariffRates


# --- Fixtures ---


@pytest.fixture
def load_manager():
    """Fixture: LoadManager z domyślnym limitem mocy 12 kW."""
    return LoadManager(grid_limit_kw=12.0)


@pytest.fixture
def sample_load():
    """Fixture: Przykładowy odbiornik (bojler CWU)."""
    return LoadConfig(
        load_id="load_cwu",
        name="Bojler CWU",
        entity_id="switch.bojler",
        threshold_on=Decimal("0.35"),
        threshold_off=Decimal("0.55"),
        min_daily_hours=2.0,
        max_daily_hours=6.0,
        allowed_start=time(22, 0),
        allowed_end=time(6, 0),
        priority=1,
        power_w=2000,
        failsafe_state=True,
    )


@pytest.fixture
def daytime_load():
    """Fixture: Odbiornik z oknem dziennym (06:00–22:00)."""
    return LoadConfig(
        load_id="load_pump",
        name="Pompa ciepła",
        entity_id="switch.pompa",
        threshold_on=Decimal("0.40"),
        threshold_off=Decimal("0.60"),
        min_daily_hours=4.0,
        max_daily_hours=10.0,
        allowed_start=time(6, 0),
        allowed_end=time(22, 0),
        priority=2,
        power_w=3000,
        failsafe_state=False,
    )


@pytest.fixture
def sample_rates():
    """Fixture: Stawki taryfowe do tworzenia HourlyCost."""
    return TariffRates(
        energy_price=Decimal("0.3000"),
        distribution_variable=Decimal("0.1000"),
        transition_fee=Decimal("0.0009"),
        oze_fee=Decimal("0.0027"),
        capacity_fee=Decimal("0.0500"),
        cogeneration_fee=Decimal("0.0050"),
    )


def _make_hourly_costs(
    start: datetime, hours: int, costs: list[Decimal], rates: TariffRates
) -> list[HourlyCost]:
    """Helper: Utwórz listę HourlyCost z podanych kosztów."""
    result = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        cost = costs[i] if i < len(costs) else costs[-1]
        result.append(
            HourlyCost(
                hour=ts.hour,
                timestamp=ts,
                cost_pln_kwh=cost,
                zone=TimeZoneName.POZASZCZYT,
                components=rates,
            )
        )
    return result


# --- Tests for evaluate_loads ---


class TestEvaluateLoads:
    """Testy dla evaluate_loads."""

    def test_turn_on_when_cost_below_threshold(self, load_manager, sample_load):
        """Włącz odbiornik gdy koszt < threshold_on."""
        now = datetime(2024, 1, 15, 23, 0)  # 23:00 — w oknie 22:00–06:00
        current_cost = Decimal("0.30")  # < 0.35 threshold_on
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert len(decisions) == 1
        assert decisions[0].action == "on"
        assert decisions[0].load_id == "load_cwu"

    def test_turn_off_when_cost_above_threshold(self, load_manager, sample_load):
        """Wyłącz odbiornik gdy koszt > threshold_off."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.60")  # > 0.55 threshold_off
        load_states = {"load_cwu": {"is_on": True, "daily_runtime_hours": 1.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert len(decisions) == 1
        assert decisions[0].action == "off"

    def test_maintain_state_when_cost_between_thresholds(self, load_manager, sample_load):
        """Utrzymaj stan gdy koszt pomiędzy progami."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.45")  # between 0.35 and 0.55

        # Gdy jest włączony — utrzymaj "on"
        load_states = {"load_cwu": {"is_on": True, "daily_runtime_hours": 1.0, "manual_override": False}}
        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)
        assert decisions[0].action == "on"

        # Gdy jest wyłączony — utrzymaj "off"
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 1.0, "manual_override": False}}
        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)
        assert decisions[0].action == "off"

    def test_blocked_when_max_hours_reached(self, load_manager, sample_load):
        """Zablokuj gdy osiągnięto max_daily_hours."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.20")  # poniżej progu — normalnie włączyłby
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 6.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "blocked"

    def test_off_when_outside_time_window(self, load_manager, sample_load):
        """Wyłącz gdy poza dozwolonym oknem czasowym."""
        now = datetime(2024, 1, 15, 12, 0)  # 12:00 — poza oknem 22:00–06:00
        current_cost = Decimal("0.20")  # poniżej progu
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "off"
        assert "oknem czasowym" in decisions[0].reason

    def test_manual_override_respected(self, load_manager, sample_load):
        """Respektuj sterowanie ręczne."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.20")
        load_states = {"load_cwu": {"is_on": True, "daily_runtime_hours": 1.0, "manual_override": True}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "manual_override"

    def test_multiple_loads(self, load_manager, sample_load, daytime_load):
        """Obsługa wielu odbiorników jednocześnie."""
        now = datetime(2024, 1, 15, 10, 0)  # 10:00 — w oknie dziennym, poza nocnym
        current_cost = Decimal("0.30")
        load_states = {
            "load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False},
            "load_pump": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False},
        }

        decisions = load_manager.evaluate_loads(
            current_cost, [sample_load, daytime_load], load_states, now
        )

        assert len(decisions) == 2
        # Bojler poza oknem (22:00–06:00) → off
        assert decisions[0].action == "off"
        # Pompa w oknie (06:00–22:00), koszt 0.30 < 0.40 → on
        assert decisions[1].action == "on"

    def test_max_loads_limit(self, load_manager, sample_load):
        """Ograniczenie do MAX_LOADS (16) odbiorników."""
        loads = [
            LoadConfig(
                load_id=f"load_{i}",
                name=f"Load {i}",
                entity_id=f"switch.load_{i}",
                threshold_on=Decimal("0.35"),
                threshold_off=Decimal("0.55"),
                min_daily_hours=1.0,
                max_daily_hours=6.0,
                allowed_start=time(0, 0),
                allowed_end=time(23, 59),
                priority=i,
                power_w=1000,
                failsafe_state=False,
            )
            for i in range(1, 20)  # 19 loads — exceeds MAX_LOADS=16
        ]
        now = datetime(2024, 1, 15, 12, 0)
        current_cost = Decimal("0.30")
        load_states = {}

        decisions = load_manager.evaluate_loads(current_cost, loads, load_states, now)

        assert len(decisions) == 16  # Capped at MAX_LOADS

    def test_missing_load_state_uses_defaults(self, load_manager, sample_load):
        """Brak stanu odbiornika — użyj domyślnych wartości."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.20")
        load_states = {}  # Brak stanu dla load_cwu

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "on"


# --- Tests for ensure_minimum_runtime ---


class TestEnsureMinimumRuntime:
    """Testy dla ensure_minimum_runtime."""

    def test_no_windows_when_runtime_met(self, load_manager, sample_load, sample_rates):
        """Brak okien gdy minimalny czas pracy osiągnięty."""
        remaining_costs = _make_hourly_costs(
            datetime(2024, 1, 15, 22, 0),
            8,
            [Decimal("0.30")] * 8,
            sample_rates,
        )

        windows = load_manager.ensure_minimum_runtime(
            sample_load, remaining_costs, current_runtime_hours=2.0
        )

        assert windows == []

    def test_selects_cheapest_hours(self, load_manager, sample_load, sample_rates):
        """Wybiera najtańsze godziny w dozwolonym oknie."""
        # Koszty: 22:00=0.50, 23:00=0.20, 00:00=0.30, 01:00=0.10, 02:00=0.40
        start = datetime(2024, 1, 15, 22, 0)
        costs = [
            Decimal("0.50"),
            Decimal("0.20"),
            Decimal("0.30"),
            Decimal("0.10"),
            Decimal("0.40"),
        ]
        remaining_costs = _make_hourly_costs(start, 5, costs, sample_rates)

        # Potrzeba 2h (min_daily_hours=2.0, current=0.0)
        windows = load_manager.ensure_minimum_runtime(
            sample_load, remaining_costs, current_runtime_hours=0.0
        )

        assert len(windows) == 2
        # Najtańsze: 01:00 (0.10) i 23:00 (0.20)
        window_hours = [w.start.hour for w in windows]
        assert 1 in window_hours  # 0.10
        assert 23 in window_hours  # 0.20

    def test_windows_sorted_chronologically(self, load_manager, sample_load, sample_rates):
        """Okna posortowane chronologicznie."""
        start = datetime(2024, 1, 15, 22, 0)
        costs = [Decimal("0.50"), Decimal("0.10"), Decimal("0.30"), Decimal("0.20")]
        remaining_costs = _make_hourly_costs(start, 4, costs, sample_rates)

        windows = load_manager.ensure_minimum_runtime(
            sample_load, remaining_costs, current_runtime_hours=0.0
        )

        # Powinny być posortowane po start
        for i in range(len(windows) - 1):
            assert windows[i].start <= windows[i + 1].start

    def test_only_hours_within_allowed_window(self, load_manager, daytime_load, sample_rates):
        """Wybiera tylko godziny w dozwolonym oknie czasowym."""
        # Okno dzienne: 06:00–22:00
        # Podajemy godziny 04:00–08:00 — tylko 06:00, 07:00 kwalifikują się
        start = datetime(2024, 1, 15, 4, 0)
        costs = [
            Decimal("0.10"),  # 04:00 — poza oknem
            Decimal("0.10"),  # 05:00 — poza oknem
            Decimal("0.50"),  # 06:00 — w oknie
            Decimal("0.30"),  # 07:00 — w oknie
            Decimal("0.40"),  # 08:00 — w oknie
        ]
        remaining_costs = _make_hourly_costs(start, 5, costs, sample_rates)

        windows = load_manager.ensure_minimum_runtime(
            daytime_load, remaining_costs, current_runtime_hours=1.0
        )

        # Potrzeba 3h (min=4.0, current=1.0), ale dostępne tylko 3 godziny w oknie
        assert len(windows) == 3
        for w in windows:
            assert w.start.hour >= 6

    def test_partial_runtime_needed(self, load_manager, sample_load, sample_rates):
        """Potrzeba tylko częściowego uzupełnienia czasu pracy."""
        start = datetime(2024, 1, 15, 22, 0)
        costs = [Decimal("0.30"), Decimal("0.20"), Decimal("0.40"), Decimal("0.10")]
        remaining_costs = _make_hourly_costs(start, 4, costs, sample_rates)

        # min=2.0h, current=1.5h → potrzeba 0.5h, ale planujemy pełne godziny
        # Algorytm wybierze 1 godzinę (najtańszą)
        windows = load_manager.ensure_minimum_runtime(
            sample_load, remaining_costs, current_runtime_hours=1.5
        )

        # Potrzeba < 1h, ale planujemy minimum 1 godzinę (granulacja godzinowa)
        assert len(windows) >= 1

    def test_empty_remaining_costs(self, load_manager, sample_load):
        """Pusta lista kosztów — brak okien."""
        windows = load_manager.ensure_minimum_runtime(
            sample_load, [], current_runtime_hours=0.0
        )

        assert windows == []

    def test_window_power_matches_load(self, load_manager, sample_load, sample_rates):
        """Moc w oknie odpowiada mocy odbiornika."""
        start = datetime(2024, 1, 15, 23, 0)
        costs = [Decimal("0.20")]
        remaining_costs = _make_hourly_costs(start, 1, costs, sample_rates)

        windows = load_manager.ensure_minimum_runtime(
            sample_load, remaining_costs, current_runtime_hours=0.0
        )

        assert len(windows) >= 1
        assert windows[0].power_kw == 2.0  # 2000W = 2.0 kW


# --- Tests for check_power_budget ---


class TestCheckPowerBudget:
    """Testy dla check_power_budget."""

    def test_all_loads_fit(self, load_manager):
        """Wszystkie odbiorniki mieszczą się w budżecie."""
        loads = [
            LoadConfig(
                load_id="load_1", name="L1", entity_id="switch.l1",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=1, power_w=2000, failsafe_state=False,
            ),
            LoadConfig(
                load_id="load_2", name="L2", entity_id="switch.l2",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=2, power_w=3000, failsafe_state=False,
            ),
        ]

        # Budynek: 5 kW, limit: 12 kW → dostępne 7 kW
        # Load 1: 2 kW, Load 2: 3 kW → razem 5 kW < 7 kW
        result = load_manager.check_power_budget(loads, current_building_load_kw=5.0)

        assert len(result) == 2

    def test_priority_ordering(self, load_manager):
        """Odbiorniki o wyższym priorytecie mają pierwszeństwo."""
        loads = [
            LoadConfig(
                load_id="load_low", name="Low", entity_id="switch.low",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=5, power_w=4000, failsafe_state=False,
            ),
            LoadConfig(
                load_id="load_high", name="High", entity_id="switch.high",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=1, power_w=4000, failsafe_state=False,
            ),
        ]

        # Budynek: 5 kW, limit: 12 kW → dostępne 7 kW
        # Oba po 4 kW — zmieści się tylko jeden (priorytet 1)
        result = load_manager.check_power_budget(loads, current_building_load_kw=5.0)

        assert len(result) == 1
        assert result[0].load_id == "load_high"

    def test_no_loads_when_no_power_available(self, load_manager):
        """Brak odbiorników gdy brak dostępnej mocy."""
        loads = [
            LoadConfig(
                load_id="load_1", name="L1", entity_id="switch.l1",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=1, power_w=1000, failsafe_state=False,
            ),
        ]

        # Budynek: 12 kW = limit → dostępne 0 kW
        result = load_manager.check_power_budget(loads, current_building_load_kw=12.0)

        assert result == []

    def test_custom_grid_limit(self, load_manager):
        """Użycie niestandardowego limitu mocy."""
        loads = [
            LoadConfig(
                load_id="load_1", name="L1", entity_id="switch.l1",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=1, power_w=5000, failsafe_state=False,
            ),
        ]

        # Budynek: 3 kW, custom limit: 6 kW → dostępne 3 kW
        # Load: 5 kW > 3 kW → nie zmieści się
        result = load_manager.check_power_budget(
            loads, current_building_load_kw=3.0, grid_limit_kw=6.0
        )

        assert result == []

    def test_partial_fit(self, load_manager):
        """Część odbiorników mieści się w budżecie."""
        loads = [
            LoadConfig(
                load_id="load_1", name="L1", entity_id="switch.l1",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=1, power_w=2000, failsafe_state=False,
            ),
            LoadConfig(
                load_id="load_2", name="L2", entity_id="switch.l2",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=2, power_w=2000, failsafe_state=False,
            ),
            LoadConfig(
                load_id="load_3", name="L3", entity_id="switch.l3",
                threshold_on=Decimal("0.35"), threshold_off=Decimal("0.55"),
                min_daily_hours=1.0, max_daily_hours=6.0,
                allowed_start=time(0, 0), allowed_end=time(23, 59),
                priority=3, power_w=2000, failsafe_state=False,
            ),
        ]

        # Budynek: 8 kW, limit: 12 kW → dostępne 4 kW
        # Load 1: 2 kW (ok, total=2), Load 2: 2 kW (ok, total=4), Load 3: 2 kW (nope, total=6>4)
        result = load_manager.check_power_budget(loads, current_building_load_kw=8.0)

        assert len(result) == 2
        assert result[0].load_id == "load_1"
        assert result[1].load_id == "load_2"

    def test_empty_loads_list(self, load_manager):
        """Pusta lista odbiorników."""
        result = load_manager.check_power_budget([], current_building_load_kw=5.0)

        assert result == []


# --- Tests for time window handling ---


class TestTimeWindow:
    """Testy obsługi okien czasowych."""

    def test_overnight_window_before_midnight(self, load_manager, sample_load):
        """Okno nocne (22:00–06:00) — czas przed północą."""
        now = datetime(2024, 1, 15, 23, 30)  # 23:30
        current_cost = Decimal("0.20")
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "on"

    def test_overnight_window_after_midnight(self, load_manager, sample_load):
        """Okno nocne (22:00–06:00) — czas po północy."""
        now = datetime(2024, 1, 16, 3, 0)  # 03:00
        current_cost = Decimal("0.20")
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "on"

    def test_overnight_window_outside(self, load_manager, sample_load):
        """Okno nocne (22:00–06:00) — czas poza oknem."""
        now = datetime(2024, 1, 15, 15, 0)  # 15:00
        current_cost = Decimal("0.20")
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].action == "off"
        assert "oknem czasowym" in decisions[0].reason

    def test_daytime_window_inside(self, load_manager, daytime_load):
        """Okno dzienne (06:00–22:00) — czas w oknie."""
        now = datetime(2024, 1, 15, 12, 0)  # 12:00
        current_cost = Decimal("0.30")  # < 0.40 threshold_on
        load_states = {"load_pump": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [daytime_load], load_states, now)

        assert decisions[0].action == "on"

    def test_daytime_window_outside(self, load_manager, daytime_load):
        """Okno dzienne (06:00–22:00) — czas poza oknem."""
        now = datetime(2024, 1, 15, 3, 0)  # 03:00
        current_cost = Decimal("0.30")
        load_states = {"load_pump": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [daytime_load], load_states, now)

        assert decisions[0].action == "off"


# --- Tests for edge cases ---


class TestEdgeCases:
    """Testy przypadków brzegowych."""

    def test_cost_exactly_at_threshold_on(self, load_manager, sample_load):
        """Koszt dokładnie równy threshold_on — nie włączaj (wymaga <)."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.35")  # == threshold_on
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        # Koszt == threshold_on, nie jest < threshold_on, więc nie włączamy
        # Koszt nie jest > threshold_off (0.55), więc utrzymujemy stan (off)
        assert decisions[0].action == "off"

    def test_cost_exactly_at_threshold_off(self, load_manager, sample_load):
        """Koszt dokładnie równy threshold_off — nie wyłączaj (wymaga >)."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.55")  # == threshold_off
        load_states = {"load_cwu": {"is_on": True, "daily_runtime_hours": 1.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        # Koszt == threshold_off, nie jest > threshold_off, więc utrzymujemy stan (on)
        assert decisions[0].action == "on"

    def test_decision_contains_timestamp(self, load_manager, sample_load):
        """Decyzja zawiera poprawny timestamp."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.20")
        load_states = {"load_cwu": {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False}}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].timestamp == now

    def test_decision_contains_load_id(self, load_manager, sample_load):
        """Decyzja zawiera poprawny load_id."""
        now = datetime(2024, 1, 15, 23, 0)
        current_cost = Decimal("0.20")
        load_states = {}

        decisions = load_manager.evaluate_loads(current_cost, [sample_load], load_states, now)

        assert decisions[0].load_id == "load_cwu"
