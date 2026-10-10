"""Validates the OOA Spec schemas and their examples.

Valid examples live in spec/examples/valid/<schema>.<name>.json. Invalid cases are
built here as single mutations of a valid example, so each one breaks exactly one rule.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SPEC = Path(__file__).resolve().parents[1]
SCHEMAS = {p.name.removesuffix(".schema.json"): json.loads(p.read_text(encoding="utf-8"))
           for p in (SPEC / "schemas").glob("*.schema.json")}
REGISTRY = Registry().with_resources(
    (s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()
)
VALID = sorted((SPEC / "examples" / "valid").glob("*.json"))


def validator(name):
    return Draft202012Validator(
        SCHEMAS[name], registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def load(filename):
    return json.loads((SPEC / "examples" / "valid" / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_is_valid_draft_2020_12(name):
    Draft202012Validator.check_schema(SCHEMAS[name])


def test_every_schema_id_uses_the_project_base():
    base = "https://moonindustries.eu/ooat/spec/v0.2/"  # ADR 0013
    assert {name: s["$id"] for name, s in SCHEMAS.items()} == {
        name: f"{base}{name}.schema.json" for name in SCHEMAS}


def test_every_entity_has_a_valid_example():
    covered = {p.name.split(".")[0] for p in VALID}
    assert set(SCHEMAS) - {"common"} <= covered


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.name)
def test_valid_example(path):
    schema = path.name.split(".")[0]
    errors = list(validator(schema).iter_errors(json.loads(path.read_text(encoding="utf-8"))))
    assert not errors, [e.message for e in errors]


def _set(path, value):
    def mutate(doc):
        *parents, last = path
        for key in parents:
            doc = doc[key]
        doc[last] = value
    return mutate


def _delete(path):
    def mutate(doc):
        *parents, last = path
        for key in parents:
            doc = doc[key]
        del doc[last]
    return mutate


INVALID = [
    # (case id, schema, valid example, mutation)
    ("capability_deterministic_with_model_policy", "capability", "capability.design_semantic_model.json",
     _set(["impl"], "deterministic")),
    ("capability_llm_on_decision_tier", "capability", "capability.design_semantic_model.json",
     _set(["model_policy", "tier"], "decision")),
    ("capability_decision_on_text_tier", "capability", "capability.check_kpis_mapped.json",
     _set(["model_policy", "tier"], "economy")),
    ("capability_id_without_verb_object", "capability", "capability.validate_json.json",
     _set(["id"], "cap.qa.validate")),
    ("capability_critic_without_rubric", "capability", "capability.design_semantic_model.json",
     _delete(["acceptance", 2, "rubric"])),
    ("family_bad_id", "family", "family.analyst.json", _set(["id"], "analyst")),
    ("role_without_capabilities", "role", "role.bi_developer.json", _set(["capabilities"], [])),
    ("role_hil_gate_without_risk", "role", "role.bi_developer.json", _delete(["gates", 0, "risk"])),
    ("provider_personal_with_unknown_training", "provider", "provider.anthropic_subscription_cli.json",
     _set(["data_policy", "training_on_inputs"], None)),
    ("provider_subscription_without_plan", "provider", "provider.anthropic_subscription_cli.json",
     _delete(["plan"])),
    ("provider_without_jurisdiction", "provider", "provider.typesafe_api.json", _delete(["jurisdiction"])),
    ("routing_missing_special_category", "routing", "routing.reference.json",
     _delete(["data_class_policy", "special_category"])),
    ("contract_abbreviated_ulid", "contract", "contract.bi_semantic_model.json",
     _set(["id"], "ctr_01J9ZQ7F3C")),
    ("contract_unversioned_artifact", "contract", "contract.bi_semantic_model.json",
     _set(["inputs"], ["art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7"])),
    ("event_abstain_without_missing", "event", "event.abstain.json", _delete(["body", "missing"])),
    ("event_abstain_reason_too_long", "event", "event.abstain.json", _set(["body", "reason"], "x" * 301)),
    ("event_hil_request_four_options", "event", "event.hil_request.json",
     _set(["body", "options"], [{"id": c, "label": c, "cost_usd": 0} for c in "abcd"])),
    ("event_hil_request_without_default", "event", "event.hil_request.json",
     _delete(["body", "default_on_silence"])),
    ("event_hil_request_r3_without_do_not_act", "event", "event.hil_request_r3.json",
     _delete(["body", "options", 1, "acts"])),
    ("event_objection_without_artifact_ref", "event", "event.objection.json", _set(["refs"], [])),
    ("event_objection_unknown_reason_code", "event", "event.objection.json",
     _set(["body", "reason_code"], "I_DISAGREE")),
    ("event_result_partial_without_remaining", "event", "event.result_partial.json",
     _delete(["body", "remaining"])),
    ("event_result_by_human", "event", "event.result_partial.json",
     _set(["actor"], {"kind": "hil", "id": "operator"})),
    ("event_agent_without_role", "event", "event.abstain.json", _delete(["actor", "role"])),
    ("event_task_closed_abstained_without_missing", "event", "event.task_closed_abstained.json",
     _delete(["body", "missing"])),
    ("event_task_required_outside_acknowledgement", "event", "event.task_submitted.json", _set(["task"], None)),
    ("event_unknown_type", "event", "event.abstain.json", _set(["type"], "CHAT_MESSAGE")),
    ("event_non_utc_timestamp", "event", "event.abstain.json", _set(["ts"], "2026-09-28T21:20:00+02:00")),
    ("event_gate_rule_out_of_range", "event", "event.topology_decided.json",
     _set(["body", "rules_applied"], ["A11"])),
    # ADR 0010
    ("provider_operator_confirmed_is_no_longer_a_term", "provider", "provider.typesafe_api.json",
     _set(["automation_permitted"], "operator_confirmed")),
    ("event_acknowledgement_without_automation_answer", "event", "event.adapter_acknowledged.json",
     _delete(["body", "automation_confirmed"])),
    ("event_acknowledgement_with_bad_fingerprint", "event", "event.adapter_acknowledged.json",
     _set(["body", "jurisdiction_sha256"], "not-a-digest")),
    ("event_adapter_disabled_by_system", "event", "event.adapter_disabled.json",
     _set(["actor"], {"kind": "system", "id": "ooat-gateway"})),
    ("event_adapter_disabled_without_reason", "event", "event.adapter_disabled.json",
     _delete(["body", "reason"])),
    ("event_negative_estimate", "event", "event.result_partial.json",
     _set(["cost", "estimated_usd"], -1)),
    # ADR 0011
    ("event_project_with_spaces", "event", "event.task_submitted.json", _set(["body", "project"], "SME AI")),
    ("event_decision_confidence_above_one", "event", "event.topology_decided.json",
     _set(["body", "decisions", 0, "confidence"], 1.5)),
    ("event_decision_without_model_version", "event", "event.topology_decided.json",
     _delete(["body", "decisions", 0, "model"])),
    ("event_decision_bad_question_id", "event", "event.topology_decided.json",
     _set(["body", "decisions", 0, "question"], "A1 criterion")),
    ("event_gate_decision_without_engine", "event", "event.gate_passed.json",
     _delete(["body", "criteria", 0, "decision", "engine"])),
    ("event_gate_unknown_kind", "event", "event.gate_passed.json", _set(["body", "gate"], "gate.oracle.check")),
    ("event_rating_correction_without_value", "event", "event.task_rated.json",
     _delete(["body", "decisions", 1, "value"])),
    ("event_rating_unknown_verdict", "event", "event.task_rated.json",
     _set(["body", "decisions", 0, "verdict"], "maybe")),
    ("event_rating_without_event", "event", "event.task_rated.json", _delete(["body", "decisions", 0, "event"])),
    # ADR 0012
    ("event_responsibility_without_date", "event", "event.adapter_acknowledged_responsibility.json",
     _delete(["body", "responsibility", "confirmed_on"])),
    ("event_responsibility_region_not_a_code", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "processing_regions"], ["Europe"])),
    ("event_responsibility_training_stated_false", "event", "event.adapter_acknowledged_responsibility.json",
     _set(["body", "responsibility", "no_training"], False)),
    # ADR 0016
    ("event_token_issued_by_system", "event", "event.operator_token_issued.json",
     _set(["actor"], {"kind": "system", "id": "ooat-core"})),
    ("event_token_issued_on_a_task", "event", "event.operator_token_issued.json",
     _set(["task"], "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7")),
    ("event_token_issued_with_the_token_itself", "event", "event.operator_token_issued.json",
     _set(["body", "secret"], "ooat_abc")),
    ("event_token_unknown_scope", "event", "event.operator_token_issued.json", _set(["body", "scopes"], ["admin"])),
    ("event_token_special_category_cap", "event", "event.operator_token_issued.json",
     _set(["body", "max_data_class"], "special_category")),
    ("event_token_personal_cap_without_responsibility", "event", "event.operator_token_issued.json",
     _set(["body", "max_data_class"], "personal")),
    ("event_token_revoked_without_reason", "event", "event.operator_token_revoked.json", _delete(["body", "reason"])),
    ("event_channel_not_a_known_kind", "event", "event.task_submitted.json", _set(["body", "channel"], "telegram")),
    ("event_intake_key_with_spaces", "event", "event.task_submitted.json",
     lambda doc: doc["body"].update(channel="web", intake_key="chat 42 message 7")),
    ("event_intake_key_without_channel", "event", "event.task_submitted.json", _set(["body", "intake_key"], "m-7")),
]


@pytest.mark.parametrize("case", INVALID, ids=[c[0] for c in INVALID])
def test_invalid_example(case):
    _, schema, source, mutate = case
    doc = copy.deepcopy(load(source))
    assert validator(schema).is_valid(doc), "base example must be valid"
    mutate(doc)
    assert not validator(schema).is_valid(doc)


def test_human_events_record_their_channel_and_a_submission_its_intake_key():  # ADR 0016
    doc = load("event.task_submitted.json")
    doc["body"] |= {"channel": "token:tok_01J9ZQ80B0K3M5N7P9Q1R3S5T7", "intake_key": "chat-42:msg-7"}
    assert validator("event").is_valid(doc)
    for source in ("event.task_rated.json", "event.adapter_disabled.json", "event.adapter_acknowledged.json"):
        doc = load(source)
        doc["body"]["channel"] = "web"
        assert validator("event").is_valid(doc), source
