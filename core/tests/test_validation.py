import json
from pathlib import Path

import pytest

from ooat_core.validation import SpecValidationError, validate

EXAMPLES = Path(__file__).resolve().parents[2] / "spec" / "examples" / "valid"


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_valid_documents_pass():
    validate("event", load("event.abstain.json"))
    validate("capability", load("capability.design_semantic_model.json"))


def test_every_violation_is_reported():
    event = load("event.abstain.json")
    del event["body"]["missing"]
    event["body"]["confidence"] = 2
    with pytest.raises(SpecValidationError) as info:
        validate("event", event)
    text = " ".join(info.value.messages)
    assert "missing" in text and "confidence" in text
    assert info.value.entity == "event"


def test_unknown_schema_is_an_error():
    with pytest.raises(KeyError):
        validate("nonsense", {})
