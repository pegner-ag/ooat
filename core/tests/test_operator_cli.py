import io
from datetime import date

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core.operator_cli import main
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger

TODAY = date(2026, 10, 1)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ooat.toml"
    url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
    path.write_text(f'[ledger]\nurl = "{url}"\n', encoding="utf-8")
    return path, url


def run(config, *argv, answers="", connectors=None):
    stdout = io.StringIO()
    registry = Registry(connectors if connectors is not None else [FakeConnector()])
    code = main(["--config", str(config[0]), *argv], stdin=io.StringIO(answers), stdout=stdout,
                registry=registry, today=TODAY)
    return code, stdout.getvalue()


def state_events(config):
    ledger = Ledger.open(config[1])
    events = ledger.events(types=["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"])
    ledger.close()
    return events


def test_list_shows_installed_connectors_and_their_state(config):
    code, out = run(config, "connectors", "list")
    assert code == 0 and "prv.fake.api  [not acknowledged]" in out and "tiers: workhorse=fake-model" in out


def test_show_prints_the_card_without_changing_anything(config):
    code, out = run(config, "connectors", "show", "prv.fake.api")
    assert code == 0 and "Connection consequences: prv.fake.api" in out
    assert state_events(config) == []


def test_interactive_enable_records_the_answers(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public, internal\nyes\nprv.fake.api\n")
    assert code == 0 and "enabled for public, internal; unattended use confirmed" in out
    (event,) = state_events(config)
    assert event["body"]["allowed_data_classes"] == ["public", "internal"]
    assert event["body"]["automation_confirmed"] is True and event["actor"]["id"] == "Martin"


def test_empty_class_answer_takes_the_safe_default(config):
    code, _ = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                  answers="\nno\nprv.fake.api\n")
    assert code == 0 and state_events(config)[0]["body"]["allowed_data_classes"] == ["public", "internal"]
    assert state_events(config)[0]["body"]["automation_confirmed"] is False


def test_wrong_confirmation_changes_nothing(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public\nyes\nprv.fake\n")
    assert code == 1 and "did not match" in out and state_events(config) == []


def test_non_interactive_enable_with_flags(config):
    code, _ = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
                  "--automation", "no", "--confirm", "prv.fake.api")
    assert code == 0 and state_events(config)[0]["body"]["allowed_data_classes"] == ["public"]


def test_terms_that_forbid_automation_are_never_asked_and_never_confirmed(config):
    connector = FakeConnector(fake_manifest(automation="not_permitted"))
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    answers="public\nprv.fake.api\n", connectors=[connector])
    assert code == 0 and "Do the terms of your plan allow" not in out
    assert state_events(config)[0]["body"]["automation_confirmed"] is False


def test_refused_classes_report_and_change_nothing(config):
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                    "--classes", "special_category", "--automation", "no", "--confirm", "prv.fake.api")
    assert code == 1 and "Refused" in out and state_events(config) == []


def test_unknown_connector_is_reported(config):
    code, out = run(config, "connectors", "show", "prv.missing.api")
    assert code == 1 and "not installed" in out


def test_disable_records_operator_and_reason(config):
    code, _ = run(config, "connectors", "disable", "prv.fake.api", "--operator", "Martin", "--reason", "trial ended")
    assert code == 0 and state_events(config)[0]["body"] == {
        "adapter": "prv.fake.api", "operator": "Martin", "reason": "trial ended"}


def test_disable_with_a_malformed_id_is_refused(config):
    code, out = run(config, "connectors", "disable", "anthropic", "--operator", "Martin", "--reason", "x")
    assert code == 1 and "Refused" in out


def test_console_script_is_installed():
    from importlib.metadata import entry_points

    (script,) = [e for e in entry_points(group="console_scripts") if e.name == "ooat"]
    assert script.value == "ooat_core.operator_cli:main"


def test_missing_explicit_config_is_refused_and_writes_no_ledger(tmp_path):
    stdout = io.StringIO()
    code = main(["--config", str(tmp_path / "typo.toml"), "connectors", "disable", "prv.fake.api", "--operator", "M",
                 "--reason", "x"], stdin=io.StringIO(), stdout=stdout, registry=Registry([FakeConnector()]),
                today=TODAY)
    assert code == 1 and "not found" in stdout.getvalue()
    assert list(tmp_path.iterdir()) == []


def test_list_tells_when_an_enabled_connector_is_not_usable_unattended(config):
    run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
        "--automation", "no", "--confirm", "prv.fake.api")
    _, out = run(config, "connectors", "list")
    assert "[enabled, not usable unattended]" in out


def test_explicit_yes_for_forbidding_terms_is_refused(config):
    connector = FakeConnector(fake_manifest(automation="not_permitted"))
    code, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
                    "--automation", "yes", "--confirm", "prv.fake.api", connectors=[connector])
    assert code == 1 and "do not permit" in out and state_events(config) == []
