"""Optymalizator PV i baterii dla Polish Energy Optimizer (PEO).

Oblicza strategię pracy baterii na 24h, profil nadwyżki PV,
oraz tryb baterii na podstawie cen energii i prognoz produkcji.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from .const import DEFAULT_MIN_SOC_PERCENT, MIN_SOC_RANGE
from .enums import BatteryMode
from .models import (
    BatteryConfig,
    BatteryStrategy,
    HourlyCost,
    HourlyPVForecast,
    TimeWindow,
)

_LOGGER = logging.getLogger(__name__)

# Precision for savings calculations
_SAVINGS_PRECISION = Decimal("0.01")


class PVOptimizer:
    """Optymalizator fotowoltaiki i baterii.

    Oblicza strategię pracy baterii na 24h, profil nadwyżki PV,
    oraz tryb baterii na podstawie cen energii, prognoz produkcji
    i konfiguracji magazynu energii.
    """

    def calculate_surplus_profile(
        self,
        pv_forecast: list[HourlyPVForecast],
        avg_consumption: list[float],
    ) -> list[float]:
        """Oblicz profil nadwyżki (PV - średnie zużycie godzinowe).

        Dla każdej godziny: surplus = produkcja PV - średnie zużycie z 7 dni.
        Wartość dodatnia = nadwyżka, ujemna = deficyt.

        Args:
            pv_forecast: Prognoza produkcji PV (do 24 elementów).
            avg_consumption: Średnie godzinowe zużycie z 7 dni (24 wartości).

        Returns:
            Lista 24 wartości nadwyżki/deficytu (kWh).
        """
        # Build lookup of PV production by hour
        pv_by_hour: dict[int, float] = {}
        for forecast in pv_forecast:
            if forecast.hour in pv_by_hour:
                pv_by_hour[forecast.hour] += forecast.production_kwh
            else:
                pv_by_hour[forecast.hour] = forecast.production_kwh

        surplus_profile: list[float] = []
        for hour in range(24):
            production = pv_by_hour.get(hour, 0.0)
            consumption = avg_consumption[hour] if hour < len(avg_consumption) else 0.0
            surplus_profile.append(production - consumption)

        return surplus_profile

    def determine_battery_mode(
        self,
        grid_price: Decimal,
        degradation_cost: Decimal,
        pv_available: float,
        current_soc: float,
        min_soc: float,
    ) -> BatteryMode:
        """Określ tryb baterii: charge/discharge/standby.

        Logika decyzyjna:
        1. Jeśli current_soc <= min_soc → STANDBY (próg bezpieczeństwa)
        2. Jeśli grid_price < degradation_cost → CHARGE (tanie ładowanie z sieci)
        3. Jeśli grid_price > degradation_cost + wartość magazynowalnej PV → DISCHARGE
        4. W przeciwnym razie → STANDBY

        Args:
            grid_price: Bieżąca cena energii z sieci (PLN/kWh).
            degradation_cost: Koszt degradacji baterii (PLN/kWh).
            pv_available: Dostępna energia PV w bieżącej godzinie (kWh).
            current_soc: Bieżący poziom naładowania baterii (%).
            min_soc: Minimalny bezpieczny poziom SoC (%).

        Returns:
            BatteryMode: CHARGE, DISCHARGE lub STANDBY.
        """
        # Safety threshold: if at or below min SoC, go to standby
        if current_soc <= min_soc:
            return BatteryMode.STANDBY

        # Cheap grid price: charge from grid
        if grid_price < degradation_cost:
            return BatteryMode.CHARGE

        # Calculate value of storable PV energy
        # If PV is available, the value of storing it equals the grid price
        # (energy that would otherwise be exported or wasted)
        value_of_storable_pv = Decimal(str(pv_available)) * grid_price if pv_available > 0 else Decimal("0")

        # Expensive grid price: discharge if profitable
        # Discharge when grid price exceeds degradation cost + value of PV that could be stored
        # Simplified: if no PV available, discharge when grid_price > degradation_cost
        # If PV available, the threshold is higher (we'd rather store PV)
        discharge_threshold = degradation_cost + Decimal(str(pv_available)) * degradation_cost

        if grid_price > discharge_threshold:
            return BatteryMode.DISCHARGE

        return BatteryMode.STANDBY

    def calculate_battery_strategy(
        self,
        pv_forecast: list[HourlyPVForecast],
        costs: list[HourlyCost],
        battery: BatteryConfig,
        consumption_profile: list[float],
    ) -> BatteryStrategy:
        """Oblicz strategię baterii na 24h.

        Algorytm:
        1. Oblicz profil nadwyżki PV
        2. Zidentyfikuj tanie strefy (cena < degradation_cost)
        3. Oblicz docelowy SoC na koniec taniej strefy
        4. Ogranicz nocne ładowanie gdy PV > dzienne zużycie
        5. Wyznacz okna ładowania i rozładowania
        6. Oszacuj oszczędności

        Args:
            pv_forecast: Prognoza produkcji PV na 24h.
            costs: Koszty energii na 24h.
            battery: Konfiguracja baterii.
            consumption_profile: Średnie godzinowe zużycie (24 wartości).

        Returns:
            BatteryStrategy z trybem, docelowym SoC, oknami i oszczędnościami.
        """
        min_soc = float(battery.min_soc_percent)
        degradation_cost = battery.degradation_cost_pln_kwh

        # Validate min_soc is within allowed range
        min_soc_clamped = max(MIN_SOC_RANGE[0], min(MIN_SOC_RANGE[1], min_soc))

        # Step 1: Calculate surplus profile
        surplus_profile = self.calculate_surplus_profile(pv_forecast, consumption_profile)

        # Step 2: Calculate daily PV production and consumption
        total_pv_production = sum(
            f.production_kwh for f in pv_forecast
        )
        total_daily_consumption = sum(consumption_profile[:24])

        # Step 3: Identify cheap hours (grid price < degradation cost)
        cheap_hours: list[int] = []
        expensive_hours: list[int] = []
        cost_by_hour: dict[int, Decimal] = {}

        for cost in costs:
            cost_by_hour[cost.hour] = cost.cost_pln_kwh
            if cost.cost_pln_kwh < degradation_cost:
                cheap_hours.append(cost.hour)
            elif cost.cost_pln_kwh > degradation_cost:
                expensive_hours.append(cost.hour)

        # Step 4: Calculate target SoC at end of cheap zone
        target_soc = self._calculate_target_soc(
            cheap_hours=cheap_hours,
            expensive_hours=expensive_hours,
            surplus_profile=surplus_profile,
            battery=battery,
            cost_by_hour=cost_by_hour,
            total_pv_production=total_pv_production,
            total_daily_consumption=total_daily_consumption,
            min_soc=min_soc_clamped,
        )

        # Step 5: Determine charge and discharge windows
        charge_windows: list[TimeWindow] = []
        discharge_windows: list[TimeWindow] = []

        # Determine primary mode based on overall strategy
        primary_mode = BatteryMode.STANDBY

        for cost in costs:
            hour = cost.hour
            pv_available = surplus_profile[hour] if hour < len(surplus_profile) else 0.0

            mode = self.determine_battery_mode(
                grid_price=cost.cost_pln_kwh,
                degradation_cost=degradation_cost,
                pv_available=max(0.0, pv_available),
                current_soc=float(target_soc),  # Use target as reference
                min_soc=min_soc_clamped,
            )

            if mode == BatteryMode.CHARGE:
                charge_windows.append(
                    TimeWindow(
                        start=cost.timestamp,
                        end=cost.timestamp,  # 1-hour window
                        power_kw=battery.max_charge_power_kw,
                    )
                )
                if primary_mode == BatteryMode.STANDBY:
                    primary_mode = BatteryMode.CHARGE
            elif mode == BatteryMode.DISCHARGE:
                discharge_windows.append(
                    TimeWindow(
                        start=cost.timestamp,
                        end=cost.timestamp,  # 1-hour window
                        power_kw=battery.max_discharge_power_kw,
                    )
                )
                if primary_mode == BatteryMode.STANDBY:
                    primary_mode = BatteryMode.DISCHARGE

        # If we have both charge and discharge windows, primary mode is based on count
        if charge_windows and discharge_windows:
            if len(discharge_windows) >= len(charge_windows):
                primary_mode = BatteryMode.DISCHARGE
            else:
                primary_mode = BatteryMode.CHARGE

        # Step 6: Estimate savings
        estimated_savings = self._estimate_savings(
            charge_windows=charge_windows,
            discharge_windows=discharge_windows,
            cost_by_hour=cost_by_hour,
            degradation_cost=degradation_cost,
            battery=battery,
        )

        return BatteryStrategy(
            mode=primary_mode,
            target_soc=target_soc,
            charge_windows=charge_windows,
            discharge_windows=discharge_windows,
            estimated_savings_pln=estimated_savings,
        )

    def _calculate_target_soc(
        self,
        cheap_hours: list[int],
        expensive_hours: list[int],
        surplus_profile: list[float],
        battery: BatteryConfig,
        cost_by_hour: dict[int, Decimal],
        total_pv_production: float,
        total_daily_consumption: float,
        min_soc: float,
    ) -> int:
        """Oblicz docelowy SoC na koniec taniej strefy.

        Minimalizuje łączny koszt energii w horyzoncie 24h.
        Ogranicza nocne ładowanie gdy PV > dzienne zużycie.

        Args:
            cheap_hours: Godziny z tanim prądem.
            expensive_hours: Godziny z drogim prądem.
            surplus_profile: Profil nadwyżki PV.
            battery: Konfiguracja baterii.
            cost_by_hour: Koszt energii per godzina.
            total_pv_production: Łączna prognozowana produkcja PV (kWh).
            total_daily_consumption: Łączne dzienne zużycie (kWh).
            min_soc: Minimalny bezpieczny SoC (%).

        Returns:
            Docelowy SoC (%) w zakresie min_soc–100.
        """
        capacity_kwh = battery.capacity_kwh

        if not cheap_hours or not expensive_hours or capacity_kwh <= 0:
            return int(min_soc)

        # Calculate energy needed during expensive hours (deficit)
        expensive_deficit = 0.0
        for hour in expensive_hours:
            if hour < len(surplus_profile) and surplus_profile[hour] < 0:
                expensive_deficit += abs(surplus_profile[hour])

        # Energy that can be stored from PV surplus
        pv_surplus_total = sum(
            max(0.0, surplus_profile[h]) for h in range(24)
        )

        # Calculate how much capacity to reserve for PV surplus
        # Requirement 5.6: If PV forecast > daily consumption, limit night charging
        pv_exceeds_consumption = total_pv_production > total_daily_consumption

        if pv_exceeds_consumption:
            # Leave capacity for PV surplus (at least the surplus amount)
            reserved_for_pv_kwh = min(pv_surplus_total, capacity_kwh)
            max_charge_kwh = capacity_kwh - reserved_for_pv_kwh
            # Ensure we don't go below min_soc worth of energy
            min_energy_kwh = capacity_kwh * (min_soc / 100.0)
            max_charge_kwh = max(max_charge_kwh, min_energy_kwh)
            max_target_soc = min(100, int((max_charge_kwh / capacity_kwh) * 100))
        else:
            max_target_soc = 100

        # Target SoC: enough to cover expensive hour deficit, capped by max
        target_energy_kwh = min(expensive_deficit, capacity_kwh)
        target_soc_from_deficit = int((target_energy_kwh / capacity_kwh) * 100)

        # Clamp to valid range
        target_soc = max(int(min_soc), min(max_target_soc, target_soc_from_deficit))

        # Ensure at least min_soc
        target_soc = max(target_soc, int(min_soc))

        _LOGGER.debug(
            "Target SoC calculation: deficit=%.2f kWh, pv_surplus=%.2f kWh, "
            "pv_exceeds=%s, max_target=%d%%, result=%d%%",
            expensive_deficit,
            pv_surplus_total,
            pv_exceeds_consumption,
            max_target_soc,
            target_soc,
        )

        return target_soc

    def _estimate_savings(
        self,
        charge_windows: list[TimeWindow],
        discharge_windows: list[TimeWindow],
        cost_by_hour: dict[int, Decimal],
        degradation_cost: Decimal,
        battery: BatteryConfig,
    ) -> Decimal:
        """Oszacuj dzienne oszczędności ze strategii baterii.

        Oszczędność = (koszt_rozładowania - koszt_ładowania - degradacja) * energia.

        Args:
            charge_windows: Okna ładowania.
            discharge_windows: Okna rozładowania.
            cost_by_hour: Koszt energii per godzina.
            degradation_cost: Koszt degradacji baterii (PLN/kWh).
            battery: Konfiguracja baterii.

        Returns:
            Szacowane oszczędności (PLN, 2 miejsca po przecinku).
        """
        if not charge_windows or not discharge_windows:
            return Decimal("0.00")

        # Average charge cost
        charge_costs: list[Decimal] = []
        for window in charge_windows:
            hour = window.start.hour
            if hour in cost_by_hour:
                charge_costs.append(cost_by_hour[hour])

        # Average discharge value
        discharge_values: list[Decimal] = []
        for window in discharge_windows:
            hour = window.start.hour
            if hour in cost_by_hour:
                discharge_values.append(cost_by_hour[hour])

        if not charge_costs or not discharge_values:
            return Decimal("0.00")

        avg_charge_cost = sum(charge_costs) / len(charge_costs)
        avg_discharge_value = sum(discharge_values) / len(discharge_values)

        # Energy cycled (limited by battery capacity and number of hours)
        max_charge_energy = battery.max_charge_power_kw * len(charge_windows)
        max_discharge_energy = battery.max_discharge_power_kw * len(discharge_windows)
        usable_capacity = battery.capacity_kwh * (1 - battery.min_soc_percent / 100.0)
        energy_cycled = min(max_charge_energy, max_discharge_energy, usable_capacity)

        # Savings = (discharge_value - charge_cost - degradation) * energy
        savings_per_kwh = avg_discharge_value - avg_charge_cost - degradation_cost
        if savings_per_kwh <= 0:
            return Decimal("0.00")

        total_savings = savings_per_kwh * Decimal(str(energy_cycled))
        return total_savings.quantize(_SAVINGS_PRECISION, rounding=ROUND_HALF_UP)
