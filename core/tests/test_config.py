import pytest

from ooat_core.config import Config, load_config, parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.secrets import REDACTED, SecretResolver

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
