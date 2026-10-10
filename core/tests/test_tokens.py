"""Operator API tokens and `ooat tokens` (design 05 §6, ADR 0016)."""

import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from ooat_core import tokens
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def ledger():
    led = Ledger.open("sqlite:///:memory:")
    yield led
    led.close()


def issue(ledger, **extra):
    return tokens.issue(ledger, **{"operator": "operator", "name": "telegram", "scopes": ["submit", "read"],
                                   "now": NOW, **extra})


def test_a_token_is_shown_once_and_only_its_hash_is_recorded(ledger):
    secret, event = issue(ledger)
    assert secret.startswith("ooat_") and len(secret) >= 47  # 32 random bytes, URL-safe
    stored = json.dumps(ledger.events())
    assert secret not in stored and secret[5:] not in stored
    body = event["body"]
    assert event["task"] is None and event["actor"] == {"kind": "hil", "id": "operator"}
    assert body["max_data_class"] == "internal" and body["expires"] == "2027-01-08T09:00:00Z"
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW).operator == "operator"


def test_a_wrong_expired_or_revoked_token_does_not_authenticate(ledger):
    secret, event = issue(ledger, days=1)
    events = ledger.events(types=tokens.EVENTS)
    assert tokens.authenticate(events, secret[:-1] + ("A" if secret[-1] != "A" else "B"), NOW) is None
    assert tokens.authenticate(events, "Bearer " + secret, NOW) is None
    assert tokens.authenticate(events, secret, NOW + timedelta(days=1)) is None
    for reason in ("", "   "):  # an emergency revoke still says why
        with pytest.raises(ValueError, match="reason is required"):
            tokens.revoke(ledger, operator="second-operator", token_id=event["body"]["token"], reason=reason)
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW).operator == "operator"
    revoked = tokens.revoke(ledger, operator="second-operator", token_id=event["body"]["token"],
                            reason=" leaked in a chat log ")  # any operator may revoke any token
    assert revoked["actor"] == {"kind": "hil", "id": "second-operator"}
    assert revoked["body"] == {"token": event["body"]["token"], "operator": "second-operator",
                               "reason": "leaked in a chat log"}
    assert tokens.authenticate(ledger.events(types=tokens.EVENTS), secret, NOW) is None
    with pytest.raises(ValueError, match="already revoked"):
        tokens.revoke(ledger, operator="operator", token_id=event["body"]["token"], reason="again")


@pytest.mark.parametrize("extra, message", [
    ({"name": "Telegram Bot"}, "token name"),
    ({"scopes": ["admin"]}, "unknown"),
    ({"scopes": []}, "scopes are"),
    ({"max_data_class": "special_category"}, "never leaves"),
    ({"max_data_class": "personal"}, "responsibility"),
    ({"days": 400}, "1 to 365 days"),
    ({"operator": "default-on-silence"}, "reserved"),
])
def test_mistakes_are_refused_and_nothing_is_written(ledger, extra, message):
    with pytest.raises(ValueError, match=message):
        issue(ledger, **extra)
    assert ledger.events() == []


def test_a_cap_above_internal_records_the_responsibility_statement(ledger):
    _, event = issue(ledger, max_data_class="client_confidential", responsibility=True)
    assert event["body"]["responsibility"] == {"confirmed_on": "2026-10-10"}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "ooat.toml"
    path.write_text('[ledger]\nurl = "sqlite:///ledger.sqlite"\n', encoding="utf-8")
    return path


def ooat(config, *argv, answers=""):
    stdout = io.StringIO()
    code = main(["--config", str(config), *argv], stdin=io.StringIO(answers), stdout=stdout, clock=lambda: NOW)
    return code, stdout.getvalue()


def test_create_list_and_revoke_from_the_command_line(config):
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "telegram",
                     "--scopes", "submit,read,answer,rate")
    assert code == 0 and "shown only now" in out
    secret = next(line.strip() for line in out.splitlines() if line.strip().startswith("ooat_"))
    token_id = out.split("Token ", 1)[1].split(" ", 1)[0]
    code, listed = ooat(config, "tokens", "list")
    assert code == 0 and token_id in listed and "[active]" in listed and secret not in listed
    code, out = ooat(config, "tokens", "revoke", token_id, "--operator", "operator", "--reason", "the bot moved")
    assert code == 0 and "[revoked]" in ooat(config, "tokens", "list")[1]


def test_a_personal_cap_asks_for_the_responsibility_and_no_means_no_token(config):
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "crm", "--scopes", "read",
                     "--max-data-class", "personal", answers="no\n")
    assert code == 1 and "No token was created" in out and "ooat_" not in out
    assert ooat(config, "tokens", "list")[1] == "No tokens.\n"
    code, out = ooat(config, "tokens", "create", "--operator", "operator", "--name", "crm", "--scopes", "read",
                     "--max-data-class", "personal", answers="yes\n")
    assert code == 0 and "data up to personal" in out
