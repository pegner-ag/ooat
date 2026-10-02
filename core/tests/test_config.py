import pytest

from ooat_core.config import Config, load_config, parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.credentials_env import REDACTED, SecretResolver

EXAMPLE = """
[ledger]
url = "sqlite:///C:/ooat/ledger.sqlite"

[routing.pin]
workhorse = "prv.anthropic.subscription_cli"

[connectors."prv.anthropic.subscription_cli"]
plan_fee_usd_month = 100
models = { workhorse = "claude-sonnet-5-5" }

[connectors."prv.anthropic.api"]
secret_env = "ANTHROPIC_API_KEY"
"""


def test_example_config_loads(tmp_path):
    path = tmp_path / "ooat.toml"
    path.write_text(EXAMPLE, encoding="utf-8")
    config = load_config(path)
    assert config.ledger_url == "sqlite:///C:/ooat/ledger.sqlite"
    assert config.pins == {"workhorse": "prv.anthropic.subscription_cli"}
    assert config.connectors["prv.anthropic.api"] == {"secret_env": "ANTHROPIC_API_KEY"}
    assert config.connectors["prv.anthropic.subscription_cli"]["models"] == {"workhorse": "claude-sonnet-5-5"}


def test_policy_limits_are_read():
    config = parse_config({"policy": {"blocked_countries": ["CN"], "personal_data_regions": ["eu"]}})
    assert config.blocked_countries == {"CN"} and config.personal_data_regions == {"eu"}
    assert parse_config({}).personal_data_regions is None  # no limit unless the operator sets one


@pytest.mark.parametrize("policy, message", [
    ({"blocked_countries": ["china"]}, "two-letter"),
    ({"blocked_countries": "CN"}, "two-letter"),
    ({"personal_data_regions": ["Europe"]}, "region codes"),
    ({"allow_everything": True}, "unknown settings"),
])
def test_policy_shapes_are_checked(policy, message):
    with pytest.raises(ValueError, match=message):
        parse_config({"policy": policy})


def test_a_relative_ledger_keeps_the_policy(tmp_path):
    (tmp_path / "ooat.toml").write_text('[ledger]\nurl = "sqlite:///l.sqlite"\n[policy]\nblocked_countries = ["CN"]\n',
                                        encoding="utf-8")
    assert load_config(tmp_path / "ooat.toml").blocked_countries == {"CN"}


def test_empty_config_has_defaults():
    assert parse_config({}) == Config()


@pytest.mark.parametrize("data, message", [
    ({"secrets": {}}, "unknown config sections"),
    ({"routing": {"pin": {"turbo": "prv.a.api"}}}, "invalid pin"),
    ({"connectors": {"prv.a.api": {"api_key": "sk-123"}}}, "unknown settings"),
    ({"connectors": {"prv.a.api": {"secret_env": "sk-ant-abc123"}}}, "environment variable"),
    ({"connectors": {"prv.a.api": {"models": {"turbo": "m"}}}}, "models"),
    ({"connectors": {"anthropic": {}}}, "invalid connector id"),
])
def test_config_rejects_unknown_keys_and_pasted_secrets(data, message):
    with pytest.raises(ValueError, match=message):
        parse_config(data)


def test_secret_is_read_from_the_named_variable():
    secrets = SecretResolver(parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}), {"A_KEY": "s3cr3t"})
    assert secrets.get("prv.a.api") == "s3cr3t"


@pytest.mark.parametrize("config, environ", [
    ({}, {}),
    ({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}, {}),
])
def test_missing_secret_makes_the_connector_unavailable(config, environ):
    with pytest.raises(ConnectorError) as info:
        SecretResolver(parse_config(config), environ).get("prv.a.api")
    assert info.value.code == "UNAVAILABLE"


def test_redact_removes_every_configured_secret():
    config = parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}, "prv.b.api": {"secret_env": "B_KEY"}}})
    secrets = SecretResolver(config, {"A_KEY": "sk-long-secret", "B_KEY": "sk-long"})
    assert secrets.redact("failed with sk-long-secret and sk-long") == f"failed with {REDACTED} and {REDACTED}"



def test_secret_pasted_as_a_value_is_rejected_without_echoing_it():
    with pytest.raises(ValueError) as info:
        parse_config({"connectors": {"prv.a.api": "sk-ant-api03-SECRETVALUE"}})
    message = str(info.value)
    assert "SECRETVALUE" not in message and "sk-ant" not in message and "'S'" not in message  # no characters echoed


@pytest.mark.parametrize("data", [
    {"ledger": {"url": "sqlite:///x", "password": "p"}},
    {"routing": {"pin": {}, "fallback": True}},
    {"routing": {"pin": {"workhorse": 7}}},
    {"connectors": {"prv.a.api": {"secret_env": 7}}},
    {"connectors": {"prv.a.api": {"models": {"workhorse": 7}}}},
    {"ledger": "sqlite:///x"},
])
def test_config_shapes_are_checked(data):
    with pytest.raises(ValueError):
        parse_config(data)


def test_secret_with_a_trailing_newline_is_stripped():
    secrets = SecretResolver(parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}), {"A_KEY": "sk-1\r\n"})
    assert secrets.get("prv.a.api") == "sk-1"


def test_secret_with_inner_control_characters_is_refused_without_echoing_it():
    secrets = SecretResolver(parse_config({"connectors": {"prv.a.api": {"secret_env": "A_KEY"}}}), {"A_KEY": "sk-1\nX"})
    with pytest.raises(ConnectorError) as info:
        secrets.get("prv.a.api")
    assert info.value.code == "UNAVAILABLE" and "sk-1" not in info.value.message and "A_KEY" in info.value.message


def test_relative_sqlite_ledger_is_resolved_against_the_config_folder(tmp_path, monkeypatch):
    (tmp_path / "ooat.toml").write_text('[ledger]\nurl = "sqlite:///data/ledger.sqlite"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    config = load_config(tmp_path / "ooat.toml")
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'data' / 'ledger.sqlite').as_posix()}"
    for url in ("sqlite:///:memory:", f"sqlite:///{(tmp_path / 'abs.sqlite').as_posix()}"):
        (tmp_path / "ooat.toml").write_text(f'[ledger]\nurl = "{url}"\n', encoding="utf-8")
        assert load_config(tmp_path / "ooat.toml").ledger_url == url


@pytest.mark.parametrize("url", ["sqlite:///C:/ooat/ledger.sqlite", "sqlite:////var/ooat/ledger.sqlite"])
def test_absolute_paths_of_either_convention_are_kept(tmp_path, url):
    (tmp_path / "ooat.toml").write_text(f'[ledger]\nurl = "{url}"\n', encoding="utf-8")
    assert load_config(tmp_path / "ooat.toml").ledger_url == url
