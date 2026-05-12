"""Testy jednostkowe dla TariffDefinitionLoader."""

import json
import pytest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from custom_components.peo.enums import OSDOperator, TariffType, TimeZoneName
from custom_components.peo.models import TariffDefinition, TariffRates
from custom_components.peo.tariff_loader import TariffDefinitionLoader, TariffLoadError


class TestLoadTariff:
    """Testy load_tariff()."""

    def test_load_g11_single_zone(self):
        """G11 — taryfa jednostrefowa z jedną strefą 'jednolita'."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G11)

        assert isinstance(result, TariffDefinition)
        assert result.tariff_type == TariffType.G11
        assert result.zones == [TimeZoneName.SINGLE]

    def test_load_g12_two_zones(self):
        """G12 — taryfa dwustrefowa z 'szczyt' i 'pozaszczyt'."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G12)

        assert isinstance(result, TariffDefinition)
        assert result.tariff_type == TariffType.G12
        assert TimeZoneName.SZCZYT in result.zones
        assert TimeZoneName.POZASZCZYT in result.zones

    def test_load_g12w_with_weekend(self):
        """G12w — taryfa z weekendem."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G12W)

        assert result.tariff_type == TariffType.G12W
        assert TimeZoneName.WEEKEND in result.zones

    def test_load_g13_three_zones(self):
        """G13 — taryfa trzystrefowa."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G13)

        assert result.tariff_type == TariffType.G13
        assert TimeZoneName.SZCZYT_PORANNY in result.zones
        assert TimeZoneName.SZCZYT_POPOLUDNIOWY in result.zones
        assert TimeZoneName.POZASZCZYT in result.zones

    def test_zone_hours_populated_for_operators(self):
        """zone_hours powinno zawierać dane dla operatorów obsługujących taryfę."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G12)

        # G12 is supported by all operators
        assert OSDOperator.TAURON in result.zone_hours
        assert OSDOperator.PGE in result.zone_hours
        assert OSDOperator.ENEA in result.zone_hours
        assert OSDOperator.ENERGA in result.zone_hours
        assert OSDOperator.INNOGY_STOEN in result.zone_hours

    def test_zone_hours_contain_time_pairs(self):
        """zone_hours powinno zawierać pary (start, end) jako stringi."""
        loader = TariffDefinitionLoader()
        result = loader.load_tariff(TariffType.G12)

        tauron_zones = result.zone_hours[OSDOperator.TAURON]
        assert TimeZoneName.SZCZYT in tauron_zones
        assert TimeZoneName.POZASZCZYT in tauron_zones

        # Check that time pairs are tuples of strings
        szczyt_hours = tauron_zones[TimeZoneName.SZCZYT]
        assert len(szczyt_hours) > 0
        for pair in szczyt_hours:
            assert len(pair) == 2
            assert isinstance(pair[0], str)
            assert isinstance(pair[1], str)

    def test_caching_returns_same_instance(self):
        """Drugie wywołanie powinno zwrócić tę samą instancję z cache."""
        loader = TariffDefinitionLoader()
        result1 = loader.load_tariff(TariffType.G12)
        result2 = loader.load_tariff(TariffType.G12)

        assert result1 is result2

    def test_load_all_tariff_types(self):
        """Wszystkie typy taryf powinny się załadować bez błędów."""
        loader = TariffDefinitionLoader()
        for tariff_type in TariffType:
            result = loader.load_tariff(tariff_type)
            assert isinstance(result, TariffDefinition)
            assert result.tariff_type == tariff_type
            assert len(result.zones) > 0

    def test_load_tariff_file_not_found(self, tmp_path):
        """Powinien rzucić TariffLoadError gdy plik nie istnieje."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            # Create tariffs dir but no file
            (tmp_path / "tariffs").mkdir()
            with pytest.raises(TariffLoadError, match="Nie znaleziono pliku"):
                loader.load_tariff(TariffType.G11)

    def test_load_tariff_invalid_json(self, tmp_path):
        """Powinien rzucić TariffLoadError przy nieprawidłowym JSON."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            tariffs_dir = tmp_path / "tariffs"
            tariffs_dir.mkdir()
            (tariffs_dir / "G11.json").write_text("not valid json{{{", encoding="utf-8")

            with pytest.raises(TariffLoadError, match="Nieprawidłowy format JSON"):
                loader.load_tariff(TariffType.G11)

    def test_load_tariff_missing_zones_field(self, tmp_path):
        """Powinien rzucić TariffLoadError gdy brak pola 'zones'."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            tariffs_dir = tmp_path / "tariffs"
            tariffs_dir.mkdir()
            osd_dir = tmp_path / "osd"
            osd_dir.mkdir()
            (tariffs_dir / "G11.json").write_text(
                json.dumps({"tariff_type": "G11"}), encoding="utf-8"
            )

            with pytest.raises(TariffLoadError, match="Nieprawidłowa definicja stref"):
                loader.load_tariff(TariffType.G11)


class TestLoadOsdZones:
    """Testy load_osd_zones()."""

    def test_load_tauron(self):
        """Załaduj definicję stref Tauron."""
        loader = TariffDefinitionLoader()
        result = loader.load_osd_zones(OSDOperator.TAURON)

        assert isinstance(result, dict)
        assert result["operator"] == "tauron"
        assert "zones" in result
        assert "G12" in result["zones"]

    def test_load_pge(self):
        """Załaduj definicję stref PGE."""
        loader = TariffDefinitionLoader()
        result = loader.load_osd_zones(OSDOperator.PGE)

        assert result["operator"] == "pge"
        assert "name" in result

    def test_load_all_operators(self):
        """Wszystkie operatory powinny się załadować bez błędów."""
        loader = TariffDefinitionLoader()
        for operator in OSDOperator:
            result = loader.load_osd_zones(operator)
            assert isinstance(result, dict)
            assert result["operator"] == operator.value
            assert "zones" in result

    def test_osd_zones_contain_tariff_definitions(self):
        """Definicja OSD powinna zawierać strefy dla taryf wielostrefowych."""
        loader = TariffDefinitionLoader()
        result = loader.load_osd_zones(OSDOperator.TAURON)

        zones = result["zones"]
        # G12 should have szczyt and pozaszczyt
        assert "szczyt" in zones["G12"]
        assert "pozaszczyt" in zones["G12"]

    def test_caching_returns_same_instance(self):
        """Drugie wywołanie powinno zwrócić tę samą instancję z cache."""
        loader = TariffDefinitionLoader()
        result1 = loader.load_osd_zones(OSDOperator.TAURON)
        result2 = loader.load_osd_zones(OSDOperator.TAURON)

        assert result1 is result2

    def test_load_osd_file_not_found(self, tmp_path):
        """Powinien rzucić TariffLoadError gdy plik OSD nie istnieje."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            (tmp_path / "osd").mkdir()
            with pytest.raises(TariffLoadError, match="Nie znaleziono pliku"):
                loader.load_osd_zones(OSDOperator.TAURON)

    def test_load_osd_invalid_structure(self, tmp_path):
        """Powinien rzucić TariffLoadError przy brakujących polach."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            osd_dir = tmp_path / "osd"
            osd_dir.mkdir()
            (osd_dir / "tauron.json").write_text(
                json.dumps({"name": "Tauron"}), encoding="utf-8"
            )

            with pytest.raises(TariffLoadError, match="Nieprawidłowa struktura"):
                loader.load_osd_zones(OSDOperator.TAURON)


class TestLoadDefaultRates:
    """Testy load_default_rates()."""

    def test_load_tauron_g12(self):
        """Załaduj domyślne stawki Tauron G12."""
        loader = TariffDefinitionLoader()
        result = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)

        assert isinstance(result, TariffRates)
        assert result.energy_price > Decimal("0")
        assert result.distribution_variable > Decimal("0")
        assert result.transition_fee > Decimal("0")
        assert result.oze_fee > Decimal("0")
        assert result.capacity_fee > Decimal("0")
        assert result.cogeneration_fee > Decimal("0")

    def test_load_pge_g11(self):
        """Załaduj domyślne stawki PGE G11."""
        loader = TariffDefinitionLoader()
        result = loader.load_default_rates(OSDOperator.PGE, TariffType.G11)

        assert isinstance(result, TariffRates)
        assert result.energy_price == Decimal("0.6195")

    def test_all_six_components_present(self):
        """TariffRates powinno mieć wszystkie 6 składników."""
        loader = TariffDefinitionLoader()
        result = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)

        # All 6 components should be non-negative Decimals
        assert isinstance(result.energy_price, Decimal)
        assert isinstance(result.distribution_variable, Decimal)
        assert isinstance(result.transition_fee, Decimal)
        assert isinstance(result.oze_fee, Decimal)
        assert isinstance(result.capacity_fee, Decimal)
        assert isinstance(result.cogeneration_fee, Decimal)

    def test_load_all_operator_tariff_combinations(self):
        """Wszystkie kombinacje operator/taryfa powinny się załadować."""
        loader = TariffDefinitionLoader()
        for operator in OSDOperator:
            for tariff in TariffType:
                result = loader.load_default_rates(operator, tariff)
                assert isinstance(result, TariffRates)
                assert result.energy_price > Decimal("0")

    def test_caching_returns_same_instance(self):
        """Drugie wywołanie powinno zwrócić tę samą instancję z cache."""
        loader = TariffDefinitionLoader()
        result1 = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)
        result2 = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)

        assert result1 is result2

    def test_different_operators_have_different_rates(self):
        """Różni operatorzy powinni mieć różne stawki dystrybucyjne."""
        loader = TariffDefinitionLoader()
        tauron = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)
        pge = loader.load_default_rates(OSDOperator.PGE, TariffType.G12)

        # Distribution variable should differ between operators
        assert tauron.distribution_variable != pge.distribution_variable

    def test_common_fees_are_same_across_operators(self):
        """Opłaty wspólne (przejściowa, OZE, mocowa, kogeneracyjna) powinny być takie same."""
        loader = TariffDefinitionLoader()
        tauron = loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)
        pge = loader.load_default_rates(OSDOperator.PGE, TariffType.G12)

        assert tauron.transition_fee == pge.transition_fee
        assert tauron.oze_fee == pge.oze_fee
        assert tauron.capacity_fee == pge.capacity_fee
        assert tauron.cogeneration_fee == pge.cogeneration_fee

    def test_load_rates_invalid_operator(self, tmp_path):
        """Powinien rzucić TariffLoadError dla brakującego operatora."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            defaults_dir = tmp_path / "defaults"
            defaults_dir.mkdir()
            (defaults_dir / "rates_2024.json").write_text(
                json.dumps({"operators": {}}), encoding="utf-8"
            )

            with pytest.raises(TariffLoadError, match="Brak stawek dla operatora"):
                loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)

    def test_load_rates_invalid_tariff(self, tmp_path):
        """Powinien rzucić TariffLoadError dla brakującej taryfy."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            defaults_dir = tmp_path / "defaults"
            defaults_dir.mkdir()
            (defaults_dir / "rates_2024.json").write_text(
                json.dumps({"operators": {"tauron": {}}}), encoding="utf-8"
            )

            with pytest.raises(TariffLoadError, match="Brak stawek dla taryfy"):
                loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)

    def test_load_rates_file_not_found(self, tmp_path):
        """Powinien rzucić TariffLoadError gdy plik rates nie istnieje."""
        loader = TariffDefinitionLoader()

        with patch(
            "custom_components.peo.tariff_loader._DATA_DIR", tmp_path
        ):
            (tmp_path / "defaults").mkdir()
            with pytest.raises(TariffLoadError, match="Nie znaleziono pliku"):
                loader.load_default_rates(OSDOperator.TAURON, TariffType.G12)
