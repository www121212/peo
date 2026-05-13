"""Unit tests for logging_config module.

Tests structured logging configuration for PEO.
Requirements: 8.8
"""

import logging
import pytest

from custom_components.peo.logging_config import (
    get_module_logger,
    configure_peo_logging,
    PEOLoggerMixin,
    LOGGER_PRICES,
    LOGGER_TARIFF,
    LOGGER_EV,
    LOGGER_LOADS,
    LOGGER_PV,
    LOGGER_ANALYZER,
    LOGGER_SERVICES,
    LOGGER_CONFIG,
    LOGGER_HEARTBEAT,
    LOGGER_API,
)


class TestGetModuleLogger:
    """Tests for get_module_logger function."""

    def test_returns_logger_with_correct_name(self):
        """Logger name includes domain prefix and module name."""
        logger = get_module_logger("prices")
        assert logger.name == "custom_components.peo.prices"

    def test_returns_logger_for_ev_module(self):
        """Logger for EV module has correct name."""
        logger = get_module_logger("ev")
        assert logger.name == "custom_components.peo.ev"

    def test_returns_logger_instance(self):
        """Returns a logging.Logger instance."""
        logger = get_module_logger("tariff")
        assert isinstance(logger, logging.Logger)

    def test_same_module_returns_same_logger(self):
        """Same module name returns the same logger instance."""
        logger1 = get_module_logger("loads")
        logger2 = get_module_logger("loads")
        assert logger1 is logger2


class TestConfigurePeoLogging:
    """Tests for configure_peo_logging function."""

    def test_default_sets_info_level(self):
        """Default configuration sets INFO level on root PEO logger."""
        configure_peo_logging(debug=False)
        root = logging.getLogger("custom_components.peo")
        assert root.level == logging.INFO

    def test_debug_mode_sets_debug_level(self):
        """Debug mode sets DEBUG level on root PEO logger."""
        configure_peo_logging(debug=True)
        root = logging.getLogger("custom_components.peo")
        assert root.level == logging.DEBUG

    def test_api_logger_debug_in_debug_mode(self):
        """API logger is DEBUG in debug mode."""
        configure_peo_logging(debug=True)
        api_logger = logging.getLogger("custom_components.peo.api")
        assert api_logger.level == logging.DEBUG

    def test_api_logger_info_in_normal_mode(self):
        """API logger is INFO in normal mode."""
        configure_peo_logging(debug=False)
        api_logger = logging.getLogger("custom_components.peo.api")
        assert api_logger.level == logging.INFO


class TestPEOLoggerMixin:
    """Tests for PEOLoggerMixin class."""

    def test_log_debug_without_context(self, caplog):
        """log_debug logs at DEBUG level without context."""

        class TestClass(PEOLoggerMixin):
            _log_module = "test"

        obj = TestClass()
        with caplog.at_level(logging.DEBUG, logger="custom_components.peo.test"):
            obj.log_debug("Test debug message")
        assert "Test debug message" in caplog.text

    def test_log_info_without_context(self, caplog):
        """log_info logs at INFO level."""

        class TestClass(PEOLoggerMixin):
            _log_module = "test"

        obj = TestClass()
        with caplog.at_level(logging.INFO, logger="custom_components.peo.test"):
            obj.log_info("State changed")
        assert "State changed" in caplog.text

    def test_log_warning_without_context(self, caplog):
        """log_warning logs at WARNING level."""

        class TestClass(PEOLoggerMixin):
            _log_module = "test"

        obj = TestClass()
        with caplog.at_level(logging.WARNING, logger="custom_components.peo.test"):
            obj.log_warning("Data stale")
        assert "Data stale" in caplog.text

    def test_log_error_without_context(self, caplog):
        """log_error logs at ERROR level."""

        class TestClass(PEOLoggerMixin):
            _log_module = "test"

        obj = TestClass()
        with caplog.at_level(logging.ERROR, logger="custom_components.peo.test"):
            obj.log_error("Critical failure")
        assert "Critical failure" in caplog.text

    def test_log_info_with_context(self, caplog):
        """log_info includes context data in message."""

        class TestClass(PEOLoggerMixin):
            _log_module = "test"

        obj = TestClass()
        with caplog.at_level(logging.INFO, logger="custom_components.peo.test"):
            obj.log_info("Price updated", price=0.45, source="RCE")
        assert "Price updated" in caplog.text
        assert "price" in caplog.text


class TestLoggerConstants:
    """Tests for logger name constants."""

    def test_logger_names_follow_convention(self):
        """All logger names follow peo.module convention."""
        assert LOGGER_PRICES == "peo.prices"
        assert LOGGER_TARIFF == "peo.tariff"
        assert LOGGER_EV == "peo.ev"
        assert LOGGER_LOADS == "peo.loads"
        assert LOGGER_PV == "peo.pv"
        assert LOGGER_ANALYZER == "peo.analyzer"
        assert LOGGER_SERVICES == "peo.services"
        assert LOGGER_CONFIG == "peo.config"
        assert LOGGER_HEARTBEAT == "peo.heartbeat"
        assert LOGGER_API == "peo.api"
