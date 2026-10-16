import pytest

from ooat_core.config import Config, Project, ReceptionSettings, folder_name, load_config, parse_config
from ooat_core.connectors import ConnectorError
from ooat_core.credentials_env import REDACTED, SecretResolver
from ooat_core.gate import settings_from_config

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


def test_gate_values_and_the_blob_folder_are_read(tmp_path):
    text = ('[ledger]\nurl = "sqlite:///l.sqlite"\nblobs = "blobs"\n'
            '[gate]\ndefault_budget_usd = 0.5\nexpected_output_tokens = 1500\nvalue_usd = { C = 20 }\n')
    (tmp_path / "ooat.toml").write_text(text, encoding="utf-8")
    config = load_config(tmp_path / "ooat.toml")
    assert config.blobs_dir == (tmp_path / "blobs").as_posix()
    assert config.gate == {"default_budget_usd": 0.5, "expected_output_tokens": 1500, "value_usd": {"C": 20}}
    settings = settings_from_config(config)
    assert settings.default_budget_usd == 0.5 and settings.expected_output_tokens == 1500
    assert settings.value_usd == {"A": 1000.0, "B": 300.0, "C": 20.0} and settings.hil_deadline_hours == 48.0


@pytest.mark.parametrize("gate, message", [
    ({"default_budget_usd": 0}, "positive number"),
    ({"expected_output_tokens": 1.5}, "positive whole number"),
    ({"value_usd": {"D": 1}}, "unknown settings"),
    ({"value_usd": {"A": -1}}, "amounts in USD"),
    ({"budget": 1}, "unknown settings"),
])
def test_gate_values_are_checked(gate, message):
    with pytest.raises(ValueError, match=message):
        parse_config({"gate": gate})


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


@pytest.mark.parametrize("gate, ok", [
    ({"retry_prior": 0.4, "critic_prior": 0, "critic_output_tokens": 300, "fallback_tokens_per_question": 600}, True),
    ({"retry_prior": 1.5}, False), ({"critic_prior": -0.1}, False), ({"critic_output_tokens": 0}, False),
    ({"fallback_tokens_per_question": 2.5}, False),
])
def test_estimate_priors_in_gate_are_range_checked(gate, ok):
    from ooat_core.gate import settings_from_config
    if ok:
        settings = settings_from_config(parse_config({"gate": gate}))
        assert settings.retry_prior == 0.4 and settings.critic_prior == 0
    else:
        with pytest.raises(ValueError):
            parse_config({"gate": gate})




def test_projects_map_a_slug_to_folders_with_defaults(tmp_path):
    (tmp_path / "Bots").mkdir()
    config = parse_config({"projects": {"telegrambots": {"folders": [str(tmp_path / "Bots")]}}})
    assert config.projects == {"telegrambots": Project(folders=(str(tmp_path / "Bots"),))}
    project = config.projects["telegrambots"]
    assert (project.write, project.data_class, project.deny) == (False, "internal", ())
    assert (project.max_operations, project.max_write_mb, project.timeout_min) == (300, 5, 30)


def test_a_project_sets_write_class_deny_and_limits(tmp_path):
    config = parse_config({"projects": {"web-shop": {
        "folders": [str(tmp_path / "a"), str(tmp_path / "b")], "write": True, "data_class": "client_confidential",
        "deny": ["src/projects.json*", "logs/**"], "max_operations": 600, "max_write_mb": 12.5, "timeout_min": 45}}})
    project = config.projects["web-shop"]
    assert project.write is True and project.data_class == "client_confidential"
    assert project.deny == ("src/projects.json*", "logs/**")
    assert (project.max_operations, project.max_write_mb, project.timeout_min) == (600, 12.5, 45)


@pytest.mark.parametrize("projects, message", [
    ({"Bad Name": {"folders": ["/x"]}}, "project name"),
    ({"p": {}}, "folders"),
    ({"p": {"folders": []}}, "folders"),
    ({"p": {"folders": ["relative/path"]}}, "absolute"),
    ({"p": {"folders": ["/"]}}, "root"),
    ({"p": {"folders": ["/a/app", "/b/APP"]}}, "same last name"),
    ({"p": {"folders": ["/a"], "write": "yes"}}, "write"),
    ({"p": {"folders": ["/a"], "data_class": "secret"}}, "data_class"),
    ({"p": {"folders": ["/a"], "deny": ["/etc/passwd"]}}, "deny"),
    ({"p": {"folders": ["/a"], "deny": ["../up"]}}, "deny"),
    ({"p": {"folders": ["/a"], "max_operations": 0}}, "max_operations"),
    ({"p": {"folders": ["/a"], "max_write_mb": -1}}, "max_write_mb"),
    ({"p": {"folders": ["/a"], "timeout_min": True}}, "timeout_min"),
    ({"p": {"folders": ["/a"], "password": "hunter2"}}, "unknown settings"),
])
def test_invalid_projects_are_refused_without_echoing_values(projects, message):
    with pytest.raises(ValueError) as info:
        parse_config({"projects": projects})
    assert message in str(info.value) and "hunter2" not in str(info.value)


def test_loading_checks_that_project_folders_exist_and_do_not_nest(tmp_path):
    outer = tmp_path / "outer"
    (outer / "inner").mkdir(parents=True)
    path = tmp_path / "ooat.toml"
    path.write_text(f'[projects.p]\nfolders = ["{(tmp_path / "missing").as_posix()}"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="does not exist"):
        load_config(path)
    path.write_text(f'[projects.p]\nfolders = ["{outer.as_posix()}", "{(outer / "inner").as_posix()}"]\n',
                    encoding="utf-8")
    with pytest.raises(ValueError, match="inside"):
        load_config(path)
    path.write_text(f'[projects.p]\nfolders = ["{outer.as_posix()}"]\n', encoding="utf-8")
    assert load_config(path).projects["p"].folders == (outer.as_posix(),)


def test_the_folder_name_is_the_last_segment_in_either_convention():
    assert folder_name("C:\\DATA_DEVELOPMENT\\TelegramBOTs\\") == "TelegramBOTs"
    assert folder_name("/srv/projects/shop") == "shop"


def test_reception_settings_have_defaults_and_overrides():
    assert parse_config({}).reception == ReceptionSettings()
    settings = parse_config({"reception": {"batch_seconds": 3, "silence_hours": 12, "context_tokens": 2000,
                                           "max_answer_usd": 0.1, "max_answer_operations": 20, "theta": 0.8}})
    assert settings.reception == ReceptionSettings(3, 12, 2000, 0.1, 20, 0.8)


@pytest.mark.parametrize("reception, message", [
    ({"theta": 1.2}, "share from 0 to 1"),
    ({"max_answer_operations": 2.5}, "whole number"),
    ({"context_tokens": 0}, "whole number"),
    ({"batch_seconds": -1}, "batch_seconds"),
    ({"max_answer_usd": "a lot"}, "max_answer_usd"),
    ({"api_key": "hunter2"}, "unknown settings"),
])
def test_invalid_reception_settings_are_refused_without_echoing_values(reception, message):
    with pytest.raises(ValueError) as info:
        parse_config({"reception": reception})
    assert message in str(info.value) and "hunter2" not in str(info.value)


def test_a_zero_batch_window_is_allowed():
    assert parse_config({"reception": {"batch_seconds": 0}}).reception.batch_seconds == 0
