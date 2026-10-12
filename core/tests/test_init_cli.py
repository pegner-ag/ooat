"""`ooat init` (design 05 §10, plan 01c): the setup steps in the terminal."""

import getpass
import io
from datetime import date, datetime, timezone

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core.config import load_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # an ooat.toml in the folder the tests start from must not count


def init(*argv, answers="", connectors=None):
    stdout = io.StringIO()
    registry = Registry(connectors if connectors is not None else [FakeConnector()])
    code = main(["init", *argv], stdin=io.StringIO(answers), stdout=stdout, registry=registry, today=TODAY,
                clock=lambda: NOW)
    return code, stdout.getvalue()


def events(config_path, *types):
    ledger = Ledger.open(load_config(config_path).ledger_url)
    try:
        return ledger.events(types=list(types))
    finally:
        ledger.close()


def test_init_writes_the_config_enables_a_connector_and_shows_a_token_once(tmp_path, monkeypatch, ooat_home):
    monkeypatch.setenv("FAKE_API_KEY", "sk-never-shown")
    cli = FakeConnector(fake_manifest("prv.fakecli.subscription_cli", "subscription_cli"))
    answers = "\n".join([str(tmp_path / "data"),  # data folder
                         "Jana",                   # name
                         "",                       # the key variable of prv.fake.api: the one found
                         "yes", "", "yes", "prv.fake.api",  # enable prv.fake.api: default classes, unattended, confirm
                         "no",                     # not prv.fakecli.subscription_cli
                         "yes"]) + "\n"            # a chat bridge token
    code, out = init(answers=answers, connectors=[FakeConnector(), cli])
    assert code == 0, out
    path = ooat_home / "ooat.toml"
    config = load_config(path)
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'data' / 'ooat-ledger.sqlite').as_posix()}"
    assert config.serve["operator"] == "Jana" and config.connectors == {"prv.fake.api": {"secret_env": "FAKE_API_KEY"}}
    (enabled,) = events(path, "ADAPTER_ACKNOWLEDGED")
    assert enabled["body"]["adapter"] == "prv.fake.api" and enabled["actor"]["id"] == "Jana"
    (token,) = events(path, "OPERATOR_TOKEN_ISSUED")
    assert token["body"]["scopes"] == ["submit", "read", "answer", "rate"]
    assert token["body"]["max_data_class"] == "internal"
    assert out.count("It is shown only now") == 1 and "sk-never-shown" not in out
    assert "FAKE_API_KEY" in out and "ooat serve" in out


def test_init_with_yes_takes_the_defaults_and_enables_nothing(monkeypatch, ooat_home):
    monkeypatch.setattr(getpass, "getuser", lambda: "jana")
    code, out = init("--yes")
    assert code == 0, out
    config = load_config(ooat_home / "ooat.toml")
    assert config.serve["operator"] == "jana"
    assert config.ledger_url == f"sqlite:///{(ooat_home / 'ooat-ledger.sqlite').as_posix()}"
    assert events(ooat_home / "ooat.toml", "ADAPTER_ACKNOWLEDGED", "OPERATOR_TOKEN_ISSUED") == []


def test_init_leaves_an_existing_setup_alone(ooat_home):
    path = ooat_home / "ooat.toml"
    path.write_text('[ledger]\nurl = "sqlite:///mine.sqlite"\n', encoding="utf-8")
    code, out = init("--operator", "Petr", "--yes")
    assert code == 0 and "already set up" in out
    assert path.read_text(encoding="utf-8") == '[ledger]\nurl = "sqlite:///mine.sqlite"\n'


def test_init_cancelled_before_the_config_is_written_writes_nothing(ooat_home):
    code, out = init(answers="")  # the input ends at the first question
    assert code == 1 and "nothing was changed" in out.lower()
    assert not (ooat_home / "ooat.toml").exists()


def test_a_bad_name_is_refused_and_nothing_is_written(tmp_path, ooat_home):
    code, out = init("--data", str(tmp_path / "data"), "--operator", "default-on-silence", "--yes")
    assert code == 1 and "reserved" in out and not (ooat_home / "ooat.toml").exists()


def test_a_relative_data_folder_is_the_one_under_the_current_folder(tmp_path, ooat_home):
    code, out = init("--data", "mydata", "--operator", "Jana", answers="\nno\nno\n")  # no key, enable nothing, no token
    assert code == 0, out
    config = load_config(ooat_home / "ooat.toml")
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'mydata' / 'ooat-ledger.sqlite').as_posix()}"
    assert events(ooat_home / "ooat.toml", "OPERATOR_TOKEN_ISSUED") == []
