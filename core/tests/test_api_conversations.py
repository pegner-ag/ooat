"""Conversations and memory in the REST API: messages, the desk's decision, taps, memory, caps (design 08 §8;
plan 08a task 9)."""

import json

from api_fakes import Served, now
from reception_fakes import ReceptionModel, decision

from ooat_core import memory
from ooat_core.config import parse_config
from ooat_core.ids import new_id

FAST = parse_config({"reception": {"batch_seconds": 0}})
PERSONAL_ROUTE = ("public", "internal", "client_confidential", "personal")


def served(tmp_path, *replies, **options):
    return Served(tmp_path, model=ReceptionModel(list(replies) or [decision("answer", "Ano.")]), config=FAST,
                  **options)


def send(s, headers, text="Ahoj.", **body):
    response = s.client.post("/api/v1/conversations/messages", headers=headers,
                             json={"project": "docs", "text": text, **body})
    assert response.status_code == 202, response.text
    return response.json()


def decided(s, headers, conversation):
    s.server.desk.run_due()
    events = s.client.get(f"/api/v1/conversations/{conversation}/events", headers=headers).json()["events"]
    return [e for e in events if e["type"] == "RECEPTION_DECIDED"]


def test_a_message_is_recorded_at_once_and_decided_by_the_desk(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    assert sent["message"].startswith("evt_") and sent["conversation"].startswith("cnv_")
    events = s.client.get(f"/api/v1/conversations/{sent['conversation']}/events", headers=bot).json()
    assert [e["type"] for e in events["events"]] == ["CONVERSATION_MESSAGE"]
    reply = decided(s, bot, sent["conversation"])
    assert len(reply) == 1 and reply[0]["body"]["reply"] == "Ano."
    later = s.client.get(f"/api/v1/conversations/{sent['conversation']}/events", headers=bot,
                         params={"after": events["next"]}).json()["events"]
    assert [e["type"] for e in later] == ["RECEPTION_DECIDED"]


def test_a_message_from_a_token_is_on_its_channel(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    view = s.client.get(f"/api/v1/conversations/{sent['conversation']}", headers=bot).json()
    assert view["channel"].startswith("token:tok_") and view["operator"] == "operator"


def test_a_repeated_idempotency_key_is_the_same_message(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    first = s.client.post("/api/v1/conversations/messages", json={
        "project": "docs", "text": "Ahoj."}, headers={**bot, "Idempotency-Key": "chat:1:7"}).json()
    again = s.client.post("/api/v1/conversations/messages", json={"project": "docs", "text": "Ahoj."},
                          headers={**bot, "Idempotency-Key": "chat:1:7"}).json()
    assert again == first


def test_the_stream_yields_the_decision_and_ends_at_close(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    s.server.desk.run_due()
    s.server.reception().close(sent["conversation"], "operator")
    response = s.client.get(f"/api/v1/conversations/{sent['conversation']}/events",
                            headers={**bot, "Accept": "text/event-stream"})
    kinds = [line.removeprefix("event: ") for line in response.text.splitlines() if line.startswith("event: ")]
    assert kinds == ["CONVERSATION_MESSAGE", "RECEPTION_DECIDED", "CONVERSATION_CLOSED"]


def test_yes_on_a_confirmation_starts_the_task(tmp_path):
    s = served(tmp_path, decision("confirm", "Rozumím tomu jako změnu titulku. Mám začít?", confidence=0.5))
    bot = s.token()
    sent = send(s, bot, "Titulek.")
    assert decided(s, bot, sent["conversation"])[0]["body"]["buttons"] == ["yes", "differently"]
    tapped = s.client.post(f"/api/v1/conversations/{sent['conversation']}/taps", headers=bot, json={"tap": "yes"})
    assert tapped.status_code == 200, tapped.text
    task = tapped.json()["decision"]["body"]["task"]
    assert s.client.get(f"/api/v1/tasks/{task}", headers=bot).json()["state"] == "SUBMITTED"
    assert task in s.server.runner._queue


def test_a_token_without_answer_cannot_tap(tmp_path):
    s = served(tmp_path)
    bot = s.token(scopes=("submit", "read"))
    sent = send(s, bot)
    response = s.client.post(f"/api/v1/conversations/{sent['conversation']}/taps", headers=bot, json={"tap": "yes"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"


def test_a_personal_reply_is_a_stub_for_an_internal_token(tmp_path):
    s = served(tmp_path, decision("answer", "Napíšu panu Novákovi."), classes=PERSONAL_ROUTE)
    bot = s.token(cap="internal")
    sent = send(s, bot, "Napiš panu Novákovi na jan.novak@example.cz.")
    reply = decided(s, bot, sent["conversation"])[0]["body"]
    assert reply["data_class"] == "personal" and reply["reply"]["redacted"]
    message = s.client.get(f"/api/v1/conversations/{sent['conversation']}", headers=bot).json()["events"][0]
    assert "redacted" in message["body"]["text"]
    web = s.login()
    seen = s.client.get(f"/api/v1/conversations/{sent['conversation']}", headers=web).json()
    assert seen["events"][0]["body"]["text"].startswith("Napiš panu")


def test_another_operators_conversation_reads_as_unknown(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    web = s.login(operator="someone else")
    assert s.client.get(f"/api/v1/conversations/{sent['conversation']}", headers=web).status_code == 404
    response = s.client.post(f"/api/v1/conversations/{sent['conversation']}/taps", headers=web, json={"tap": "yes"})
    assert response.status_code == 404


def test_a_conversation_on_a_project_above_the_tokens_cap_is_refused(tmp_path):
    root = tmp_path / "Shop"
    root.mkdir()
    config = parse_config({"reception": {"batch_seconds": 0},
                           "projects": {"shop": {"folders": [str(root)], "data_class": "client_confidential"}}})
    s = Served(tmp_path, model=ReceptionModel(), config=config)
    response = s.client.post("/api/v1/conversations/messages", headers=s.token(cap="internal"),
                             json={"project": "shop", "text": "Ahoj."})
    assert response.status_code == 403 and response.json()["error"]["code"] == "DATA_CLASS_ABOVE_TOKEN"


def noted(s, scope="docs", text="Ceny jsou s DPH.", data_class="internal", kind="fact"):
    with s.ledger() as ledger:
        return memory.note(ledger, s.server.memory, scope=scope, kind=kind, text=text, data_class=data_class,
                           source=new_id("evt"), actor={"kind": "hil", "id": "operator"})


def test_memory_is_listed_within_the_cap(tmp_path):
    s = served(tmp_path, classes=PERSONAL_ROUTE)
    noted(s)
    noted(s, text="Důvěrná cena.", data_class="client_confidential")
    listed = s.client.get("/api/v1/memory/docs", headers=s.token(cap="internal")).json()["items"]
    assert [i["text"] for i in listed] == ["Ceny jsou s DPH."]
    assert len(s.client.get("/api/v1/memory/docs", headers=s.login()).json()["items"]) == 2


def test_a_token_cannot_edit_or_pin_but_can_mark_done_and_forget(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    item, todo = noted(s), noted(s, text="Nastavit DNS.", kind="todo")
    for change in ({"text": "Jinak."}, {"pinned": True}):
        response = s.client.patch(f"/api/v1/memory/docs/{item.id}", headers=bot, json=change)
        assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"
    assert s.client.patch(f"/api/v1/memory/docs/{todo.id}", headers=bot, json={"done": True}).status_code == 200
    assert s.client.delete(f"/api/v1/memory/docs/{item.id}", headers=bot).json()["forgotten"] is True
    assert s.server.memory.read(item.id) is None
    web = s.login()
    other = noted(s)
    assert s.client.patch(f"/api/v1/memory/docs/{other.id}", headers=web, json={"pinned": True}).status_code == 200


def test_forgetting_through_another_scope_or_above_the_cap_is_refused(tmp_path):
    s = served(tmp_path, classes=PERSONAL_ROUTE)
    bot = s.token(cap="internal")
    elsewhere = noted(s, scope="shop")
    assert s.client.delete(f"/api/v1/memory/docs/{elsewhere.id}", headers=bot).status_code == 404
    secret = noted(s, text="Důvěrná cena.", data_class="client_confidential")
    response = s.client.delete(f"/api/v1/memory/docs/{secret.id}", headers=bot)
    assert response.status_code == 403 and s.server.memory.read(secret.id) is not None


def test_a_secret_in_an_edit_is_refused(tmp_path):
    s = served(tmp_path)
    item = noted(s)
    response = s.client.patch(f"/api/v1/memory/docs/{item.id}", headers=s.login(), json={"text": "password=hunter22"})
    assert response.status_code == 400 and response.json()["error"]["code"] == "SECRET_REFUSED"
    assert "hunter22" not in response.text


def test_conversations_are_listed_for_their_operator(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    listed = s.client.get("/api/v1/conversations", headers=bot).json()["conversations"]
    assert [c["conversation"] for c in listed] == [sent["conversation"]]
    assert s.client.get("/api/v1/conversations", headers=s.login(operator="someone else")).json() == {
        "conversations": []}


def test_usage_has_a_reception_row(tmp_path):
    s = served(tmp_path)
    bot = s.token()
    sent = send(s, bot)
    decided(s, bot, sent["conversation"])
    usage = s.client.get("/api/v1/stats", headers=bot).json()
    assert any(g["key"] == "reception" for g in usage["groups"])
    by_project = s.client.get("/api/v1/stats", headers=bot, params={"group": "project", "project": "docs"}).json()
    assert by_project["spend"]["metered_usd"] > 0


def test_the_desk_starts_and_stops_with_the_server(tmp_path):
    from api_fakes import listening, wait_for
    s = Served(tmp_path, model=ReceptionModel([decision("answer", "Ano.")]), config=FAST, runner=True)
    from ooat_client import OoatClient
    from api_fakes import secret
    bot = s.token()
    with listening(s) as url:
        client = OoatClient(url, secret(bot))
        response = client._json("POST", "/conversations/messages", body={"project": "docs", "text": "Ahoj."})
        conversation = response["conversation"]
        wait_for(lambda: [e for e in client._json("GET", f"/conversations/{conversation}/events")["events"]
                          if e["type"] == "RECEPTION_DECIDED"])
    assert json.dumps(now().isoformat())


def test_a_delete_may_go_without_a_length_but_never_with_a_streamed_body(tmp_path):
    s = served(tmp_path)
    item = noted(s)
    url = f"/api/v1/memory/docs/{item.id}"
    response = s.client.request("DELETE", url, headers={**s.token(), "Transfer-Encoding": "chunked"}, content=b"")
    assert response.status_code == 411 and s.server.memory.read(item.id) is not None
    assert s.client.delete(url, headers=s.token()).status_code == 200


def test_projects_lists_the_configured_ones_within_the_cap_and_those_seen(tmp_path):
    for name in ("Docs", "Hr"):
        (tmp_path / name).mkdir()
    config = parse_config({"reception": {"batch_seconds": 0}, "projects": {
        "docs": {"folders": [str(tmp_path / "Docs")]},
        "hr": {"folders": [str(tmp_path / "Hr")], "data_class": "personal"}}})
    s = Served(tmp_path, model=ReceptionModel(), config=config)
    bot = s.token()
    s.client.post("/api/v1/conversations/messages", headers=bot, json={"project": "eshop", "text": "Ahoj."})
    s.client.post("/api/v1/conversations/messages", headers=s.token(), json={"project": "docs", "text": "Ahoj."})
    listed = s.client.get("/api/v1/projects", headers=bot)
    assert listed.json() == {"projects": [
        {"project": "docs", "data_class": "internal", "write": False, "folders": 1},
        {"project": "eshop", "data_class": "internal", "write": False, "folders": 0}]}
    assert str(tmp_path.name) not in listed.text  # names only, never a folder
    other = s.client.get("/api/v1/projects", headers=s.login(operator="someone else")).json()["projects"]
    assert [p["project"] for p in other] == ["docs", "hr"]  # another operator's projects stay theirs


def test_an_item_by_hand_needs_the_web_and_passes_the_secret_scan(tmp_path):
    s = served(tmp_path)
    body = {"kind": "fact", "text": "Ceny jsou s DPH.", "pinned": True}
    refused = s.client.post("/api/v1/memory/docs", headers=s.token(), json=body)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "SCOPE"
    web = s.login()
    made = s.client.post("/api/v1/memory/docs", headers=web, json=body)
    assert made.status_code == 201, made.text
    item = made.json()
    assert item | {"memory": None, "noted": None, "source": None} == {
        "memory": None, "scope": "docs", "kind": "fact", "data_class": "internal", "text": "Ceny jsou s DPH.",
        "pinned": True, "done": False, "noted": None, "source": None, "conversation": None}
    noted_event = next(e for e in s.server.runtime().ledger.events(types=["MEMORY_NOTED"]))
    assert item["source"] == noted_event["id"] and noted_event["actor"] == {"kind": "hil", "id": "operator"}
    assert [i["text"] for i in s.client.get("/api/v1/memory/docs", headers=web).json()["items"]] == [
        "Ceny jsou s DPH."]
    secret = s.client.post("/api/v1/memory/docs", headers=web, json={"kind": "fact", "text": "password=hunter22"})
    assert secret.status_code == 400 and secret.json()["error"]["code"] == "SECRET_REFUSED"
    assert "hunter22" not in secret.text


def test_an_item_by_hand_keeps_to_its_kinds(tmp_path):
    s = served(tmp_path)
    web = s.login()
    for scope_name, kind in (("docs", "summary"), ("operator", "fact"), ("Docs!", "fact")):
        response = s.client.post(f"/api/v1/memory/{scope_name}", headers=web, json={"kind": kind, "text": "Krátce."})
        assert response.status_code == 400, (scope_name, kind, response.text)
    made = s.client.post("/api/v1/memory/operator", headers=web,
                         json={"kind": "preference", "text": "Odpovídej česky."})
    assert made.status_code == 201 and made.json()["scope"] == "operator"
