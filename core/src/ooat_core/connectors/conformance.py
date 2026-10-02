"""Checks every connector package runs in its own tests (gateway design §10)."""

import time

from ..validation import validate
from . import CONNECTOR_KINDS, Detection, jurisdiction_fingerprint


def check_connector(connector) -> None:
    """Raise AssertionError unless the connector meets the contract every OOAT connector must meet."""
    assert connector.kind in CONNECTOR_KINDS, f"unsupported connector kind: {connector.kind!r}"
    validate("provider", connector.manifest)
    decision_tier = "decision" in connector.manifest["tiers"]
    assert decision_tier == (connector.kind == "decision"), "the decision tier is served by decision connectors only"
    assert connector.kind != "decision" or len(connector.manifest["tiers"]) == 1, "a decision connector serves one tier"
    assert len(jurisdiction_fingerprint(connector.manifest)) == 64
    started = time.monotonic()
    detection = connector.detect()
    assert isinstance(detection, Detection) and detection.detail, "detect() returns a Detection with a detail"
    assert time.monotonic() - started < 5, "detect() must be fast and offline"
