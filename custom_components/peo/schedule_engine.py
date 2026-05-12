"""Silnik harmonogramowania (Schedule Engine) — LP solver dla PEO.

Odpowiedzialność: Wspólny solver LP dla EV i Load Shifting.
Minimalizuje koszt energii przy ograniczeniach mocy, czasu i energii.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

import numpy as np
from scipy.optimize import linprog


@dataclass(frozen=True)
class TimeSlot:
    """Slot czasowy dostępny do ładowania/pracy."""

    start: datetime
    end: datetime
    duration_hours: float = 1.0


@dataclass(frozen=True)
class ScheduleWindow:
    """Okno w harmonogramie z przypisaną mocą."""

    slot: TimeSlot
    power_kw: float


@dataclass(frozen=True)
class ScheduleResult:
    """Wynik optymalizacji harmonogramu."""

    windows: list[ScheduleWindow]
    total_cost: Decimal
    total_energy: float
    is_feasible: bool


@dataclass(frozen=True)
class ScheduleDemand:
    """Zapotrzebowanie na energię jednego odbiorcy (pojazdu/odbiornika)."""

    demand_id: str
    required_energy: float  # kWh
    power_min: float  # kW — minimalna moc ładowania (lub 0)
    power_max: float  # kW — maksymalna moc ładowania
    priority: int  # 1 = najwyższy
    time_slots: list[TimeSlot]
    allow_discontinuous: bool = True


class ScheduleEngine:
    """Silnik optymalizacji harmonogramów (LP solver).

    Używa scipy.optimize.linprog do minimalizacji kosztu energii
    przy ograniczeniach mocy przyłączeniowej, mocy ładowarki i wymaganej energii.
    Dla ograniczenia min_power (moc >= power_min LUB == 0) stosuje podejście
    greedy (sortowanie slotów po koszcie).
    """

    def solve_minimum_cost_schedule(
        self,
        time_slots: list[TimeSlot],
        costs: list[Decimal],
        required_energy: float,
        power_min: float,
        power_max: float,
        grid_limit: float,
        existing_load: list[float],
        allow_discontinuous: bool = True,
    ) -> ScheduleResult:
        """Rozwiąż problem minimalizacji kosztu ładowania.

        Minimalizuje: Σ(cost[h] × power[h]) dla każdego slotu h
        Pod warunkami:
          - Σ(power[h] × duration[h]) >= required_energy
          - power[h] <= power_max
          - power[h] + existing_load[h] <= grid_limit
          - power[h] >= power_min OR power[h] == 0 (greedy)
          - Jeśli not allow_discontinuous: ładowanie w jednym ciągłym bloku

        Args:
            time_slots: Lista dostępnych slotów czasowych.
            costs: Lista kosztów (Decimal, PLN/kWh) dla każdego slotu.
            required_energy: Wymagana energia do doładowania (kWh).
            power_min: Minimalna moc ładowania (kW) — jeśli ładuje, to >= power_min.
            power_max: Maksymalna moc ładowania (kW).
            grid_limit: Limit mocy przyłączeniowej budynku (kW).
            existing_load: Istniejące obciążenie budynku per slot (kW).
            allow_discontinuous: Czy ładowanie może być nieciągłe.

        Returns:
            ScheduleResult z oknami ładowania, kosztem i flagą feasibility.
        """
        n = len(time_slots)

        if n == 0 or required_energy <= 0:
            return ScheduleResult(
                windows=[],
                total_cost=Decimal("0.00"),
                total_energy=0.0,
                is_feasible=(required_energy <= 0),
            )

        # Oblicz dostępną moc per slot (uwzględniając grid_limit i existing_load)
        available_power = []
        for i in range(n):
            avail = min(power_max, grid_limit - existing_load[i])
            available_power.append(max(0.0, avail))

        # Sprawdź czy power_min jest spełnialny w jakimkolwiek slocie
        feasible_slots = [
            i for i in range(n) if available_power[i] >= power_min
        ]

        if not feasible_slots:
            return ScheduleResult(
                windows=[],
                total_cost=Decimal("0.00"),
                total_energy=0.0,
                is_feasible=False,
            )

        # Greedy approach: sortuj feasible sloty po koszcie, wypełniaj najtańsze
        # To rozwiązuje problem min_power-or-zero (mixed-integer)
        slot_info = []
        for i in feasible_slots:
            effective_power = min(available_power[i], power_max)
            # Upewnij się, że effective_power >= power_min
            if effective_power < power_min:
                continue
            slot_info.append({
                "index": i,
                "cost": float(costs[i]),
                "power_max": effective_power,
                "duration": time_slots[i].duration_hours,
            })

        if not slot_info:
            return ScheduleResult(
                windows=[],
                total_cost=Decimal("0.00"),
                total_energy=0.0,
                is_feasible=False,
            )

        # Sortuj po koszcie (najtańsze najpierw)
        slot_info.sort(key=lambda s: s["cost"])

        if not allow_discontinuous:
            # Znajdź najtańszy ciągły blok
            return self._solve_contiguous(
                time_slots, costs, required_energy, power_min,
                power_max, available_power, slot_info, feasible_slots,
            )

        # Greedy: wypełniaj najtańsze sloty
        allocated = []
        remaining_energy = required_energy

        for slot in slot_info:
            if remaining_energy <= 0:
                break

            idx = slot["index"]
            max_energy_in_slot = slot["power_max"] * slot["duration"]
            energy_to_allocate = min(remaining_energy, max_energy_in_slot)

            # Oblicz moc — musi być >= power_min
            power = energy_to_allocate / slot["duration"]
            if power < power_min:
                # Potrzebujemy mniej energii niż power_min * duration
                # Ale musimy ładować z co najmniej power_min
                power = power_min
                energy_to_allocate = power * slot["duration"]

            allocated.append({
                "index": idx,
                "power": power,
                "energy": energy_to_allocate,
                "duration": slot["duration"],
            })
            remaining_energy -= energy_to_allocate

        if remaining_energy > 1e-6:
            # Nie da się dostarczyć wymaganej energii
            # Zwróć najlepszy możliwy wynik z is_feasible=False
            return self._build_result(
                time_slots, costs, allocated, is_feasible=False
            )

        # Optymalizacja LP: mając wybrane sloty, zoptymalizuj moc w każdym
        # (greedy już daje dobre wyniki, ale LP może poprawić alokację)
        result = self._optimize_with_lp(
            time_slots, costs, required_energy, power_min,
            power_max, available_power, allocated,
        )

        if result is not None:
            return result

        # Fallback do greedy result
        return self._build_result(time_slots, costs, allocated, is_feasible=True)

    def solve_multi_priority_schedule(
        self,
        demands: list[ScheduleDemand],
        costs: list[Decimal],
        grid_limit: float,
        existing_load: list[float],
    ) -> list[ScheduleResult]:
        """Rozwiąż problem wielu odbiorców z priorytetami.

        Alokuje moc sekwencyjnie wg priorytetu:
        - Najwyższy priorytet (1) dostaje pełną alokację pierwszy
        - Pozostała pojemność trafia do kolejnych odbiorców
        - Jeśli pozostała pojemność < min_power odbiorcy, pomijamy go

        Args:
            demands: Lista zapotrzebowań (posortowana wg priorytetu).
            costs: Lista kosztów per slot.
            grid_limit: Limit mocy przyłączeniowej.
            existing_load: Istniejące obciążenie per slot.

        Returns:
            Lista ScheduleResult — jeden per demand (w kolejności demands).
        """
        # Sortuj demands wg priorytetu (1 = najwyższy)
        sorted_demands = sorted(demands, key=lambda d: d.priority)

        # Śledzenie zużytej mocy per slot
        n = len(costs)
        used_power = list(existing_load)
        results: dict[str, ScheduleResult] = {}

        for demand in sorted_demands:
            # Oblicz remaining capacity per slot
            remaining_load = [used_power[i] for i in range(n)]

            # Filtruj sloty do tych dostępnych dla tego demand
            demand_slot_indices = []
            for slot in demand.time_slots:
                # Znajdź indeks slotu w globalnej liście
                for i in range(n):
                    if i < len(demand.time_slots) and demand.time_slots[i] == slot:
                        demand_slot_indices.append(i)

            # Użyj indeksów slotów demand bezpośrednio
            # (zakładamy, że time_slots w demand odpowiadają indeksom w costs)
            available_slots = []
            available_costs = []
            available_existing = []

            for i, slot in enumerate(demand.time_slots):
                if i < n:
                    available_slots.append(slot)
                    available_costs.append(costs[i])
                    available_existing.append(used_power[i])

            if not available_slots:
                results[demand.demand_id] = ScheduleResult(
                    windows=[],
                    total_cost=Decimal("0.00"),
                    total_energy=0.0,
                    is_feasible=False,
                )
                continue

            # Sprawdź czy jest wystarczająca moc dla tego demand
            max_available = max(
                grid_limit - used_power[i]
                for i in range(min(len(demand.time_slots), n))
            )

            if max_available < demand.power_min:
                # Brak wystarczającej mocy — pomijamy
                results[demand.demand_id] = ScheduleResult(
                    windows=[],
                    total_cost=Decimal("0.00"),
                    total_energy=0.0,
                    is_feasible=False,
                )
                continue

            # Rozwiąż harmonogram dla tego demand
            result = self.solve_minimum_cost_schedule(
                time_slots=available_slots,
                costs=available_costs,
                required_energy=demand.required_energy,
                power_min=demand.power_min,
                power_max=demand.power_max,
                grid_limit=grid_limit,
                existing_load=available_existing,
                allow_discontinuous=demand.allow_discontinuous,
            )

            results[demand.demand_id] = result

            # Zaktualizuj used_power na podstawie alokacji
            if result.is_feasible:
                for window in result.windows:
                    # Znajdź indeks slotu
                    for i, slot in enumerate(available_slots):
                        if slot == window.slot and i < n:
                            used_power[i] += window.power_kw
                            break

        # Zwróć wyniki w oryginalnej kolejności demands
        return [results[d.demand_id] for d in demands]

    def _solve_contiguous(
        self,
        time_slots: list[TimeSlot],
        costs: list[Decimal],
        required_energy: float,
        power_min: float,
        power_max: float,
        available_power: list[float],
        slot_info: list[dict],
        feasible_slots: list[int],
    ) -> ScheduleResult:
        """Znajdź najtańszy ciągły blok ładowania.

        Przeszukuje wszystkie możliwe ciągłe bloki i wybiera najtańszy.
        """
        n = len(time_slots)
        best_result: Optional[ScheduleResult] = None
        best_cost = float("inf")

        # Próbuj wszystkie ciągłe bloki
        for start_idx in range(n):
            if start_idx not in feasible_slots:
                continue

            allocated = []
            remaining = required_energy
            block_cost = 0.0

            for end_idx in range(start_idx, n):
                if end_idx not in feasible_slots:
                    break

                avail = available_power[end_idx]
                if avail < power_min:
                    break

                duration = time_slots[end_idx].duration_hours
                max_energy = min(avail, power_max) * duration
                energy = min(remaining, max_energy)
                power = energy / duration

                if power < power_min:
                    power = power_min
                    energy = power * duration

                allocated.append({
                    "index": end_idx,
                    "power": power,
                    "energy": energy,
                    "duration": duration,
                })
                remaining -= energy
                block_cost += float(costs[end_idx]) * energy

                if remaining <= 1e-6:
                    # Blok wystarczający
                    if block_cost < best_cost:
                        best_cost = block_cost
                        best_result = self._build_result(
                            time_slots, costs, allocated, is_feasible=True
                        )
                    break

        if best_result is not None:
            return best_result

        # Nie znaleziono ciągłego bloku — infeasible
        return ScheduleResult(
            windows=[],
            total_cost=Decimal("0.00"),
            total_energy=0.0,
            is_feasible=False,
        )

    def _optimize_with_lp(
        self,
        time_slots: list[TimeSlot],
        costs: list[Decimal],
        required_energy: float,
        power_min: float,
        power_max: float,
        available_power: list[float],
        greedy_allocated: list[dict],
    ) -> Optional[ScheduleResult]:
        """Optymalizuj alokację mocy w wybranych slotach za pomocą LP.

        Mając zestaw slotów wybranych przez greedy, optymalizuj moc w każdym
        aby zminimalizować koszt przy zachowaniu ograniczeń.

        Returns:
            ScheduleResult lub None jeśli LP nie poprawia wyniku.
        """
        if not greedy_allocated:
            return None

        selected_indices = [a["index"] for a in greedy_allocated]
        m = len(selected_indices)

        # Zmienne decyzyjne: power[i] dla każdego wybranego slotu
        # Cel: minimize Σ(cost[i] * power[i] * duration[i])
        c_vec = np.array([
            float(costs[idx]) * time_slots[idx].duration_hours
            for idx in selected_indices
        ])

        # Ograniczenia:
        # 1. Σ(power[i] * duration[i]) >= required_energy
        #    → -Σ(power[i] * duration[i]) <= -required_energy
        durations = np.array([
            time_slots[idx].duration_hours for idx in selected_indices
        ])

        A_ub = [-durations]
        b_ub = [-required_energy]

        # Bounds: power_min <= power[i] <= min(power_max, available_power[i])
        bounds = [
            (power_min, min(power_max, available_power[idx]))
            for idx in selected_indices
        ]

        try:
            result = linprog(
                c=c_vec,
                A_ub=A_ub,
                b_ub=b_ub,
                bounds=bounds,
                method="highs",
            )

            if result.success:
                allocated = []
                for i, idx in enumerate(selected_indices):
                    power = result.x[i]
                    if power > 1e-6:
                        allocated.append({
                            "index": idx,
                            "power": power,
                            "energy": power * time_slots[idx].duration_hours,
                            "duration": time_slots[idx].duration_hours,
                        })

                if allocated:
                    return self._build_result(
                        time_slots, costs, allocated, is_feasible=True
                    )
        except Exception:
            pass

        return None

    def _build_result(
        self,
        time_slots: list[TimeSlot],
        costs: list[Decimal],
        allocated: list[dict],
        is_feasible: bool,
    ) -> ScheduleResult:
        """Zbuduj ScheduleResult z listy alokacji."""
        windows = []
        total_cost = Decimal("0.00")
        total_energy = 0.0

        for alloc in allocated:
            idx = alloc["index"]
            power = alloc["power"]
            energy = alloc["energy"]

            if power > 1e-6:
                windows.append(ScheduleWindow(
                    slot=time_slots[idx],
                    power_kw=round(power, 4),
                ))
                slot_cost = costs[idx] * Decimal(str(round(energy, 6)))
                total_cost += slot_cost
                total_energy += energy

        total_cost = total_cost.quantize(Decimal("0.01"))

        return ScheduleResult(
            windows=windows,
            total_cost=total_cost,
            total_energy=round(total_energy, 4),
            is_feasible=is_feasible,
        )
