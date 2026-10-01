"""Checks every model connector package runs in its own tests (gateway design §10)."""

import time

from ..validation import validate
from . import Detection, jurisdiction_fingerprint


def check_connector(connector) -> None:
    """Raise AssertionError unless the connector meets the contract every OOAT connector must meet."""
    assert connector.kind == "model", "only model connectors are supported"
    validate("provider", connector.manifest)
    assert len(jurisdiction_fingerprint(connector.manifest)) == 64
    started = time.monotonic()
    detection = connector.detect()
    assert isinstance(detection, Detection) and detection.detail, "detect() returns a Detection with a detail"
    assert time.monotonic() - started < 5, "detect() must be fast and offline"
