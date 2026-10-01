"""Validation against the OOA Spec JSON Schemas in spec/schemas."""

import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

# F1 runs from a repository checkout; shipping the schemas inside the wheel is part of the release work.
SCHEMA_DIR = Path(__file__).resolve().parents[3] / "spec" / "schemas"


class SpecValidationError(ValueError):
    """A document does not match its OOA Spec schema. `messages` lists every violation."""

    def __init__(self, entity: str, messages: list[str]):
        super().__init__(f"{entity}: " + "; ".join(messages))
        self.entity = entity
        self.messages = messages


@cache
def _validators() -> dict[str, Draft202012Validator]:
    schemas = {
        path.name.removesuffix(".schema.json"): json.loads(path.read_text(encoding="utf-8"))
        for path in SCHEMA_DIR.glob("*.schema.json")
    }
    if not schemas:
        raise FileNotFoundError(f"no OOA Spec schemas in {SCHEMA_DIR}")
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return {
        name: Draft202012Validator(schema, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER)
        for name, schema in schemas.items()
    }


def validate(entity: str, document: dict) -> None:
    """Raise SpecValidationError unless `document` matches spec/schemas/<entity>.schema.json."""
    validator = _validators().get(entity)
    if validator is None:
        raise KeyError(f"unknown OOA Spec schema: {entity}")
    errors = sorted(validator.iter_errors(document), key=lambda e: e.json_path)
    if errors:
        raise SpecValidationError(entity, [f"{e.json_path}: {e.message}" for e in errors])
