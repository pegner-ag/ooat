"""The Python client (sdk/python) against `ooat serve` on a loopback port, with its runner thread (design 05 §9)."""

import pytest
from api_fakes import CRITERIA, Served, listening, secret

from ooat_client import OoatClient, OoatError
from ooat_core import endpoints, tokens

GOAL = "Shrň smlouvu pro jednatele."


@pytest.fixture(autouse=True)
def fast_stream(monkeypatch):
    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.05)


def test_follow_yields_the_timeline_to_its_end_and_a_closed_task_ends_it_at_once(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        client = OoatClient(url, secret(served.token()), sleep=lambda seconds: pytest.fail("no reconnect"))
        task = client.submit(project="docs", goal=GOAL, acceptance=CRITERIA)
        events = list(client.follow(task))
        assert events[0]["type"] == "TASK_SUBMITTED" and events[-1]["type"] == "TASK_CLOSED"
        assert len({e["id"] for e in events}) == len(events)
        assert list(client.follow(task, after=events[-1]["id"])) == []  # a bot restarted after the close
        detail = client.task(task)
        assert detail["state"] == "CLOSED_DONE"
        (document,) = detail["result"]["artifacts"]
        assert client.artifact(document).content.decode("utf-8") == served.model.documents[0]


def test_a_token_revoked_while_it_follows_a_task_gets_an_error(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        client = OoatClient(url, secret(served.token()))
        task = client.submit(project="docs", goal=GOAL)  # no criteria: the Gate asks, the task waits
        timeline = client.follow(task)
        while next(timeline)["type"] != "HIL_REQUEST":
            pass
        with served.ledger() as ledger:
            (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
            tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
        with pytest.raises(OoatError) as refused:
            next(timeline)
    assert (refused.value.status, refused.value.code) == (401, "UNAUTHENTICATED")


def test_refusals_reach_the_bot_as_typed_errors(tmp_path):
    served = Served(tmp_path, runner=True)
    with listening(served) as url:
        reader = OoatClient(url, secret(served.token(scopes=("submit", "read"))))
        task = reader.submit(project="docs", goal=GOAL, key="chat-1:7")
        assert reader.submit(project="docs", goal=GOAL, key="chat-1:7") == task
        refusals = []
        for call in (lambda: reader.answer("evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", choice="run_as_is"),
                     lambda: reader.submit(project="docs", goal="x", data_class="personal"),
                     lambda: reader.task("tsk_01J9ZQ70A0K3M5N7P9Q1R3S5T7")):
            with pytest.raises(OoatError) as refused:
                call()
            refusals.append((refused.value.status, refused.value.code))
    assert refusals == [(403, "SCOPE"), (403, "DATA_CLASS_ABOVE_TOKEN"), (404, "NOT_FOUND")]
