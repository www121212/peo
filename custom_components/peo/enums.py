"""Enumeracje dla Polish Energy Optimizer (PEO)."""

from enum import StrEnum


class TariffType(StrEnum):
    """Typy taryf energetycznych obsługiwanych przez PEO."""

    G11 = "G11"
    G12 = "G12"
    G12W = "G12w"
    G12R = "G12r"
    G13 = "G13"
    C11 = "C11"
    C12A = "C12a"
    C12B = "C12b"
    C21 = "C21"
    C22A = "C22a"
    C22B = "C22b"
    C23 = "C23"


class OSDOperator(StrEnum):
    """Operatorzy Systemu Dystrybucyjnego (OSD) w Polsce."""

    TAURON = "tauron"
    PGE = "pge"
    ENEA = "enea"
    ENERGA = "energa"
    INNOGY_STOEN = "innogy_stoen"


class TimeZoneName(StrEnum):
    """Nazwy stref czasowych taryf wielostrefowych."""

    SZCZYT = "szczyt"
    SZCZYT_PORANNY = "szczyt_poranny"
    SZCZYT_POPOLUDNIOWY = "szczyt_popołudniowy"
    POZASZCZYT = "pozaszczyt"
    NOC = "noc"
    WEEKEND = "weekend"
    SINGLE = "jednolita"


class BatteryMode(StrEnum):
    """Tryby pracy baterii magazynu energii."""

    CHARGE = "ładowanie"
    DISCHARGE = "rozładowanie"
    STANDBY = "oczekiwanie"


class ChargingStrategy(StrEnum):
    """Strategie ładowania pojazdów elektrycznych."""

    CHEAPEST = "najtańsze_okna"
    READY_BY = "gotowy_do_godziny"
    PV_ONLY = "tylko_nadwyżka_PV"


class LoadStatus(StrEnum):
    """Statusy odbiorników odraczalnych."""

    ON = "włączony"
    OFF = "wyłączony"
    BLOCKED = "zablokowany"
    MANUAL = "ręczny"


class PriceDataStatus(StrEnum):
    """Statusy danych cenowych z RCE PSE."""

    OK = "ok"
    WAITING = "oczekiwanie"
    STALE = "dane_nieaktualne"
    NO_DATA = "brak_danych"


class SolarProvider(StrEnum):
    """Dostawcy prognoz solarnych."""

    SOLCAST = "solcast"
    FORECAST_SOLAR = "forecast_solar"
    OPENWEATHERMAP = "openweathermap"
