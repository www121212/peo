"""Stałe dla integracji Polish Energy Optimizer (PEO)."""

from typing import Final

# Domain integracji
DOMAIN: Final = "peo"

# Platformy encji
PLATFORMS: Final = ["sensor", "binary_sensor"]

# Domyślne interwały aktualizacji (w minutach)
DEFAULT_PRICE_UPDATE_INTERVAL: Final = 60
DEFAULT_TARIFF_UPDATE_INTERVAL: Final = 15
DEFAULT_PV_FORECAST_UPDATE_INTERVAL: Final = 60

# Interwały heartbeat i failsafe (w sekundach)
HEARTBEAT_INTERVAL: Final = 60
FAILSAFE_TIMEOUT: Final = 300  # 5 minut

# Limity API
MAX_REQUESTS_PER_HOUR: Final = 60
HTTP_TIMEOUT: Final = 30  # sekundy

# Walidacja cen
PRICE_MIN_PLN_MWH: Final = 0
PRICE_MAX_PLN_MWH: Final = 5000
HOURS_PER_DAY: Final = 24

# Walidacja danych wejściowych
SOC_MIN: Final = 0
SOC_MAX: Final = 100
POWER_MIN_KW: Final = 0.0
POWER_MAX_KW: Final = 100.0
RATE_MIN_PLN_KWH: Final = 0.0
RATE_MAX_PLN_KWH: Final = 5.0

# Retencja danych
PRICE_HISTORY_DAYS: Final = 30
MAX_CHARGING_SESSIONS: Final = 1000

# Konfiguracja EV
MAX_VEHICLE_CHARGER_PAIRS: Final = 4
DEFAULT_MIN_CHARGING_POWER_KW: Final = 1.4
CHARGER_RETRY_COUNT: Final = 3
CHARGER_RETRY_INTERVAL: Final = 10  # sekundy
SOC_CHECK_INTERVAL: Final = 60  # sekundy
CHARGER_COMM_TIMEOUT: Final = 60  # sekundy

# Konfiguracja odbiorników (Load Manager)
MAX_LOADS: Final = 16
LOAD_COMMAND_TIMEOUT: Final = 60  # sekundy
LOAD_RETRY_COUNT: Final = 3
LOAD_RETRY_INTERVAL: Final = 30  # sekundy

# Konfiguracja PV
DEFAULT_MIN_SOC_PERCENT: Final = 10
MIN_SOC_RANGE: Final = (5, 30)
PV_FORECAST_STALE_MINUTES: Final = 180

# Klucze konfiguracji (ConfigEntry.data)
CONF_MODULES_ENABLED: Final = "modules_enabled"
CONF_TARIFF_TYPE: Final = "tariff_type"
CONF_OSD_OPERATOR: Final = "osd_operator"
CONF_SOLAR_PROVIDER: Final = "solar_provider"
CONF_SOLAR_API_KEY: Final = "solar_api_key"
CONF_CHARGERS: Final = "chargers"

# Klucze opcji (ConfigEntry.options)
CONF_TARIFF_RATES: Final = "tariff_rates"
CONF_EV_VEHICLES: Final = "ev_vehicles"
CONF_LOADS: Final = "loads"
CONF_GRID_LIMIT_KW: Final = "grid_limit_kw"
CONF_PV: Final = "pv"
CONF_PRICE_THRESHOLD_CHEAP: Final = "price_threshold_cheap"
CONF_UPDATE_INTERVALS: Final = "update_intervals"

# Moduły
MODULE_PRICES: Final = "prices"
MODULE_TARIFF: Final = "tariff"
MODULE_EV: Final = "ev"
MODULE_LOADS: Final = "loads"
MODULE_PV: Final = "pv"
MODULE_ANALYZER: Final = "analyzer"

# Zdarzenia (Events)
EVENT_PRICES_UPDATED: Final = "peo_prices_updated"
EVENT_SCHEDULE_UPDATED: Final = "peo_schedule_updated"
EVENT_CHARGING_STARTED: Final = "peo_charging_started"
EVENT_CHARGING_COMPLETED: Final = "peo_charging_completed"
EVENT_LOAD_SHIFTED: Final = "peo_load_shifted"
EVENT_PRICE_THRESHOLD_CROSSED: Final = "peo_price_threshold_crossed"

# Usługi (Services)
SERVICE_START_EV_CHARGING: Final = "start_ev_charging"
SERVICE_STOP_EV_CHARGING: Final = "stop_ev_charging"
SERVICE_SET_LOAD_THRESHOLD: Final = "set_load_threshold"
SERVICE_FORCE_LOAD_ON: Final = "force_load_on"
SERVICE_FORCE_LOAD_OFF: Final = "force_load_off"
SERVICE_RECALCULATE_SCHEDULE: Final = "recalculate_schedule"
