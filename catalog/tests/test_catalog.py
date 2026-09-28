"""Checks the starter catalog: family cards against the spec schema, the family chain rules
of ADR 0004, and the capability taxonomy against spec section 5."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "catalog"
SCHEMAS = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "spec" / "schemas").glob("*.schema.json")]
REGISTRY = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in SCHEMAS)
COMMON = next(s for s in SCHEMAS if s["$id"].endswith("/common.schema.json"))
FAMILY_SCHEMA = next(s for s in SCHEMAS if s["$id"].endswith("/family.schema.json"))

FAMILIES = {f["id"]: f for f in (json.loads(p.read_text(encoding="utf-8"))
                                 for p in (CATALOG / "families").glob("*.json"))}
TAXONOMY = json.loads((CATALOG / "taxonomy.json").read_text(encoding="utf-8"))
CAPABILITIES = [c for d in TAXONOMY["domains"] for c in d["capabilities"]]

# Spec section 5, "Starter capability domains". Further domains may be added freely;
# per-domain targets live in taxonomy.json.
STARTER_DOMAINS = {"mgmt", "account", "arch", "data", "bi", "dev", "ai", "qa", "sec", "fin", "mkt", "research", "doc"}
KINDS = {"family.analyst", "family.builder", "family.reviewer", "family.communicator", "family.orchestrator"}


@pytest.mark.parametrize("family_id", sorted(FAMILIES))
def test_family_matches_schema(family_id):
    v = Draft202012Validator(FAMILY_SCHEMA, registry=REGISTRY)
    errors = list(v.iter_errors(FAMILIES[family_id]))
    assert not errors, [e.message for e in errors]


def test_family_chain():
    assert set(FAMILIES) == {"family.base"} | KINDS
    assert "extends" not in FAMILIES["family.base"]
    for fid in KINDS:
        assert FAMILIES[fid]["extends"] == "family.base"


def _covered(scope, parent_scopes):
    return any(p == scope or (p.endswith("*") and scope.startswith(p[:-1])) for p in parent_scopes)


@pytest.mark.parametrize("family_id", sorted(KINDS))
def test_family_only_narrows_base(family_id):
    child, parent = FAMILIES[family_id], FAMILIES["family.base"]
    cp, pp = child.get("permissions", {}), parent["permissions"]
    for key in ("read", "write"):
        widened = [s for s in cp.get(key, []) if not _covered(s, pp.get(key, []))]
        assert not widened, f"{key} widened: {widened}"
    assert not (cp.get("network") and not pp.get("network"))
    assert not (cp.get("code_exec") == "sandbox" and pp.get("code_exec") != "sandbox")
    for key, limit in parent["budget"].items():
        assert child.get("budget", {}).get(key, limit) <= limit


def test_domains_unique_and_include_starter_set():
    ids = [d["id"] for d in TAXONOMY["domains"]]
    assert len(ids) == len(set(ids))
    assert STARTER_DOMAINS <= set(ids)
    assert "general" in ids, "T2 fallback capability domain"


@pytest.mark.parametrize("domain", TAXONOMY["domains"], ids=lambda d: d["id"])
def test_domain_count_within_target(domain):
    assert abs(len(domain["capabilities"]) - domain["target"]) <= 2


@pytest.mark.parametrize("domain", TAXONOMY["domains"], ids=lambda d: d["id"])
def test_capability_ids_belong_to_domain(domain):
    for cap in domain["capabilities"]:
        assert cap["id"].split(".")[1] == domain["id"], cap["id"]


def test_capabilities_are_well_formed_and_unique():
    ids = [c["id"] for c in CAPABILITIES]
    assert len(ids) == len(set(ids))
    item = {
        "type": "object",
        "required": ["id", "impl", "summary"],
        "additionalProperties": False,
        "properties": {
            "id": {"$ref": "common.schema.json#/$defs/capability_id"},
            "impl": {"$ref": "common.schema.json#/$defs/impl"},
            "summary": {"type": "string", "minLength": 1, "maxLength": 200},
        },
    }
    v = Draft202012Validator({"$id": COMMON["$id"].replace("common", "taxonomy_item"), **item}, registry=REGISTRY)
    errors = [(c["id"], e.message) for c in CAPABILITIES for e in v.iter_errors(c)]
    assert not errors
