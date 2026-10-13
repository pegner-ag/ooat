import json
from pathlib import Path

import pytest
from connector_fakes import fake_manifest

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


def test_a_manifest_may_say_whether_it_can_work_with_project_folders():
    for value in (True, False, None):
        validate("provider", {**fake_manifest(), "features": {"workspace": value}})
    with pytest.raises(SpecValidationError):
        validate("provider", {**fake_manifest(), "features": {"workspace": "yes"}})


SHA = "sha256:" + "a" * 64
USED = {"id": "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "ts": "2026-10-13T10:00:00.000000Z",
        "task": "tsk_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "actor": {"kind": "system", "id": "ooat-runtime"},
        "type": "WORKSPACE_USED", "refs": [], "body": {
            "project": "bots", "by": "worker", "write": True, "read": [{"path": "Bots/a.py", "times": 2}],
            "changed": [{"path": "Bots/a.py", "before": SHA, "after": SHA, "added": 1, "removed": 1}],
            "created": [{"path": "Bots/b.py", "after": SHA, "added": 3}],
            "refused": [{"path": "Bots/.env", "tool": "read_file", "reason": "protected file"}],
            "operations": 4, "written_bytes": 120, "journal_lines": 4,
            "limit": {"kind": "operations", "operation": 301, "tool": "edit_file", "path": "Bots/a.py"}}}


def test_workspace_used_holds_paths_hashes_and_counts_only():
    validate("event", USED)
    with pytest.raises(SpecValidationError):
        validate("event", {**USED, "body": {**USED["body"], "content": "TOKEN=x"}})
    with pytest.raises(SpecValidationError):
        validate("event", {**USED, "actor": {"kind": "hil", "id": "operator"}})
    with pytest.raises(SpecValidationError):
        validate("event", {**USED, "body": {**USED["body"], "read": [{"path": "x" * 301, "times": 1}]}})


def test_workspace_reverted_is_the_operators_event():
    event = {**USED, "type": "WORKSPACE_REVERTED", "actor": {"kind": "hil", "id": "operator"}, "body": {
        "project": "bots", "restored": [{"path": "Bots/a.py", "after": SHA}],
        "skipped": [{"path": "Bots/c.py", "reason": "changed since the task"}], "kept": ["Bots/b.py"],
        "channel": "web"}}
    validate("event", event)
    with pytest.raises(SpecValidationError):
        validate("event", {**event, "actor": {"kind": "system", "id": "ooat-runtime"}})


def test_a_submitted_task_may_carry_its_workspace_and_the_task_it_follows():
    body = {"goal": "Oprav bot.", "project": "bots", "workspace": {"write": True, "folders": ["Bots"]},
            "follows": "tsk_01J9ZQ70A0K3M5N7P9Q1R3S5T7"}
    validate("event", {**USED, "type": "TASK_SUBMITTED", "actor": {"kind": "hil", "id": "operator"}, "body": body})


def test_a_hil_request_has_two_to_four_options():
    option = {"id": "a", "label": "A", "cost_usd": 0.0}
    body = {"question": "Co dál?", "recommended": "a", "default_on_silence": "a",
            "deadline": "2026-10-15T10:00:00Z", "blocking": True, "evidence": []}
    request = {**USED, "type": "HIL_REQUEST"}
    validate("event", {**request, "body": {**body, "options": [{**option, "id": i} for i in "abcd"]}})
    with pytest.raises(SpecValidationError):
        validate("event", {**request, "body": {**body, "options": [{**option, "id": i} for i in "abcde"]}})
