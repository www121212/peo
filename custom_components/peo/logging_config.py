"""Konfiguracja strukturalnego logowania dla PEO.

Zapewnia spójne logowanie we wszystkich modułach integracji:
- DEBUG: szczegóły komunikacji API, kroki obliczeń
- INFO: zmiany stanu, zakończone operacje
- WARNING: nieaktualne dane, ponowione operacje, limity rate
- ERROR: krytyczne awarie operacji

Requirements: 8.8
"""

from __future__ import annotations

import logging
from typing import Final

from .const import DOMAIN

# Module-specific logger names
LOGGER_PRICES: Final = f"{DOMAIN}.prices"
LOGGER_TARIFF: Final = f"{DOMAIN}.tariff"
LOGGER_EV: Final = f"{DOMAIN}.ev"
LOGGER_LOADS: Final = f"{DOMAIN}.loads"
LOGGER_PV: Final = f"{DOMAIN}.pv"
LOGGER_ANALYZER: Final = f"{DOMAIN}.analyzer"
LOGGER_SERVICES: Final = f"{DOMAIN}.services"
LOGGER_CONFIG: Final = f"{DOMAIN}.config"
LOGGER_HEARTBEAT: Final = f"{DOMAIN}.heartbeat"
LOGGER_API: Final = f"{DOMAIN}.api"


def get_module_logger(module_name: str) -> logging.Logger:
    """Pobierz logger dla modułu PEO.

    Tworzy logger z prefiksem domeny PEO, zapewniając spójne
    nazewnictwo i hierarchię loggerów.

    Args:
        module_name: Nazwa modułu (np. 'prices', 'ev', 'tariff').

    Returns:
        Skonfigurowany logger dla modułu.

    Example:
        >>> logger = get_module_logger("prices")
        >>> logger.info("Pobrano ceny na dziś")
    """
    return logging.getLogger(f"custom_components.{DOMAIN}.{module_name}")


def configure_peo_logging(debug: bool = False) -> None:
    """Konfiguracja logowania dla całej integracji PEO.

    Ustawia poziomy logowania dla poszczególnych modułów.
    W trybie debug wszystkie moduły logują na poziomie DEBUG.

    Args:
        debug: Czy włączyć tryb debug (domyślnie False).

    Log levels per category:
        - DEBUG: API communication details, calculation steps
        - INFO: state changes, completed operations
        - WARNING: stale data, retried operations, rate limits
        - ERROR: critical operation failures
    """
    root_logger = logging.getLogger(f"custom_components.{DOMAIN}")

    if debug:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.INFO)

    # API communication — DEBUG by default (verbose)
    logging.getLogger(f"custom_components.{DOMAIN}.api").setLevel(
        logging.DEBUG if debug else logging.INFO
    )


class PEOLoggerMixin:
    """Mixin dodający strukturalne logowanie do klas PEO.

    Zapewnia metody logowania z kontekstem modułu i operacji.
    Klasy dziedziczące powinny ustawić _log_module.

    Example:
        class MyCoordinator(PEOLoggerMixin):
            _log_module = "prices"

            def fetch(self):
                self.log_info("Pobieranie cen", date="2024-01-15")
    """

    _log_module: str = "unknown"

    @property
    def _logger(self) -> logging.Logger:
        """Logger dla bieżącego modułu."""
        return get_module_logger(self._log_module)

    def log_debug(self, message: str, **context) -> None:
        """Log DEBUG: szczegóły komunikacji API, kroki obliczeń.

        Args:
            message: Komunikat logu.
            **context: Dodatkowe dane kontekstowe.
        """
        if context:
            self._logger.debug("%s | %s", message, context)
        else:
            self._logger.debug(message)

    def log_info(self, message: str, **context) -> None:
        """Log INFO: zmiany stanu, zakończone operacje.

        Args:
            message: Komunikat logu.
            **context: Dodatkowe dane kontekstowe.
        """
        if context:
            self._logger.info("%s | %s", message, context)
        else:
            self._logger.info(message)

    def log_warning(self, message: str, **context) -> None:
        """Log WARNING: nieaktualne dane, ponowione operacje, limity rate.

        Args:
            message: Komunikat logu.
            **context: Dodatkowe dane kontekstowe.
        """
        if context:
            self._logger.warning("%s | %s", message, context)
        else:
            self._logger.warning(message)

    def log_error(self, message: str, **context) -> None:
        """Log ERROR: krytyczne awarie operacji.

        Args:
            message: Komunikat logu.
            **context: Dodatkowe dane kontekstowe.
        """
        if context:
            self._logger.error("%s | %s", message, context)
        else:
            self._logger.error(message)
