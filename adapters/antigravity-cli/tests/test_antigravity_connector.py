import json
import os
from pathlib import Path

import pytest

import ooat_adapter_antigravity_cli as adapter
from ooat_adapter_antigravity_cli import MANIFEST, AntigravityConnector
from ooat_core.connectors import ConnectorError, ModelRequest
from ooat_core.connectors.cli import CliResult
from ooat_core.connectors.conformance import check_connector
from ooat_core.connectors.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_conformance():
    check_connector(AntigravityConnector(executable="agy-not-installed"))


def test_entry_point_is_registered():
    assert isinstance(Registry.discover().get("prv.google.subscription_cli"), AntigravityConnector)


def test_manifest_states_training_and_leaves_unknowns_null():
    assert MANIFEST["data_policy"]["training_on_inputs"] is True
    assert MANIFEST["jurisdiction"]["training_on_inputs"] is True
    assert MANIFEST["data_policy"]["allowed_data_classes"] == ["public", "internal"]
    assert MANIFEST["automation_permitted"] == "unknown"
    assert MANIFEST["jurisdiction"]["verified_on"] is None and MANIFEST["jurisdiction"]["vendor_entity"] is None
    assert MANIFEST["tiers"] == {"economy": "gemini-3.8-flash-low", "workhorse": "gemini-3.8-flash-high",
                                 "frontier": "gemini-3.1-pro-high"}
