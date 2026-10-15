"""`ooat ask` on a file ledger with a scripted reception model (plan 08a task 10)."""

import io
from datetime import datetime, timezone

import pytest
from reception_fakes import ReceptionModel, decision
from runtime_fakes import acknowledge, decisions, routing_document

from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main
from ooat_core.routing import RoutingPolicy


@pytest.fixture
def env(tmp_path):
    (tmp_path / "ooat.toml").write_text('[ledger]\nurl = "sqlite:///ledger.sqlite"\n', encoding="utf-8")
    model, jev = ReceptionModel([decision("ask", "Který web myslíte?", confidence=0.4,
                                          options=["testdna.cz", "eurogeen.com"])]), decisions()
    ledger = Ledger.open(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    for connector in (model, jev):
        acknowledge(ledger, connector)
    ledger.close()
    return {"config": tmp_path / "ooat.toml", "registry": Registry([model, jev]), "model": model,
            "ledger": f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"}


def ooat(env, *argv):
    stdout = io.StringIO()
    code = main(["--config", str(env["config"]), *argv], stdin=io.StringIO(""), stdout=stdout,
                registry=env["registry"], routing=RoutingPolicy(routing_document()),
                clock=lambda: datetime.now(timezone.utc))
    return code, stdout.getvalue()


def test_ask_prints_the_reply_and_its_numbered_options(env):
    code, out = ooat(env, "ask", "--project", "docs", "--operator", "Martin", "Oprav", "to.")
    assert code == 0 and out.startswith("Který web myslíte?\n")
    assert "  1. testdna.cz\n  2. eurogeen.com\n" in out
    ledger = Ledger.open(env["ledger"])
    message = ledger.events(types=["CONVERSATION_MESSAGE"])[0]["body"]
    ledger.close()
    assert message["channel"] == "cli" and message["text"] == "Oprav to."


def test_ask_prints_the_task_it_started(env):
    env["model"].replies = [decision("task", "Dělám na tom.")]
    code, out = ooat(env, "ask", "--project", "docs", "--operator", "Martin", "Změň titulek.")
    assert code == 0 and "Task tsk_" in out and "ooat task run tsk_" in out


def test_ask_refuses_a_project_that_is_not_a_slug(env):
    code, out = ooat(env, "ask", "--project", "Not A Slug", "--operator", "Martin", "Ahoj.")
    assert code == 1 and out.startswith("Refused:")
