"""Menedżer Obciążeń (Load Manager) dla Polish Energy Optimizer (PEO).

Zarządza przesuwaniem obciążeń na podstawie progów cenowych,
priorytetów mocy i minimalnych/maksymalnych czasów pracy.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from .const import MAX_LOADS
from .models import HourlyCost, LoadConfig, LoadDecision, TimeWindow

_LOGGER = logging.getLogger(__name__)


class LoadManager:
    """Menedżer odbiorników odraczalnych.

    Odpowiada za:
    - Ocenę progów cenowych i podejmowanie decyzji on/off
    - Zapewnienie minimalnego czasu pracy w najtańszych godzinach
    - Kontrolę budżetu mocy z uwzględnieniem priorytetów
    """

    def __init__(self, grid_limit_kw: float = 12.0) -> None:
        """Inicjalizacja LoadManager.

        Args:
            grid_limit_kw: Limit mocy przyłączeniowej budynku w kW.
        """
        self._grid_limit_kw = grid_limit_kw

    def evaluate_loads(
        self,
        current_cost: Decimal,
        loads: list[LoadConfig],
        load_states: dict[str, dict],
        now: Optional[datetime] = None,
    ) -> list[LoadDecision]:
        """Oceń które odbiorniki włączyć/wyłączyć na podstawie bieżącego kosztu.

        Dla każdego odbiornika:
        - Jeśli current_cost < threshold_on → decyzja "on" (włącz)
        - Jeśli current_cost > threshold_off → decyzja "off" (wyłącz)
        - Jeśli pomiędzy progami → utrzymaj bieżący stan
        - Sprawdź okno czasowe (allowed_start do allowed_end)
        - Sprawdź czy nie przekroczono max_daily_hours

        Args:
            current_cost: Bieżący koszt energii w PLN/kWh.
            loads: Lista konfiguracji odbiorników (max 16).
            load_states: Słownik stanów odbiorników {load_id: {"is_on": bool,
                         "daily_runtime_hours": float, "manual_override": bool}}.
            now: Bieżący czas (opcjonalny, domyślnie datetime.now()).

        Returns:
            Lista decyzji LoadDecision dla każdego odbiornika.
        """
        if now is None:
            now = datetime.now()

        if len(loads) > MAX_LOADS:
            _LOGGER.warning(
                "Przekroczono maksymalną liczbę odbiorników (%d > %d), "
                "przetwarzam tylko pierwsze %d",
                len(loads),
                MAX_LOADS,
                MAX_LOADS,
            )
            loads = loads[:MAX_LOADS]

        decisions: list[LoadDecision] = []

        for load in loads:
            state = load_states.get(
                load.load_id,
                {"is_on": False, "daily_runtime_hours": 0.0, "manual_override": False},
            )

            decision = self._evaluate_single_load(current_cost, load, state, now)
            decisions.append(decision)

        return decisions

    def ensure_minimum_runtime(
        self,
        load: LoadConfig,
        remaining_costs: list[HourlyCost],
        current_runtime_hours: float,
    ) -> list[TimeWindow]:
        """Zaplanuj najtańsze godziny dla zapewnienia minimalnej pracy.

        Jeśli current_runtime < min_daily_hours, wybierz najtańsze
        pozostałe godziny w dozwolonym oknie czasowym.

        Args:
            load: Konfiguracja odbiornika.
            remaining_costs: Lista kosztów godzinowych na pozostałe godziny dnia.
            current_runtime_hours: Dotychczasowy czas pracy w bieżącym dniu (h).

        Returns:
            Lista zaplanowanych okien TimeWindow dla wymaganego czasu pracy.
        """
        remaining_needed = load.min_daily_hours - current_runtime_hours

        if remaining_needed <= 0:
            return []

        # Filtruj godziny w dozwolonym oknie czasowym
        eligible_hours = [
            cost
            for cost in remaining_costs
            if self._is_within_time_window(
                cost.timestamp, load.allowed_start, load.allowed_end
            )
        ]

        if not eligible_hours:
            _LOGGER.warning(
                "Brak dostępnych godzin w oknie czasowym dla odbiornika %s",
                load.load_id,
            )
            return []

        # Sortuj po koszcie (najtańsze najpierw)
        eligible_hours_sorted = sorted(eligible_hours, key=lambda c: c.cost_pln_kwh)

        # Wybierz najtańsze godziny pokrywające wymagany czas
        selected_windows: list[TimeWindow] = []
        hours_planned = 0.0

        for cost in eligible_hours_sorted:
            if hours_planned >= remaining_needed:
                break

            window = TimeWindow(
                start=cost.timestamp,
                end=cost.timestamp + timedelta(hours=1),
                power_kw=load.power_w / 1000.0,
            )
            selected_windows.append(window)
            hours_planned += 1.0

        # Sortuj okna chronologicznie
        selected_windows.sort(key=lambda w: w.start)

        return selected_windows

    def check_power_budget(
        self,
        loads_to_activate: list[LoadConfig],
        current_building_load_kw: float,
        grid_limit_kw: Optional[float] = None,
    ) -> list[LoadConfig]:
        """Filtruj odbiorniki wg budżetu mocy i priorytetów.

        Sortuje odbiorniki wg priorytetu (1 = najwyższy) i dodaje
        kolejno, dopóki nie zostanie przekroczony limit mocy.

        Args:
            loads_to_activate: Lista odbiorników do aktywacji.
            current_building_load_kw: Bieżące obciążenie budynku w kW.
            grid_limit_kw: Limit mocy przyłączeniowej (opcjonalny,
                          domyślnie z konfiguracji instancji).

        Returns:
            Podzbiór odbiorników możliwych do aktywacji w ramach budżetu mocy.
        """
        if grid_limit_kw is None:
            grid_limit_kw = self._grid_limit_kw

        available_power_kw = grid_limit_kw - current_building_load_kw

        if available_power_kw <= 0:
            _LOGGER.info(
                "Brak dostępnej mocy (budynek: %.2f kW, limit: %.2f kW)",
                current_building_load_kw,
                grid_limit_kw,
            )
            return []

        # Sortuj wg priorytetu (1 = najwyższy priorytet)
        sorted_loads = sorted(loads_to_activate, key=lambda l: l.priority)

        approved_loads: list[LoadConfig] = []
        used_power_kw = 0.0

        for load in sorted_loads:
            load_power_kw = load.power_w / 1000.0

            if used_power_kw + load_power_kw <= available_power_kw:
                approved_loads.append(load)
                used_power_kw += load_power_kw
            else:
                _LOGGER.debug(
                    "Odbiornik %s (priorytet %d, %.2f kW) pominięty — "
                    "przekroczenie budżetu mocy (użyto: %.2f kW, dostępne: %.2f kW)",
                    load.load_id,
                    load.priority,
                    load_power_kw,
                    used_power_kw,
                    available_power_kw,
                )

        return approved_loads

    def _evaluate_single_load(
        self,
        current_cost: Decimal,
        load: LoadConfig,
        state: dict,
        now: datetime,
    ) -> LoadDecision:
        """Oceń pojedynczy odbiornik i zwróć decyzję.

        Args:
            current_cost: Bieżący koszt energii PLN/kWh.
            load: Konfiguracja odbiornika.
            state: Bieżący stan odbiornika.
            now: Bieżący czas.

        Returns:
            LoadDecision z akcją i powodem.
        """
        # Sprawdź manual override
        if state.get("manual_override", False):
            return LoadDecision(
                load_id=load.load_id,
                action="manual_override",
                reason="Sterowanie ręczne — automatyka wstrzymana",
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )

        # Sprawdź okno czasowe
        if not self._is_within_time_window(now, load.allowed_start, load.allowed_end):
            return LoadDecision(
                load_id=load.load_id,
                action="off",
                reason="Poza dozwolonym oknem czasowym",
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )

        # Sprawdź max daily hours
        daily_runtime = state.get("daily_runtime_hours", 0.0)
        if daily_runtime >= load.max_daily_hours:
            return LoadDecision(
                load_id=load.load_id,
                action="blocked",
                reason=f"Osiągnięto maksymalny czas pracy ({load.max_daily_hours}h)",
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )

        # Porównaj koszt z progami
        if current_cost < load.threshold_on:
            return LoadDecision(
                load_id=load.load_id,
                action="on",
                reason=f"Koszt {current_cost} < próg włączenia {load.threshold_on}",
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )
        elif current_cost > load.threshold_off:
            return LoadDecision(
                load_id=load.load_id,
                action="off",
                reason=f"Koszt {current_cost} > próg wyłączenia {load.threshold_off}",
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )
        else:
            # Pomiędzy progami — utrzymaj bieżący stan
            current_action = "on" if state.get("is_on", False) else "off"
            return LoadDecision(
                load_id=load.load_id,
                action=current_action,
                reason=(
                    f"Koszt {current_cost} pomiędzy progami "
                    f"({load.threshold_on}–{load.threshold_off}) — "
                    f"utrzymanie stanu"
                ),
                timestamp=now,
                savings_pln=Decimal("0.00"),
            )

    @staticmethod
    def _is_within_time_window(
        timestamp: datetime, allowed_start: time, allowed_end: time
    ) -> bool:
        """Sprawdź czy czas mieści się w dozwolonym oknie.

        Obsługuje okna przechodzące przez północ (np. 22:00–06:00).

        Args:
            timestamp: Moment do sprawdzenia.
            allowed_start: Godzina rozpoczęcia okna.
            allowed_end: Godzina zakończenia okna.

        Returns:
            True jeśli timestamp jest w dozwolonym oknie.
        """
        current_time = timestamp.time()

        if allowed_start <= allowed_end:
            # Normalne okno (np. 06:00–22:00)
            return allowed_start <= current_time < allowed_end
        else:
            # Okno przechodzące przez północ (np. 22:00–06:00)
            return current_time >= allowed_start or current_time < allowed_end
