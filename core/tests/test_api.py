"""`ooat serve` endpoints end to end on a file ledger with fake connectors (design 05 §5, §6, §11)."""

import base64
import json

import pytest
from api_fakes import CRITERIA, PERSONAL_GOAL, Served

from ooat_core.ledger import new_event


def get(served, path, headers):
    response = served.client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_submit_answer_and_rate_through_the_api(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    submitted = served.submit(bot, acceptance=[])  # no criteria: the Gate asks (rule A1)
    task = submitted["task"]
    assert submitted["state"] == "SUBMITTED"
    assert served.run() == [task]
    (question,) = get(served, "/api/v1/hil", bot)["requests"]
    assert question["task"] == task and question["recommended"] and question["deadline"]
    answered = served.client.post(f"/api/v1/hil/{question['request']}/answer", headers=bot,
                                  json={"text": CRITERIA[0]})
    assert answered.status_code == 202
    served.run()
    detail = get(served, f"/api/v1/tasks/{task}", bot)
    assert detail["state"] == "CLOSED_DONE" and detail["result"]["cost"]["contracts_usd"] > 0
    (document,) = detail["result"]["artifacts"]
    shown = served.client.get(f"/api/v1/artifacts/{document}", headers=bot)
    assert shown.text == served.model.documents[0] and shown.headers["content-type"] == "text/plain; charset=utf-8"
    (entry,) = get(served, "/api/v1/ratings/queue", bot)["tasks"]
    decisions = [{"event": d["event"], "question": d["question"], "verdict": "confirmed"} for d in entry["decisions"]]
    rated = served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot,
                               json={"accepted": True, "value_class": "B", "decisions": decisions})
    assert rated.status_code == 201 and rated.json()["decisions"] == len(decisions)
    again = served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot, json={"accepted": True, "value_class": "B"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_RATED"
    assert get(served, "/api/v1/ratings/queue", bot)["tasks"] == []
    usage = get(served, "/api/v1/stats?period=7d&group=connector", bot)
    assert {g["key"] for g in usage["groups"]} == {"prv.fake.api", "prv.fakejev.api"}
    assert usage["tasks"]["accepted"] == 1 and usage["hil"]["answered"] == 1
    with served.ledger() as ledger:
        events = ledger.events(task=task)
    channel = submitted_channel = next(e for e in events if e["type"] == "TASK_SUBMITTED")["body"]["channel"]
    assert channel.startswith("token:tok_")
    for kind in ("HIL_RESPONSE", "TASK_RATED"):
        assert next(e for e in events if e["type"] == kind)["body"]["channel"] == submitted_channel
    assert all(e["actor"]["id"] == "operator" for e in events if e["actor"]["kind"] == "hil")


def test_a_repeated_idempotency_key_returns_the_first_task_also_after_a_restart(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    first = served.client.post("/api/v1/tasks", headers={**bot, "Idempotency-Key": "chat-1:msg-7"},
                               json={"project": "docs", "goal": "Shrň smlouvu."}).json()["task"]
    restarted = Served(tmp_path)  # a new server process on the same ledger
    again = restarted.client.post("/api/v1/tasks", headers={**bot, "Idempotency-Key": "chat-1:msg-7"},
                                  json={"project": "docs", "goal": "Shrň smlouvu."})
    assert again.status_code == 202 and again.json()["task"] == first
    with served.ledger() as ledger:
        assert len(ledger.events(types=["TASK_SUBMITTED"])) == 1


def test_a_second_answer_is_a_conflict(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    served.submit(bot, acceptance=[])
    served.run()
    (question,) = get(served, "/api/v1/hil", bot)["requests"]
    path = f"/api/v1/hil/{question['request']}/answer"
    assert served.client.post(path, headers=bot, json={"choice": "do_not_run"}).status_code == 202
    second = served.client.post(path, headers=bot, json={"choice": "run_as_is"})
    assert second.status_code == 409 and second.json()["error"]["code"] == "ALREADY_ANSWERED"


def test_cancel_closes_a_waiting_task_through_the_runner(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=[])["task"]
    served.run()
    cancelled = served.client.post(f"/api/v1/tasks/{task}/cancel", headers=bot)
    assert cancelled.status_code == 202 and cancelled.json()["cancel"] == "requested"
    served.run()
    assert get(served, f"/api/v1/tasks/{task}", bot)["state"] == "CANCELLED"
    late = served.client.post(f"/api/v1/tasks/{task}/cancel", headers=bot)
    assert late.status_code == 409 and late.json()["error"]["code"] == "NOT_OPEN"


def test_the_timeline_follows_a_cursor_and_streams_until_the_task_is_closed(tmp_path):
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=CRITERIA)["task"]
    served.run()
    events = get(served, f"/api/v1/tasks/{task}/events", bot)["events"]
    assert events[0]["type"] == "TASK_SUBMITTED" and events[-1]["type"] == "TASK_CLOSED"
    later = get(served, f"/api/v1/tasks/{task}/events?after={events[2]['id']}", bot)
    assert [e["id"] for e in later["events"]] == [e["id"] for e in events[3:]]
    with served.client.stream("GET", f"/api/v1/tasks/{task}/events", headers={**bot, "Accept": "text/event-stream",
                                                                                "Last-Event-ID": events[-3]["id"]}) \
            as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in stream.iter_lines() if line.startswith("event: ")]
    assert lines == [f"event: {e['type']}" for e in events[-2:]]  # then the stream ends: the task is closed
    bad = served.client.get(f"/api/v1/tasks/{task}/events?after=evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", headers=bot)
    assert bad.status_code == 400


def test_a_token_revoked_while_its_stream_is_open_ends_the_stream_at_the_next_poll(tmp_path, monkeypatch):
    from ooat_core import endpoints, tokens

    from starlette.requests import Request

    from ooat_core.api import principal, scope

    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.01)
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=[])["task"]
    served.run()  # waits for a clarification: the stream stays open
    # The test client buffers a whole streamed body, so the stream's generator is driven here, step by step, with
    # the same re-check the endpoint gives it.
    request = Request({"type": "http", "method": "GET", "path": "/", "app": served.app, "query_string": b"",
                       "headers": [(b"authorization", bot["Authorization"].encode())]})
    stream = endpoints._stream(served.server, task, None, lambda: scope("read")(principal(request)))
    seen = []
    for chunk in stream:
        seen.append(chunk.split("\n", 2)[1] if chunk.startswith("id: ") else chunk.split("\n", 1)[0])
        if seen[-1] == "event: HIL_REQUEST":  # the timeline so far has arrived; now the token leaks
            with served.ledger() as ledger:
                (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
                tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
    assert seen[0] == "event: TASK_SUBMITTED" and seen[-1] == "event: UNAUTHENTICATED"  # and the stream ended


def test_the_documents_of_two_attempts_have_a_diff_and_the_list_filters(tmp_path):
    from runtime_fakes import ScriptedModel, decisions

    served = Served(tmp_path, model=ScriptedModel(["# Shrnutí\n\nPříliš dlouhé.\n", "# Shrnutí\n\nKrátké.\n"]),
                    jev=decisions(met=[False, True]))  # the first document misses its criterion: a second attempt
    bot = served.token()
    task = served.submit(bot, acceptance=CRITERIA)["task"]
    other = served.submit(bot, project="sales", acceptance=CRITERIA)["task"]
    served.run()
    first, second = [a["ref"] for a in get(served, f"/api/v1/tasks/{task}", bot)["artifacts"]]
    diff = served.client.get(f"/api/v1/artifacts/{second}/diff?against={first}", headers=bot)
    assert diff.status_code == 200 and "-Příliš dlouhé." in diff.text and "+Krátké." in diff.text
    foreign = get(served, f"/api/v1/tasks/{other}", bot)["result"]["artifacts"][0]
    assert served.client.get(f"/api/v1/artifacts/{second}/diff?against={foreign}", headers=bot).status_code == 400
    listed = get(served, "/api/v1/tasks?project=docs&state=CLOSED_DONE", bot)["tasks"]
    assert [t["task"] for t in listed] == [task]
    page = get(served, "/api/v1/tasks?limit=1", bot)
    assert [t["task"] for t in page["tasks"]] == [other] and page["next"] == other
    assert [t["task"] for t in get(served, f"/api/v1/tasks?after={other}", bot)["tasks"]] == [task]


def test_an_r3_request_is_refused_on_the_web_and_for_a_token(tmp_path):
    served = Served(tmp_path)
    bot, web = served.token(), served.login()
    task = served.submit(bot, acceptance=[])["task"]
    with served.ledger() as ledger:
        request = ledger.append(new_event("HIL_REQUEST", task=task, actor={"kind": "system", "id": "ooat-runtime"},
                                          body={"question": "Odeslat nabídku?", "risk_class": "R3", "options": [
                                              {"id": "send", "label": "Odeslat", "cost_usd": 0.0},
                                              {"id": "hold", "label": "Ne", "cost_usd": 0.0, "acts": False}],
                                              "recommended": "send", "default_on_silence": "hold",
                                              "deadline": "2099-01-01T00:00:00Z", "blocking": True, "evidence": []}))
    for headers in (web, bot):
        response = served.client.post(f"/api/v1/hil/{request['id']}/answer", headers=headers, json={"choice": "hold"})
        assert response.status_code == 403 and response.json()["error"]["code"] == "R3_NEEDS_BOUND_IDENTITY"


PERSONAL_ROUTE = ("public", "internal", "personal")  # the operator enabled the fake model for personal data


def personal_task(served, web):
    """A closed task with personal data in its goal and its attachment, submitted and cancelled in the web app."""
    attachment = base64.b64encode("Kontakt: jan.novak@example.cz".encode()).decode()
    task = served.submit(web, goal=PERSONAL_GOAL, project="client-x", data_class="personal",
                         attachments=[{"name": "kontakt.txt", "content_base64": attachment}])["task"]
    served.run()
    assert served.client.post(f"/api/v1/tasks/{task}/cancel", headers=web).status_code == 202
    served.run()
    return task


def test_content_above_a_tokens_cap_is_a_stub_on_every_read_endpoint(tmp_path):
    served = Served(tmp_path, classes=PERSONAL_ROUTE)
    web, bot = served.login(), served.token(cap="internal")
    task = personal_task(served, web)
    waiting = served.submit(web, goal=PERSONAL_GOAL, project="client-x", acceptance=[])["task"]
    served.run()
    detail = get(served, f"/api/v1/tasks/{task}", bot)
    attachment = next(a["ref"] for a in detail["artifacts"] if a["type"] == "attachment")
    responses = {
        "list": get(served, "/api/v1/tasks", bot), "detail": detail,
        "waiting": get(served, f"/api/v1/tasks/{waiting}", bot),
        "events": get(served, f"/api/v1/tasks/{task}/events", bot),
        "hil": get(served, "/api/v1/hil", bot), "ratings": get(served, "/api/v1/ratings/queue", bot),
        "artifact": get(served, f"/api/v1/artifacts/{attachment}", bot),
        "stats": get(served, "/api/v1/stats?group=project&period=all", bot),
    }
    for name, body in responses.items():
        text = json.dumps(body, ensure_ascii=False).lower()
        assert "novak" not in text and "client-x" not in text, name
    assert detail["state"] == "CANCELLED" and detail["goal"]["redacted"]  # the state and the costs stay visible
    assert responses["hil"]["requests"][0]["question"]["redacted"] and responses["artifact"]["redacted"]
    assert {g["key"] for g in responses["stats"]["groups"]} <= {"(other)"}  # never the project name
    assert "novak" in json.dumps(get(served, f"/api/v1/tasks/{task}", {})).lower()  # the web session sees it


def test_writes_on_a_task_above_a_tokens_cap_are_refused(tmp_path):
    served = Served(tmp_path, classes=PERSONAL_ROUTE)
    web, bot = served.login(), served.token(cap="internal")
    task = personal_task(served, web)
    waiting = served.submit(web, goal=PERSONAL_GOAL, project="client-x", acceptance=[])["task"]
    served.run()
    (question,) = get(served, "/api/v1/hil", web)["requests"]
    attempts = [served.client.post(f"/api/v1/hil/{question['request']}/answer", headers=bot, json={"choice": "clarify",
                                                                                                    "text": "x"}),
                served.client.post(f"/api/v1/tasks/{task}/rating", headers=bot,
                                   json={"accepted": False, "value_class": "C"}),
                served.client.post(f"/api/v1/tasks/{waiting}/cancel", headers=bot),
                served.client.post("/api/v1/tasks", headers=bot,
                                   json={"project": "docs", "goal": "x", "data_class": "client_confidential"})]
    for response in attempts:
        assert response.status_code == 403 and response.json()["error"]["code"] == "DATA_CLASS_ABOVE_TOKEN"


def test_connectors_need_their_scope_and_a_typed_confirmation(tmp_path):
    served = Served(tmp_path)
    web, bot = served.login(), served.token()
    assert served.client.get("/api/v1/connectors", headers=bot).status_code == 403
    listed = get(served, "/api/v1/connectors", web)["connectors"]
    assert {c["id"] for c in listed} == {"prv.fake.api", "prv.fakejev.api"}
    card = get(served, "/api/v1/connectors/prv.fake.api/card", web)["card"]
    assert card.startswith("Connection consequences: prv.fake.api")
    body = {"classes": ["public"], "automation": True, "confirm": "prv.fake"}
    assert served.client.post("/api/v1/connectors/prv.fake.api/enable", headers=web, json=body).status_code == 400
    enabled = served.client.post("/api/v1/connectors/prv.fake.api/enable", headers=web,
                                 json={**body, "confirm": "prv.fake.api"})
    assert enabled.status_code == 201
    disabled = served.client.post("/api/v1/connectors/prv.fake.api/disable", headers=web, json={"reason": "trial"})
    assert disabled.status_code == 201
    with served.ledger() as ledger:
        state = ledger.events(types=["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"])[-2:]
    assert [e["body"]["channel"] for e in state] == ["web", "web"]
    assert all(e["actor"] == {"kind": "hil", "id": "operator"} for e in state)


def test_errors_are_typed_and_never_echo_an_attachment(tmp_path):
    served = Served(tmp_path)
    token = served.token()
    unknown = served.client.get("/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7", headers=token)
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "NOT_FOUND"
    secret = "VERY-SECRET-ATTACHMENT-CONTENT"
    invalid = served.client.post("/api/v1/tasks", headers=token, json={
        "project": "Docs With Spaces", "goal": "x", "attachments": [{"name": "a.txt", "content_base64": secret}]})
    assert invalid.status_code == 400 and invalid.json()["error"]["code"] == "INVALID" and secret not in invalid.text
    for content, name in (("%%%", "not base64"), ("AAEC", "binary")):
        response = served.client.post("/api/v1/tasks", headers=token, json={
            "project": "docs", "goal": "x", "attachments": [{"name": "a.txt", "content_base64": content}]})
        assert response.status_code == 400, name
    bad_key = served.client.post("/api/v1/tasks", headers={**token, "Idempotency-Key": "a b"},
                                 json={"project": "docs", "goal": "x"})
    assert bad_key.status_code == 400
    with served.ledger() as ledger:
        assert ledger.events(types=["TASK_SUBMITTED"]) == []


def test_a_ledger_locked_past_the_busy_timeout_answers_503_and_writes_nothing(tmp_path, monkeypatch):
    import sqlite3

    from ooat_core.backends import sqlite as sqlite_backend

    monkeypatch.setattr(sqlite_backend, "BUSY_TIMEOUT_MS", 100)
    served = Served(tmp_path)
    headers = served.token()
    other = sqlite3.connect(tmp_path / "ledger.sqlite", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # e.g. a long write by another process
    try:
        response = served.client.post("/api/v1/tasks", headers=headers, json={"project": "docs", "goal": "x"})
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert response.status_code == 503 and response.json()["error"]["code"] == "LEDGER_BUSY"
    with served.ledger() as ledger:
        assert ledger.events(types=["TASK_SUBMITTED"]) == []


def test_hooks_are_approved_from_a_web_session_never_with_a_token(tmp_path):
    served = Served(tmp_path)
    web, bot = served.login(), served.token(scopes=("connectors",))
    body = {"confirm": "prv.fake.api", "hooks": []}
    by_token = served.client.post("/api/v1/connectors/prv.fake.api/approve-hooks", headers=bot, json=body)
    assert by_token.status_code == 403 and by_token.json()["error"]["code"] == "SCOPE"
    by_web = served.client.post("/api/v1/connectors/prv.fake.api/approve-hooks", headers=web, json=body)
    assert by_web.status_code == 400 and "no hooks" in by_web.json()["error"]["message"]  # past the channel check


UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
OPEN = {"/login", "/login.js", "/api/v1/login"}


def test_every_endpoint_but_the_sign_in_needs_authentication(tmp_path):
    from ooat_core.api import login_routes, session_routes
    from ooat_core.endpoints import resource_routes

    served = Served(tmp_path)
    routes = [(method, "/api/v1" + route.path) for router in (session_routes(), resource_routes())
              for route in router.routes for method in route.methods]
    routes += [(method, route.path) for route in login_routes().routes for method in route.methods]
    routes = [(method, path) for method, path in routes if path not in OPEN]
    assert len(routes) >= 20
    for method, path in routes:
        url = path.replace("{task}", "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7").replace(
            "{request_id}", "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7").replace("{ref}", "art_01J9ZQ6X9EK3M5N7P9Q1R3S5T7@v1") \
            .replace("{connector_id}", "prv.fake.api")
        headers = {"Origin": served.origin} if method in UNSAFE else {}
        response = served.client.request(method, url, headers=headers, json={} if method in UNSAFE else None)
        assert response.status_code == 401, (method, path, response.status_code)


@pytest.mark.parametrize("scope, method, path", [
    ("read", "GET", "/api/v1/tasks"), ("read", "GET", "/api/v1/hil"), ("read", "GET", "/api/v1/stats"),
    ("submit", "POST", "/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7/cancel"),
    ("answer", "POST", "/api/v1/hil/evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7/answer"),
    ("rate", "POST", "/api/v1/tasks/tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7/rating"),
    ("connectors", "GET", "/api/v1/connectors"),
])
def test_each_endpoint_checks_its_scope(tmp_path, scope, method, path):
    served = Served(tmp_path)
    others = [s for s in ("submit", "read", "answer", "rate", "connectors") if s != scope]
    response = served.client.request(method, path, headers=served.token(scopes=others),
                                     json={"accepted": True, "value_class": "A"} if method == "POST" else None)
    assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"


def test_usage_of_a_project_above_the_tokens_cap_reads_like_an_unknown_project(tmp_path):
    served = Served(tmp_path, classes=PERSONAL_ROUTE)
    web, bot = served.login(), served.token(cap="internal")
    served.submit(web, goal=PERSONAL_GOAL, project="client-x", data_class="personal", acceptance=CRITERIA)
    served.run()  # the worker runs: the project has spend
    hidden = get(served, "/api/v1/stats?period=all&project=client-x", bot)
    unknown = get(served, "/api/v1/stats?period=all&project=no-such-project", bot)
    assert {**hidden, "project": None} == {**unknown, "project": None}  # neither spend nor existence leaks
    seen = get(served, "/api/v1/stats?period=all&project=client-x", {})  # the web session
    assert seen["spend"]["metered_usd"] > 0


def test_an_artifact_no_task_produced_is_not_found(tmp_path):
    from ooat_core.artifacts import ArtifactStore
    from ooat_core.blobs import BlobStore

    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=CRITERIA)["task"]
    with served.ledger() as ledger:
        staged = ArtifactStore(ledger, BlobStore(tmp_path / "blobs")).stage(b"note", artifact_type="markdown_document",
                                                                            data_class="internal")
        ledger.append(new_event("DECISION", task=task, actor={"kind": "system", "id": "ooat-runtime"},
                                refs=[staged.ref], body={"decision": "noted"}), [staged])
    for path in (f"/api/v1/artifacts/{staged.ref}", f"/api/v1/artifacts/{staged.ref}/diff?against={staged.ref}"):
        response = served.client.get(path, headers=served.token(cap="public"))
        assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND", path


def test_a_token_lists_hooks_without_their_text(tmp_path):
    from runtime_fakes import ScriptedModel

    class Hooked(ScriptedModel):
        def hooks(self):
            return [("hooks.json", "a" * 64, '{"env": {"TOKEN": "VERY-SECRET-HOOK-VALUE"}}')]

    served = Served(tmp_path, model=Hooked())
    by_token = get(served, "/api/v1/connectors/prv.fake.api/hooks", served.token(scopes=("connectors",)))
    assert by_token["hooks"] == [{"path": "hooks.json", "sha256": "a" * 64}]  # it may leave for a chat platform
    assert "VERY-SECRET" in get(served, "/api/v1/connectors/prv.fake.api/hooks", served.login())["hooks"][0]["text"]


def test_an_idle_event_stream_returns_to_its_thread_between_polls(tmp_path, monkeypatch):
    import threading

    from ooat_core import endpoints

    monkeypatch.setattr(endpoints, "SSE_POLL_S", 0.01)
    served = Served(tmp_path)
    bot = served.token()
    task = served.submit(bot, acceptance=[])["task"]
    served.run()  # waits for a clarification: nothing new arrives
    stream = endpoints._stream(served.server, task, None, lambda: _reader(served, bot))
    chunks = []

    def pull():
        for _ in range(8):
            chunks.append(next(stream))
    puller = threading.Thread(target=pull, daemon=True)
    puller.start()
    puller.join(5)
    assert not puller.is_alive() and ": keepalive\n\n" in chunks  # a disconnected client is noticed at a poll


def _reader(served, headers):
    from starlette.requests import Request

    from ooat_core.api import principal, scope

    request = Request({"type": "http", "method": "GET", "path": "/", "app": served.app, "query_string": b"",
                       "headers": [(b"authorization", headers["Authorization"].encode())]})
    return scope("read")(principal(request))
