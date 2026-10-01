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


def run_without_config(directory, *argv, answers=""):
    stdout = io.StringIO()
    code = main(list(argv), stdin=io.StringIO(answers), stdout=stdout, registry=Registry([FakeConnector()]),
                today=TODAY)
    return code, stdout.getvalue()


def test_read_only_commands_without_config_create_no_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run_without_config(tmp_path, "connectors", "show", "prv.fake.api")[0] == 0
    code, out = run_without_config(tmp_path, "connectors", "list")
    assert code == 0 and "no ooat.toml" in out.lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [
    ("connectors", "enable", "prv.fake.api", "--operator", "M", "--classes", "public", "--automation", "no",
     "--confirm", "prv.fake.api"),
    ("connectors", "disable", "prv.fake.api", "--operator", "M", "--reason", "x"),
])
def test_state_changes_without_config_are_refused(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    code, out = run_without_config(tmp_path, *argv)
    assert code == 1 and "ooat.toml" in out and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content, message", [
    ("[ledger\n", "Config error"),
    ("[secrets]\n", "Config error"),
    ('[ledger]\nurl = "postgresql://host/ooat"\n', "Cannot open ledger"),
    ('[ledger]\nurl = "sqlite:///missing/folder/ledger.sqlite"\n', "Cannot open ledger"),
])
def test_config_and_ledger_mistakes_end_without_a_traceback(tmp_path, content, message):
    path = tmp_path / "ooat.toml"
    path.write_text(content, encoding="utf-8")
    code, out = run((path, None), "connectors", "list")
    assert code == 1 and message in out


def test_success_names_the_ledger_written(config):
    _, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public",
                 "--automation", "no", "--confirm", "prv.fake.api")
    assert "ledger.sqlite" in out


def test_summary_before_confirmation_repeats_what_is_allowed(config):
    _, out = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin",
                 answers="public\nno\nprv.fake.api\n")
    assert "You are allowing: public; unattended use: no" in out


@pytest.mark.parametrize("argv", [
    ("--operator", " ", "--classes", "public"),
    ("--operator", "Martin", "--classes", "secret"),
    ("--operator", "Martin", "--classes", ""),
])
def test_bad_operator_or_classes_are_refused_before_any_question(config, argv):
    code, out = run(config, "connectors", "enable", "prv.fake.api", *argv)
    assert code == 1 and "Do the terms" not in out and "to confirm" not in out and state_events(config) == []


def test_end_of_input_changes_nothing(config):
    code, _ = run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", answers="")
    assert code == 1 and state_events(config) == []


def test_manual_relay_is_not_asked_and_explicit_yes_is_refused(config):
    manual = fake_manifest("prv.fake.subscription_manual", "subscription_manual")
    manual["metering"] = "none"
    code, out = run(config, "connectors", "enable", "prv.fake.subscription_manual", "--operator", "Martin",
                    "--classes", "public", "--automation", "yes", "--confirm", "prv.fake.subscription_manual",
                    connectors=[FakeConnector(manual)])
    assert code == 1 and "manual relay" in out
    code, out = run(config, "connectors", "enable", "prv.fake.subscription_manual", "--operator", "Martin",
                    answers="public\nprv.fake.subscription_manual\n", connectors=[FakeConnector(manual)])
    assert code == 0 and "Do the terms" not in out


def test_ctrl_c_at_a_prompt_cancels_cleanly(config):
    class Interrupting(io.StringIO):
        def readline(self, *args):
            raise KeyboardInterrupt

    stdout = io.StringIO()
    code = main(["--config", str(config[0]), "connectors", "enable", "prv.fake.api", "--operator", "Martin"],
                stdin=Interrupting(), stdout=stdout, registry=Registry([FakeConnector()]), today=TODAY)
    assert code == 130 and "nothing was changed" in stdout.getvalue() and state_events(config) == []


def test_enabled_through_the_cli_the_gateway_routes_to_it(config):
    from ooat_core.config import load_config
    from ooat_core.connectors import ModelRequest
    from ooat_core.gateway import Gateway
    from ooat_core.ids import new_id
    from ooat_core.routing import RoutingPolicy

    run(config, "connectors", "enable", "prv.fake.api", "--operator", "Martin", "--classes", "public,internal",
        "--automation", "yes", "--confirm", "prv.fake.api")
    policy = {c: {"allowed": True} for c in ("public", "internal", "client_confidential", "personal")}
    policy["special_category"] = {"allowed": True, "require_verified_redaction": True}
    routing = RoutingPolicy({"version": "0.1.0", "data_class_policy": policy, "prices": [
        {"adapter": "prv.fake.api", "model": "fake-model", "usd_per_mtok_in": 1, "usd_per_mtok_out": 5,
         "valid_from": "2026-01-01", "source": "https://fake.invalid/pricing"}]})
    ledger = Ledger.open(load_config(config[0]).ledger_url)
    try:
        gateway = Gateway(ledger, Registry([FakeConnector()]), routing)
        request = ModelRequest(tier="workhorse", prompt="x", data_class="internal", task=new_id("tsk"))
        assert gateway.call(request).cost["adapter"] == "prv.fake.api"
    finally:
        ledger.close()
