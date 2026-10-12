"""First-run setup's shared parts (design 05 §10, plan 01c): the data folder, the config, what the machine has."""

import getpass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core import setup
from ooat_core.config import load_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def test_the_data_folder_follows_the_os_unless_ooat_home_is_set(tmp_path):
    home = tmp_path / "jana"
    assert setup.data_folder({"APPDATA": str(tmp_path / "Roaming")}, "win32", home) == tmp_path / "Roaming" / "ooat"
    assert setup.data_folder({}, "win32", home) == home / "AppData" / "Roaming" / "ooat"
    assert setup.data_folder({}, "darwin", home) == home / "Library" / "Application Support" / "ooat"
    assert setup.data_folder({"XDG_DATA_HOME": str(tmp_path / "xdg")}, "linux", home) == tmp_path / "xdg" / "ooat"
    assert setup.data_folder({}, "linux", home) == home / ".local" / "share" / "ooat"
    assert setup.data_folder({"OOAT_HOME": str(tmp_path / "own"), "APPDATA": "x"}, "win32", home) == tmp_path / "own"


def test_the_config_is_the_named_one_then_the_local_one_then_the_data_folders(tmp_path):
    environ = {"OOAT_HOME": str(tmp_path / "home")}
    work = tmp_path / "work"
    work.mkdir()
    assert setup.find_config("other.toml", work, environ) == Path("other.toml")
    assert setup.find_config(None, work, environ) == tmp_path / "home" / "ooat.toml"  # need not exist yet
    (work / "ooat.toml").write_text("", encoding="utf-8")
    assert setup.find_config(None, work, environ) == work / "ooat.toml"


def test_the_written_config_loads_and_is_never_overwritten(tmp_path):
    path = tmp_path / "home" / "ooat.toml"
    text = setup.config_text(tmp_path / "data", "Jana Nováková", {"prv.anthropic.api": "ANTHROPIC_API_KEY"})
    setup.write_config(path, text)
    config = load_config(path)
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'data' / 'ooat-ledger.sqlite').as_posix()}"
    assert config.serve["operator"] == "Jana Nováková"
    assert config.connectors == {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}
    with pytest.raises(FileExistsError):
        setup.write_config(path, setup.config_text(tmp_path / "elsewhere", "Petr"))
    assert path.read_text(encoding="utf-8") == text


def test_a_bad_name_or_a_pasted_key_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError):
        setup.config_text(tmp_path, "   ")
    with pytest.raises(ValueError):
        setup.config_text(tmp_path, "Jana", {"prv.anthropic.api": "sk-ant-123"})  # a value, not a variable's name
    assert list(tmp_path.iterdir()) == []


def test_the_default_operator_is_the_os_account_or_operator(monkeypatch):
    monkeypatch.setattr(getpass, "getuser", lambda: "jana")
    assert setup.operator_name() == "jana"

    def no_name():
        raise OSError("no login name")
    monkeypatch.setattr(getpass, "getuser", no_name)
    assert setup.operator_name() == "operator"
    monkeypatch.setattr(getpass, "getuser", lambda: "default-on-silence")  # reserved for defaults on silence
    assert setup.operator_name() == "operator"


def test_key_variables_are_names_of_set_variables_of_the_vendor():
    environ = {"ANTHROPIC_API_KEY": "sk-1", "ANTHROPIC_TOKEN": "  ", "ANTHROPIC_MODEL": "opus",
               "OPENAI_API_KEY": "sk-2", "ANTHROPIC_ADMIN_KEY": "sk-3",
               "anthropic_old_key": "sk-4"}  # lower case: not a name ooat.toml accepts
    assert setup.key_variables(fake_manifest("prv.anthropic.api"), environ) == ["ANTHROPIC_ADMIN_KEY",
                                                                                "ANTHROPIC_API_KEY"]


def test_only_a_lone_api_key_variable_is_bound_without_asking():
    def found(*names):
        return setup.Found("prv.anthropic.api", "api", True, "", names)
    assert setup.default_secret_envs([found("ANTHROPIC_ADMIN_KEY", "ANTHROPIC_API_KEY")]) == {
        "prv.anthropic.api": "ANTHROPIC_API_KEY"}
    assert setup.default_secret_envs([found("ANTHROPIC_ADMIN_KEY")]) == {}  # an admin key is never wired silently
    assert setup.default_secret_envs([found("ANTHROPIC_API_KEY", "ANTHROPIC_PROD_API_KEY")]) == {}


def test_found_connectors_report_detection_and_the_key_names_of_api_connectors():
    class Broken(FakeConnector):
        def detect(self):
            raise RuntimeError("plugin bug")

    cli = FakeConnector(fake_manifest("prv.fakecli.subscription_cli", "subscription_cli"))
    broken = Broken(fake_manifest("prv.broken.api"))
    found = setup.found_connectors(Registry([FakeConnector(), cli, broken]), {"FAKE_API_KEY": "sk-1"})
    by_id = {f.id: f for f in found}
    assert by_id["prv.fake.api"] == setup.Found("prv.fake.api", "api", True, "fake connector", ("FAKE_API_KEY",))
    assert by_id["prv.fakecli.subscription_cli"].key_variables == ()
    assert not by_id["prv.broken.api"].available and "plugin bug" in by_id["prv.broken.api"].detail
    assert setup.default_secret_envs(found) == {"prv.fake.api": "FAKE_API_KEY"}


def test_a_bridge_token_may_submit_read_answer_and_rate_up_to_internal(tmp_path):
    ledger = Ledger.open(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    try:
        secret, event = setup.bridge_token(ledger, "Jana", NOW)
    finally:
        ledger.close()
    assert secret and secret not in str(event)
    assert event["body"]["scopes"] == ["submit", "read", "answer", "rate"]
    assert event["body"]["max_data_class"] == "internal" and event["body"]["name"] == "chat"


def test_a_ledger_url_is_shown_without_its_credentials():
    assert setup.shown_url("postgresql://jana:s3cret@db.local:5432/ooat") == "postgresql://***@db.local:5432/ooat"
    assert setup.shown_url("sqlite:///C:/Users/jana/ooat-ledger.sqlite") == "sqlite:///C:/Users/jana/ooat-ledger.sqlite"
