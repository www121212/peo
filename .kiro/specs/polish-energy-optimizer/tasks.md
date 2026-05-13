# Implementation Plan: Polish Energy Optimizer (PEO)

## Overview

This implementation plan breaks down the PEO Home Assistant integration into incremental coding tasks. The architecture follows a modular approach with independent DataUpdateCoordinators, event-driven communication, and an LP solver for optimization. Implementation proceeds from foundational infrastructure (project structure, data models, tariff definitions) through core modules (prices, tariffs, EV scheduling, load shifting, PV optimization, tariff analysis) to integration wiring (Config Flow, services, events, sensors).

## Tasks

- [ ] 1. Set up project structure, data models, and core infrastructure
  - [x] 1.1 Create directory structure and manifest files
    - Create `custom_components/peo/` directory structure with `__init__.py`, `manifest.json`, `hacs.json`
    - Create `data/tariffs/`, `data/osd/`, `data/defaults/` subdirectories
    - Set up `manifest.json` with domain, name, version (semver), documentation, issue_tracker, dependencies, codeowners, iot_class, homeassistant fields
    - Set up `hacs.json` with name, homeassistant, render_readme fields
    - Create `const.py` with DOMAIN, PLATFORMS, default intervals, and configuration keys
    - _Requirements: 8.6_

  - [x] 1.2 Define enumerations and data models
    - Implement all enumerations: `TariffType`, `OSDOperator`, `TimeZoneName`, `BatteryMode`, `ChargingStrategy`, `LoadStatus`, `PriceDataStatus`, `SolarProvider`
    - Implement all frozen dataclasses: `HourlyPrice`, `PriceData`, `PriceStats`, `TariffRates`, `TariffDefinition`, `HourlyCost`, `VehicleConfig`, `ChargerConfig`, `VehicleChargerPair`, `ChargingSchedule`, `TimeWindow`, `ChargingSession`, `LoadConfig`, `LoadDecision`, `BatteryConfig`, `BatteryStrategy`, `HourlyPVForecast`, `TariffComparison`, `TariffRanking`, `OptimizationDecision`, `ChargingConstraints`
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 11.1_

  - [x] 1.3 Implement InputValidator utility class
    - Implement `validate_price(value) -> Decimal` (range 0–5000 PLN/MWh)
    - Implement `validate_soc(value) -> int` (range 0–100)
    - Implement `validate_power(value) -> float` (range 0–100 kW)
    - Implement `validate_rate(value) -> Decimal` (range 0–5 PLN/kWh)
    - Raise appropriate validation errors with Polish-language messages
    - _Requirements: 9.1, 7.3_

  - [x] 1.4 Implement RateLimiter class
    - Implement `acquire(endpoint: str) -> bool` — track requests per endpoint per hour
    - Implement `get_remaining(endpoint: str) -> int`
    - Enforce 60 requests/hour per endpoint limit
    - Log WARNING when limit is reached
    - _Requirements: 9.8_

  - [x] 1.5 Write property test for rate limiting (Property 23)
    - **Property 23: Rate limiting — 60 żądań/h per endpoint**
    - **Validates: Requirements 9.8**

  - [x] 1.6 Implement HeartbeatMonitor with failsafe mechanism
    - Implement `pulse()` — update heartbeat timestamp
    - Implement `check_failsafe()` — detect 5-minute timeout
    - Implement `activate_failsafe()` — switch devices to configured default states and notify user
    - Heartbeat interval: 60s, failsafe timeout: 5min
    - _Requirements: 9.5_

  - [x] 1.7 Create tariff definition JSON files
    - Create JSON files for all tariffs: G11, G12, G12w, G12r, G13, C11, C12a, C12b, C21, C22a, C22b, C23
    - Create OSD zone definition files: tauron.json, pge.json, enea.json, energa.json, innogy_stoen.json
    - Create default rates file (rates_2024.json) with URE-approved rates
    - _Requirements: 2.1, 2.2, 2.8_

- [ ] 2. Implement Moduł_Cen (Price Module)
  - [x] 2.1 Implement RCEApiClient
    - Implement `fetch_prices(date) -> list[HourlyPrice]` with 30s HTTP timeout
    - Handle HTTP error codes (4xx, 5xx) gracefully
    - Use `aiohttp` with proper session management
    - Integrate RateLimiter for API calls
    - _Requirements: 1.1, 1.5, 9.8_

  - [x] 2.2 Implement PriceValidator
    - Validate exactly 24 hourly values
    - Validate all values in range 0–5000 PLN/MWh
    - Validate required fields and data types
    - Reject entire dataset on any validation failure
    - _Requirements: 1.8, 9.1, 9.2_

  - [x] 2.3 Write property tests for price validation (Properties 1, 2)
    - **Property 1: Parsowanie i statystyki cen RCE**
    - **Property 2: Walidacja danych wejściowych odrzuca nieprawidłowe dane**
    - **Validates: Requirements 1.2, 1.3, 1.8, 9.1, 9.2**

  - [x] 2.4 Implement PriceHistoryStore
    - Implement `store(date, prices)` — persist daily prices
    - Implement `get_history(days=30)` — retrieve last N days
    - Implement `cleanup_old()` — remove entries older than 30 days
    - Use Home Assistant `Store` helper for persistent storage
    - _Requirements: 1.6_

  - [x] 2.5 Write property test for price history retention (Property 3)
    - **Property 3: Retencja historii cen — 30 dni**
    - **Validates: Requirements 1.6**

  - [x] 2.6 Implement PriceDataCoordinator
    - Extend `DataUpdateCoordinator` with 60-minute update interval
    - Implement `_async_update_data()` — fetch, validate, store, fire event
    - Handle "oczekiwanie" status after 13:30 when tomorrow prices unavailable (retry every 15 min)
    - Handle "dane_nieaktualne" status on fetch failure, "brak_danych" after 24h without success
    - Fire `peo_prices_updated` event on successful fetch with date and source attributes
    - Expose sensors: current price, min/max/avg daily price, 24 hourly prices as attribute
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7_

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement Kalkulator_Taryf (Tariff Calculator)
  - [x] 4.1 Implement TariffDefinitionLoader
    - Implement `load_tariff(tariff_type) -> TariffDefinition` — load from JSON
    - Implement `load_osd_zones(operator) -> OSDZoneDefinition` — load OSD-specific zone hours
    - Implement `load_default_rates(operator, tariff) -> TariffRates` — load URE defaults
    - _Requirements: 2.1, 2.2, 2.8_

  - [x] 4.2 Implement TariffCalculator core logic
    - Implement `get_zone_for_time(timestamp, tariff, operator) -> TimeZoneName` — determine active zone
    - Implement `calculate_cost(timestamp, tariff, operator, rates, rce_price) -> Decimal` — full cost with 4 decimal places
    - Cost formula: energy + distribution_variable + transition_fee + oze_fee + capacity_fee + cogeneration_fee
    - Apply zone-specific distribution rates per OSD operator
    - Implement `get_hourly_costs(start, hours=24) -> list[HourlyCost]`
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x] 4.3 Write property tests for tariff calculation (Properties 4, 5)
    - **Property 4: Obliczanie kosztu kWh dla taryf**
    - **Property 5: Walidacja konfiguracji taryfa/OSD**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.9**

  - [x] 4.4 Implement TariffDataCoordinator
    - Extend `DataUpdateCoordinator` with 15-minute update interval
    - Expose sensor: current cost (PLN/kWh, 4 decimal places) with zone name attribute
    - Update sensor within 10 seconds of zone change
    - Support user-configurable rates via ConfigEntry.options (no reinstall required)
    - _Requirements: 2.5, 2.6, 2.7_

- [ ] 5. Implement Harmonogramownik_EV (EV Scheduler)
  - [x] 5.1 Implement ScheduleEngine (LP Solver)
    - Implement `solve_minimum_cost_schedule()` — minimize Σ(cost×power×duration) subject to constraints
    - Constraints: required energy, charger max power, grid limit, min charging power (or 0), time windows
    - Support discontinuous charging windows
    - Implement `solve_multi_priority_schedule()` — multi-vehicle with priority allocation
    - Use `scipy.optimize.linprog` or `PuLP` for LP solving
    - _Requirements: 3.1, 3.5, 3.10, 11.2_

  - [x] 5.2 Write property tests for EV scheduling (Properties 6, 7, 9, 10)
    - **Property 6: Optymalne okno ładowania EV minimalizuje koszt**
    - **Property 7: Ładowanie nieciągłe vs ciągłe — wybór tańszego**
    - **Property 9: Nieprzekraczanie mocy przyłączeniowej (EV)**
    - **Property 10: Wykrywanie nieosiągalności docelowego SoC**
    - **Validates: Requirements 3.1, 3.5, 3.10, 3.13**

  - [x] 5.3 Implement ChargerAdapter abstract class and concrete adapters
    - Implement abstract `ChargerAdapter` with: `start_charging`, `stop_charging`, `get_status`, `get_limits`
    - Implement `OCPPChargerAdapter` (OCPP 1.6/2.0)
    - Implement `TeslaChargerAdapter` (Tesla Wall Connector API)
    - Implement `WallboxChargerAdapter` (Wallbox Pulsar API)
    - Implement `OpenEVSEChargerAdapter` (OpenEVSE API)
    - Retry logic: 3 retries with 10s intervals on command failure
    - _Requirements: 3.2, 3.6, 9.3_

  - [x] 5.4 Write property test for charger power limits (Property 22)
    - **Property 22: Respektowanie limitów mocy ładowarki**
    - **Validates: Requirements 9.3**

  - [x] 5.5 Implement EVScheduler and ChargingSessionManager
    - Implement `calculate_schedule()` — single vehicle optimal schedule
    - Implement `calculate_multi_vehicle_schedule()` — multi-vehicle with priorities
    - Implement `ChargingSessionManager`: start/stop sessions, monitor SoC (every 60s), handle manual charging
    - Implement stop condition: SoC >= target OR window ended
    - Handle SoC entity unavailable >5min: pause automation, notify user
    - Implement PV surplus notification when forecast shows excess production
    - Recalculate schedule on `peo_prices_updated` event
    - Support 3 strategies per vehicle: "najtańsze_okna", "gotowy_do_godziny", "tylko_nadwyżka_PV"
    - _Requirements: 3.1, 3.3, 3.4, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 11.1, 11.2, 11.3, 11.4_

  - [x] 5.6 Write property tests for charging stop condition and multi-vehicle (Properties 8, 28, 29)
    - **Property 8: Warunek zatrzymania ładowania**
    - **Property 28: Przydział mocy wielu pojazdom wg priorytetów**
    - **Property 29: Strategia ładowania per pojazd**
    - **Validates: Requirements 3.4, 11.2, 11.3, 11.4, 11.7**

  - [x] 5.7 Implement EV safety features
    - Respect charger power limits (max current A, max power kW) — never exceed
    - Pause charging when battery temperature exceeds safety threshold
    - Resume when temperature drops below threshold
    - Continue charging without temperature check if charger doesn't provide temperature data
    - Handle communication loss (60s timeout): notify user, mark session "wymagająca weryfikacji"
    - _Requirements: 9.3, 9.4, 9.6, 9.9_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement Menedżer_Obciążeń (Load Manager)
  - [x] 7.1 Implement LoadManager core logic
    - Implement `evaluate_loads(current_cost)` — compare cost against thresholds, decide on/off
    - Implement `ensure_minimum_runtime(load, remaining_hours)` — select cheapest remaining hours
    - Implement `check_power_budget(loads_to_activate, current_building_load)` — filter by priority and grid limit
    - Support 1–16 configurable loads with all parameters (entity, thresholds, min/max hours, time window, priority, power)
    - Send on/off commands within 30s of price change detection
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6_

  - [x] 7.2 Write property tests for load management (Properties 11, 12, 13, 14)
    - **Property 11: Przełączanie odbiorników wg progów cenowych**
    - **Property 12: Zapewnienie minimalnej dziennej pracy odbiornika**
    - **Property 13: Blokada po osiągnięciu maksymalnej dziennej pracy**
    - **Property 14: Priorytetyzacja mocy — odbiorniki**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6**

  - [x] 7.3 Implement LoadStateTracker
    - Track on/off events per load with timestamps
    - Calculate daily runtime with 0.1h resolution
    - Block loads after max daily hours reached (until 00:00 next day)
    - Detect manual override: pause automation until manual off or end of allowed window
    - Retry command 3x (30s intervals) if load doesn't confirm state change within 60s
    - Expose sensor per load: planned windows, realized runtime, remaining required runtime, status
    - _Requirements: 4.5, 4.7, 4.8, 4.9_

- [ ] 8. Implement Optymalizator_PV (PV Optimizer)
  - [x] 8.1 Implement SolarForecastClient
    - Implement multi-provider support: Solcast, Forecast.Solar, OpenWeatherMap Solar
    - Fetch 24h PV forecast every 60 minutes
    - Handle provider unavailability >180min: fallback to last forecast, status "prognoza nieaktualna", notify user
    - Integrate RateLimiter
    - _Requirements: 5.1, 5.9_

  - [x] 8.2 Implement PVOptimizer core logic
    - Implement `calculate_surplus_profile(pv_forecast, avg_consumption)` — production minus 7-day average hourly consumption
    - Implement `determine_battery_mode(grid_price, degradation_cost, pv_available, current_soc, min_soc)` — charge/discharge/standby
    - Implement `calculate_battery_strategy(pv_forecast, costs, battery, consumption_profile)` — 24h strategy
    - Calculate target SoC at end of cheap zone to minimize 24h cost
    - Limit night charging when PV forecast exceeds daily consumption (leave capacity for PV surplus)
    - Enforce minimum safety SoC (default 10%, configurable 5–30%) — switch to standby at threshold
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 5.10_

  - [x] 8.3 Write property tests for PV optimization (Properties 15, 16, 17, 18)
    - **Property 15: Obliczanie profilu nadwyżki PV**
    - **Property 16: Decyzja o trybie baterii**
    - **Property 17: Ograniczenie nocnego ładowania przy dużej prognozie PV**
    - **Property 18: Bezpieczeństwo minimalnego SoC baterii**
    - **Validates: Requirements 5.2, 5.3, 5.4, 5.6, 5.10**

  - [x] 8.4 Implement PVForecastCoordinator and inverter communication
    - Extend `DataUpdateCoordinator` with 60-minute interval
    - Expose sensors: forecast PV production (today/tomorrow kWh), forecast autoconsumption (today kWh), recommended battery mode, estimated daily savings (PLN)
    - Support inverter communication via HA integrations: SolarEdge, Huawei Solar, GoodWe, Fronius, SMA
    - _Requirements: 5.7, 5.8_

- [ ] 9. Implement Analizator_Taryf (Tariff Analyzer)
  - [x] 9.1 Implement TariffAnalyzer
    - Implement `analyze_tariffs(consumption_profile, current_tariff, operator)` — compare costs for G11, G12, G12w, G12r, G13
    - Implement `calculate_hypothetical_cost(hourly_consumption, tariff, operator, rates)` — full cost per tariff
    - Include all cost components: energy + distribution + transition + OZE + capacity + cogeneration
    - Rank tariffs from cheapest to most expensive with PLN difference vs current
    - Run analysis daily at 01:00 local time based on last 30 days
    - Mark results as "niewystarczające dane" if <7 days of data
    - _Requirements: 6.1, 6.2, 6.3, 6.5, 6.6, 6.7_

  - [x] 9.2 Write property test for tariff comparison (Property 19)
    - **Property 19: Porównanie taryf — poprawność obliczeń i rankingu**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.6**

  - [x] 9.3 Implement tariff recommendation notifications
    - Expose sensor: recommended tariff with estimated monthly savings (PLN)
    - Generate notification when difference >10% of monthly cost (max once per 7 days)
    - _Requirements: 6.3, 6.4_

- [ ] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement monitoring and savings tracking
  - [x] 11.1 Implement savings calculation sensors
    - Daily savings sensor (PLN, 2 decimal places): difference between non-optimized and actual cost, reset at 00:00
    - Monthly cumulative savings sensor (PLN, 2 decimal places): reset on 1st of each month at 00:00
    - Update after each optimization decision
    - Mark as "unknown" when baseline price data unavailable
    - _Requirements: 10.1, 10.2, 10.7_

  - [x] 11.2 Write property test for savings calculation (Property 24)
    - **Property 24: Obliczanie oszczędności**
    - **Validates: Requirements 10.1, 10.2**

  - [x] 11.3 Implement ChargingSession logging
    - Record completed sessions: duration (min), energy (kWh, 2dp), actual cost (PLN, 2dp), hypothetical cost (PLN, 2dp)
    - Store max 1000 sessions in persistent storage
    - _Requirements: 10.3_

  - [x] 11.4 Write property test for session logging (Property 25)
    - **Property 25: Rejestracja sesji ładowania EV**
    - **Validates: Requirements 10.3**

  - [x] 11.5 Implement load runtime tracking sensor
    - Sensor per load: daily hours worked (0.1h resolution), reset at 00:00
    - _Requirements: 10.4_

  - [x] 11.6 Write property test for runtime tracking (Property 26)
    - **Property 26: Śledzenie czasu pracy odbiorników**
    - **Validates: Requirements 10.4**

  - [x] 11.7 Implement optimization decision log
    - Diagnostic attribute with last 10 decisions: timestamp (ISO 8601), decision, reason, savings (PLN, 2dp)
    - Generate notification when monthly savings exceed 50 PLN (max once per calendar month)
    - _Requirements: 10.5, 10.6, 10.8_

  - [x] 11.8 Write property test for decision log (Property 27)
    - **Property 27: Bufor ostatnich 10 decyzji optymalizacyjnych**
    - **Validates: Requirements 10.5**

- [ ] 12. Implement Config Flow and Options Flow
  - [x] 12.1 Implement PEOConfigFlow (multi-step)
    - Step 1: Module selection (at least one required)
    - Step 2: Tariff configuration (OSD operator, tariff type, rates)
    - Step 3: EV configuration (optional — vehicles, chargers)
    - Step 4: Load configuration (optional — up to 10 deferrable loads)
    - Step 5: PV configuration (optional — solar provider, battery)
    - All labels, descriptions, error messages in Polish
    - Auto-load available tariffs and default rates when OSD selected (within 3s)
    - Quick setup mode with defaults (G12 + EV + bojler CWU)
    - Preserve partial configuration on interruption until HA restart
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.7, 7.8, 7.9_

  - [x] 12.2 Write property test for Config Flow validation (Property 20)
    - **Property 20: Walidacja danych wejściowych Config Flow**
    - **Validates: Requirements 7.3**

  - [x] 12.3 Implement PEOOptionsFlow
    - Allow independent reconfiguration of each module (EV, tariff, PV, loads)
    - Add/remove deferrable loads without full reconfiguration
    - Update ConfigEntry.options without requiring integration reload
    - _Requirements: 7.5, 7.6, 8.9_

  - [x] 12.4 Implement translations (strings.json)
    - Create `translations/pl.json` with all Config Flow steps, labels, descriptions, error messages in Polish
    - _Requirements: 7.2_

- [ ] 13. Implement integration lifecycle and HA ecosystem integration
  - [ ] 13.1 Implement async_setup_entry, async_unload_entry, async_remove_entry
    - `async_setup_entry`: register coordinators, platforms, event listeners (must complete within 30s)
    - `async_unload_entry`: cancel listeners, close HTTP sessions, remove coordinator references (within 10s)
    - `async_remove_entry`: remove persistent data
    - Register entities via ConfigEntry and EntityPlatform with unique_id, device_info, correct platform
    - Delegate I/O operations >100ms to executor via `hass.async_add_executor_job`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.12_

  - [ ] 13.2 Implement async_migrate_entry for config migration
    - Implement VERSION tracking with increment on schema changes
    - Preserve all user configuration values during migration
    - Verify schema compatibility on load after HACS update
    - _Requirements: 8.10, 8.11_

  - [ ] 13.3 Write property test for config migration (Property 21)
    - **Property 21: Migracja konfiguracji zachowuje dane**
    - **Validates: Requirements 8.10**

  - [ ] 13.4 Implement HA services registration
    - Register services: `peo.start_ev_charging`, `peo.stop_ev_charging`, `peo.set_load_threshold`, `peo.force_load_on`, `peo.force_load_off`, `peo.recalculate_schedule`
    - Define and validate parameter schemas for each service
    - `recalculate_schedule`: recalculate all modules within 30s, fire `peo_schedule_updated`
    - Return `ServiceValidationError` on invalid params without state change
    - _Requirements: 12.1, 12.3, 12.4_

  - [ ] 13.5 Write property tests for services and events (Properties 30, 31)
    - **Property 30: Zdarzenia HA zawierają wymagane pola**
    - **Property 31: Walidacja parametrów usług HA**
    - **Validates: Requirements 12.2, 12.4**

  - [ ] 13.6 Implement HA events and binary sensors
    - Fire events: `peo_charging_started`, `peo_charging_completed`, `peo_load_shifted`, `peo_price_threshold_crossed`, `peo_schedule_updated` — each with timestamp, entity_id, context data
    - Binary sensors: cheap window (ON when price < threshold), EV charging active, PV surplus active
    - Sensors with attributes: hourly_prices (24h), schedule (JSON), last_updated
    - _Requirements: 12.2, 12.5, 12.6_

  - [ ] 13.7 Write property test for binary sensor (Property 32)
    - **Property 32: Binary sensor "tanie okno"**
    - **Validates: Requirements 12.5**

- [ ] 14. Implement logging, diagnostics, and credential security
  - [ ] 14.1 Implement structured logging across all modules
    - DEBUG: API communication details, calculation steps
    - INFO: state changes, completed operations
    - WARNING: stale data, retried operations, rate limits
    - ERROR: critical operation failures
    - _Requirements: 8.8_

  - [ ] 14.2 Implement credential encryption and storage
    - Use Home Assistant credentials mechanism for API tokens and passwords
    - Store connection data in ConfigEntry.data, runtime params in ConfigEntry.options
    - Ensure Python 3.12+ compatibility
    - _Requirements: 9.7, 8.5, 8.9_

  - [ ] 14.3 Implement multi-vehicle sensor exposure
    - Separate sensor set per vehicle-charger pair: charging status, planned windows, estimated cost, estimated completion time, allocated power
    - Notify user when charging is deferred due to power constraints
    - _Requirements: 11.5, 11.6_

- [ ] 15. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation uses Python 3.12+ with asyncio, aiohttp, and Hypothesis for PBT
- LP solver: scipy.optimize.linprog or PuLP
- All UI text in Polish (translations/pl.json)
- Persistent storage via Home Assistant Store helper
- Event-driven architecture: modules communicate via HA Event Bus

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "1.6", "1.7"] },
    { "id": 2, "tasks": ["1.5", "2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4"] },
    { "id": 4, "tasks": ["2.5", "2.6", "4.1"] },
    { "id": 5, "tasks": ["4.2"] },
    { "id": 6, "tasks": ["4.3", "4.4", "5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3"] },
    { "id": 8, "tasks": ["5.4", "5.5"] },
    { "id": 9, "tasks": ["5.6", "5.7", "7.1"] },
    { "id": 10, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 11, "tasks": ["8.2"] },
    { "id": 12, "tasks": ["8.3", "8.4", "9.1"] },
    { "id": 13, "tasks": ["9.2", "9.3", "11.1"] },
    { "id": 14, "tasks": ["11.2", "11.3", "11.5", "11.7"] },
    { "id": 15, "tasks": ["11.4", "11.6", "11.8", "12.1"] },
    { "id": 16, "tasks": ["12.2", "12.3", "12.4"] },
    { "id": 17, "tasks": ["13.1", "13.2"] },
    { "id": 18, "tasks": ["13.3", "13.4", "13.6"] },
    { "id": 19, "tasks": ["13.5", "13.7", "14.1", "14.2", "14.3"] }
  ]
}
```
