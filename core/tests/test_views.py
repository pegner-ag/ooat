"""The API's views with a reader's data-class cap (design 05 §6)."""

import json

from runtime_fakes import ScriptedModel
from test_runtime import Setup

from ooat_core.connectors import ConnectorError
from ooat_core.hil import open_requests
from ooat_core.rating import CHOICE_OPTIONS
from ooat_core.views import STUB_TEXT, by_task, hil_view, rating_queue, task_class, task_detail, task_summary, \
    timeline, within

PERSONAL_GOAL = "Odpověz panu Novákovi na jan.novak@example.cz ohledně smlouvy."


def classes(setup):
    tasks = by_task(setup.ledger.events())
    return tasks, {task: task_class(events, lambda ref: setup.ledger.artifact(ref)["data_class"])
                   for task, events in tasks.items()}


def test_the_cap_orders_the_classes():
    assert within("internal", "internal") and within("public", "internal") and within("personal", None)
    assert not within("client_confidential", "internal") and not within("special_category", "personal")


def test_a_personal_task_is_a_stub_above_an_internal_cap_but_its_state_and_costs_stay(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.runtime.submit(operator="operator", goal=PERSONAL_GOAL, project="client-x")  # no criteria: asks
    setup.runtime.run(task)
    tasks, found = classes(setup)
    assert found[task] == "personal"  # raised by the pre-scan
    summary = task_summary(task, tasks[task], found[task], "internal")
    assert summary["goal"] == {"redacted": STUB_TEXT, "link": f"/tasks/{task}"} and summary["project"] is None
    assert summary["state"] == "CLARIFYING" and "cost_usd" in summary and summary["data_class"] == "personal"
    detail = task_detail(task, tasks[task], found[task], "internal", setup.ledger.artifact, open_requests(setup.ledger))
    question = detail["questions"][0]
    assert question["question"]["redacted"] == STUB_TEXT and question["deadline"]
    assert all(option["label"]["redacted"] == STUB_TEXT for option in question["options"])
    events = timeline(tasks[task], found[task], "internal")
    assert all(e["body"]["redacted"] == STUB_TEXT for e in events) and events[0]["type"] == "TASK_SUBMITTED"
    assert "novak" not in json.dumps([summary, detail, events]).lower()
    assert task_summary(task, tasks[task], found[task], None)["goal"] == PERSONAL_GOAL  # the web app sees it


def test_an_attachment_above_the_cap_raises_the_task_and_is_not_readable(tmp_path):
    setup = Setup(tmp_path, classes=("public", "internal", "personal"))
    task = setup.submit(files=[b"Kontakt: jan.novak@example.cz"])
    setup.runtime.run(task)
    tasks, found = classes(setup)
    assert found[task] == "personal"
    detail = task_detail(task, tasks[task], found[task], "internal", setup.ledger.artifact, [])
    attachment = next(a for a in detail["artifacts"] if a["type"] == "attachment")
    assert attachment["untrusted"] and not attachment["readable"]
    assert detail["result"]["summary"]["redacted"] == STUB_TEXT and detail["result"]["cost"]


def test_an_internal_task_is_shown_whole_and_the_timeline_follows_a_cursor(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(project="docs")
    setup.runtime.run(task)
    tasks, found = classes(setup)
    summary = task_summary(task, tasks[task], found[task], "internal")
    assert summary["goal"] == "Shrň smlouvu pro jednatele." and summary["project"] == "docs"
    events = timeline(tasks[task], found[task], "internal")
    later = timeline(tasks[task], found[task], "internal", after=events[2]["id"])
    assert [e["id"] for e in later] == [e["id"] for e in events[3:]]


def test_the_rating_queue_holds_closed_unrated_tasks_with_their_decisions(tmp_path):
    setup = Setup(tmp_path)  # no connector for personal data: that task closes at the Gate
    plain = setup.submit()
    personal = setup.runtime.submit(operator="operator", goal=PERSONAL_GOAL, acceptance=["Odpověď je zdvořilá."])
    for task in (plain, personal):
        assert setup.runtime.run(task).state.startswith("CLOSED")
    tasks, found = classes(setup)
    queue = {entry["task"]: entry for entry in rating_queue(tasks, found, "internal")}
    assert set(queue) == {plain, personal}
    assert [d["question"] for d in queue[plain]["decisions"]][:1] == ["a1.1"]
    assert queue[personal]["goal"]["redacted"] == STUB_TEXT
    request = hil_view({"id": "evt_x", "task": plain, "ts": "t", "body": {
        "question": "Q?", "deadline": "d", "blocking": True, "recommended": "a", "default_on_silence": "b",
        "options": [{"id": "a", "label": "A", "cost_usd": 0.0}, {"id": "b", "label": "B", "cost_usd": 0.0,
                                                                "acts": False}]}}, "internal", "internal")
    assert request["question"] == "Q?" and request["options"][1]["acts"] is False


def test_a_task_paused_by_a_provider_failure_says_when_it_is_tried_again(tmp_path):
    setup = Setup(tmp_path, model=ScriptedModel(outages={("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529")}))
    task = setup.submit()
    setup.runtime.run(task)
    tasks, found = classes(setup)
    summary = task_summary(task, tasks[task], found[task], None)
    assert summary["state"] == "RUNNING" and summary["resume_after"].endswith("Z")
    setup.runtime.run(task)  # the provider is back
    tasks, found = classes(setup)
    assert task_summary(task, tasks[task], found[task], None)["resume_after"] is None


def test_an_attachment_is_listed_with_its_file_name_within_the_cap(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(files=[b"Draft of the release notes."], file_names=["notes.txt"])
    setup.runtime.run(task)
    tasks, found = classes(setup)
    detail = task_detail(task, tasks[task], found[task], None, setup.ledger.artifact, [])
    attachment = next(a for a in detail["artifacts"] if a["type"] == "attachment")
    assert attachment["name"] == "notes.txt"
    assert all(a["name"] is None for a in detail["artifacts"] if a["type"] != "attachment")


def test_a_choice_decision_in_the_rating_queue_lists_what_it_may_be_corrected_to(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    tasks, found = classes(setup)
    decisions = {d["question"]: d for d in rating_queue(tasks, found, None)[0]["decisions"]}
    assert decisions["a5"]["options"] == sorted(CHOICE_OPTIONS["a5"])
    assert decisions["a10"]["options"] == sorted(CHOICE_OPTIONS["a10"])
    assert decisions["a1.1"]["options"] is None  # yes/no: corrected to the other answer


# The workspace (plan 07c) ----------------------------------------------------------------------------------------

from runtime_fakes import WorkspaceModel  # noqa: E402
from test_runtime_workspace import EDIT, READ, Setup as ProjectSetup  # noqa: E402

from ooat_core.views import stub, workspace_view  # noqa: E402


def test_the_workspace_view_lists_what_the_worker_changed_and_whether_it_can_be_reverted(tmp_path):
    setup = ProjectSetup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    view = workspace_view(setup.ledger.events(task=task), visible=True)
    assert view["write"] is True and view["folders"] == ["Bots"]
    assert view["files"] == [{"path": "Bots/src/bot.py", "kind": "changed", "added": 1, "removed": 1}]
    assert view["diff"] and view["revertable"] is True and view["reverted"] is None and view["limit"] is False
    setup.runtime.revert(task, operator="Martin", channel="web")
    view = workspace_view(setup.ledger.events(task=task), visible=True)
    assert view["revertable"] is False and view["reverted"]["restored"] == ["Bots/src/bot.py"]
    assert view["reverted"]["by"] == "Martin"


def test_above_the_cap_any_task_is_a_stub_and_a_text_task_has_no_workspace(tmp_path):
    setup = ProjectSetup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    text_task = setup.runtime.submit(operator="Martin", goal="Shrň smlouvu.", acceptance=["Má 3 věty."], project="docs")
    assert workspace_view(setup.ledger.events(task=task), visible=False) == stub(task)
    assert workspace_view(setup.ledger.events(task=text_task), visible=False) == stub(text_task)  # tells nothing
    assert workspace_view(setup.ledger.events(task=text_task), visible=True) is None


def test_a_task_that_only_read_or_waits_at_its_limit_cannot_be_reverted(tmp_path):
    setup = ProjectSetup(tmp_path, model=WorkspaceModel([[READ]]))
    task = setup.submit()
    setup.runtime.run(task)
    view = workspace_view(setup.ledger.events(task=task), visible=True)
    assert view["files"] == [] and view["diff"] is None and view["revertable"] is False
    waiting = ProjectSetup(tmp_path / "limit", model=WorkspaceModel([EDIT + [READ]]), max_operations=2)
    task = waiting.submit()
    assert waiting.runtime.run(task).state == "HIL_WAIT"
    view = workspace_view(waiting.ledger.events(task=task), visible=True)
    assert view["limit"] is True and view["files"] and view["revertable"] is False  # revert goes via its question
