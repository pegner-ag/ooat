"""Capability and role cards in catalog/ (design 04 §5): valid against the spec and consistent with the catalog."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ooat_core.validation import validate

CATALOG = Path(__file__).resolve().parents[1]
CAPABILITIES = {c["id"]: c for c in (json.loads(p.read_text(encoding="utf-8"))
                                     for p in (CATALOG / "capabilities").glob("*.json"))}
ROLES = {r["id"]: r for r in (json.loads(p.read_text(encoding="utf-8")) for p in (CATALOG / "roles").glob("*.json"))}
FAMILIES = {f["id"]: f for f in (json.loads(p.read_text(encoding="utf-8"))
                                 for p in (CATALOG / "families").glob("*.json"))}
TAXONOMY = {c["id"]: c for d in json.loads((CATALOG / "taxonomy.json").read_text(encoding="utf-8"))["domains"]
            for c in d["capabilities"]}


@pytest.mark.parametrize("path", sorted((CATALOG / "capabilities").glob("*.json")), ids=lambda p: p.name)
def test_capability_card_is_valid_and_named_after_its_id(path):
    card = json.loads(path.read_text(encoding="utf-8"))
    validate("capability", card)
    assert path.stem == card["id"]
    assert TAXONOMY[card["id"]]["impl"] == card["impl"]


@pytest.mark.parametrize("path", sorted((CATALOG / "roles").glob("*.json")), ids=lambda p: p.name)
def test_role_card_is_valid_and_only_narrows_its_family(path):
    role = json.loads(path.read_text(encoding="utf-8"))
    validate("role", role)
    assert path.stem == role["id"]
    family = FAMILIES[role["extends"]]
    assert set(role["capabilities"]) <= set(CAPABILITIES)
    assert role["budget"]["max_usd_per_contract"] <= family["budget"]["max_usd_per_contract"]
    assert family["permissions"]["network"] or not role["permissions"]["network"]
    assert set(role["permissions"]["write"]) <= set(family["permissions"]["write"])


def test_decision_checks_name_existing_decision_capabilities():
    for card in CAPABILITIES.values():
        for criterion in card["acceptance"]:
            if criterion["type"] == "decision":
                assert CAPABILITIES[criterion["capability"]]["impl"] == "decision"


@pytest.mark.parametrize("card_id", sorted(CAPABILITIES))
def test_referenced_schemas_exist_and_are_json_schemas(card_id):
    card = CAPABILITIES[card_id]
    for key in ("input_schema", "output_schema"):
        path = CATALOG / card[key]
        assert path.is_file(), f"{card_id}: {card[key]} is missing"
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("card_id", sorted(CAPABILITIES))
def test_every_card_has_an_eval_set_that_covers_its_abstain_conditions(card_id):
    card = CAPABILITIES[card_id]
    cases = json.loads((CATALOG.parent / card["eval_set"] / "cases.json").read_text(encoding="utf-8"))
    assert cases and all({"id", "expect"} <= set(case) for case in cases)
    covered = {case.get("covers") for case in cases}
    assert set(card.get("abstain_conditions", [])) <= covered
