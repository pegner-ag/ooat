import pytest
from connector_fakes import FakeConnector, fake_manifest

from datetime import date

from ooat_core.connectors import ConnectorError, jurisdiction_fingerprint, jurisdiction_stale, registry
from ooat_core.connectors.registry import Registry


def test_valid_connector_is_registered():
    reg = Registry([FakeConnector()])
    assert reg.ids() == ["prv.fake.api"]
    assert reg.get("prv.fake.api").kind == "model"
    assert reg.broken == []


def test_invalid_manifest_is_listed_as_broken_and_not_used():
    manifest = fake_manifest()
    del manifest["jurisdiction"]
    reg = Registry([FakeConnector(manifest), FakeConnector(fake_manifest("prv.other.api"))])
    assert reg.ids() == ["prv.other.api"]
    assert reg.broken[0].name == "prv.fake.api" and "jurisdiction" in reg.broken[0].error


def test_unsupported_kind_is_broken():
    tool = FakeConnector()
    tool.kind = "tool"
    reg = Registry([tool])
    assert reg.ids() == [] and "kind" in reg.broken[0].error


def test_duplicate_ids_make_both_unusable():
    reg = Registry([FakeConnector(), FakeConnector()])
    assert reg.ids() == []
    assert reg.broken[0].name == "prv.fake.api"


class EntryPoint:
    def __init__(self, name, factory):
        self.name, self._factory = name, factory

    def load(self):
        return self._factory


def test_discover_loads_entry_points_and_survives_a_broken_plugin(monkeypatch):
    def failing():
        raise ImportError("missing dependency")

    monkeypatch.setattr(registry, "entry_points", lambda group: [
        EntryPoint("fake", FakeConnector), EntryPoint("bad", lambda: failing())])
    reg = Registry.discover()
    assert reg.ids() == ["prv.fake.api"]
    assert [b.name for b in reg.broken] == ["bad"]


def test_jurisdiction_fingerprint_ignores_key_order_and_detects_changes():
    manifest = fake_manifest()
    reordered = dict(manifest, jurisdiction=dict(reversed(list(manifest["jurisdiction"].items()))))
    changed = dict(manifest, jurisdiction=dict(manifest["jurisdiction"], processing_regions=["us"]))
    assert jurisdiction_fingerprint(manifest) == jurisdiction_fingerprint(reordered)
    assert jurisdiction_fingerprint(manifest) != jurisdiction_fingerprint(changed)


def test_jurisdiction_staleness_follows_spec_rule_2():
    manifest = fake_manifest()
    acknowledgement = {"jurisdiction_sha256": jurisdiction_fingerprint(manifest)}
    assert not jurisdiction_stale(manifest, acknowledgement, date(2026, 10, 1))
    assert jurisdiction_stale(manifest, acknowledgement, date(2027, 9, 2))  # verified_on older than 12 months
    assert jurisdiction_stale(manifest, {"jurisdiction_sha256": "0" * 64}, date(2026, 10, 1))
    assert jurisdiction_stale(manifest, {}, date(2026, 10, 1))  # acknowledgement from before ADR 0010
    unverified = fake_manifest(jurisdiction=dict(manifest["jurisdiction"], verified_on=None))
    assert jurisdiction_stale(unverified, {"jurisdiction_sha256": jurisdiction_fingerprint(unverified)},
                              date(2026, 10, 1))


def test_connector_error_codes_are_the_schema_codes():
    assert ConnectorError("UNAVAILABLE", "claude not on PATH").code == "UNAVAILABLE"
    with pytest.raises(ValueError):
        ConnectorError("PROVIDER_ERROR", "x")
