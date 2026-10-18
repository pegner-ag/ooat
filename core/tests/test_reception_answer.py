"""Direct answers that read a project's folders with a read-only grant (design 08 §4; plan 08a task 6)."""

import pytest
from reception_fakes import Desk, ReceptionModel, decision

from ooat_core.config import ReceptionSettings


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "Web"
    root.mkdir()
    (root / "ceny.md").write_text("Cena testu je 2 990 Kč s DPH.\n", encoding="utf-8")
    return {"docs": {"folders": [str(root)], "write": True}}


def reading(*replies, tools=(("read_file", {"path": "Web/ceny.md"}),)):
    return ReceptionModel([decision("answer", "Podívám se do souborů.", needs_files=True), *replies], tools=tools)


def test_an_answer_reads_the_files_and_never_writes(tmp_path, project):
    model = reading("Cena testu je 2 990 Kč s DPH (Web/ceny.md).",
                    tools=(("read_file", {"path": "Web/ceny.md"}),
                           ("edit_file", {"path": "Web/ceny.md", "old": "2 990", "new": "1"})))
    desk = Desk(tmp_path, projects=project, model=model)
    body = desk.ask("Kolik stojí test?")["body"]
    assert body["decision"] == "answer" and body["reply"] == "Cena testu je 2 990 Kč s DPH (Web/ceny.md)."
    assert (tmp_path / "Web" / "ceny.md").read_text(encoding="utf-8") == "Cena testu je 2 990 Kč s DPH.\n"
    decided = desk.events("RECEPTION_DECIDED")
    assert decided[0]["body"]["reading"] is True and decided[0]["body"]["reply"] == "Podívám se do souborů."
    assert decided[1]["cost"]["tier"] == "economy" and decided[1]["body"]["messages"] == decided[0]["body"]["messages"]
    grant = model.calls[1].workspace
    assert grant.write is False and grant.max_operations == 40
    used = desk.events("WORKSPACE_USED")[0]
    assert used["task"] is None and used["body"]["conversation"] == body["conversation"]
    assert used["body"]["by"] == "reception" and used["body"]["write"] is False
    assert used["body"]["read"] == [{"path": "Web/ceny.md", "times": 1}]
    assert used["body"]["refused"][0]["tool"] == "edit_file" and desk.submitted() == []


def test_an_estimate_above_the_cap_makes_no_second_call(tmp_path, project):
    model = reading("Nikdy.")
    desk = Desk(tmp_path, projects=project, model=model, settings=ReceptionSettings(max_answer_usd=0.000001))
    body = desk.ask("Kolik stojí test?")["body"]
    assert len(model.calls) == 1 and body["buttons"] == ["make_task"] and "limit" in body["reply"]
    assert desk.events("WORKSPACE_USED") == []


def test_the_operation_limit_makes_a_partial_answer(tmp_path, project):
    model = reading("Část odpovědi.", tools=[("list_dir", {"path": "Web"})] * 5)
    desk = Desk(tmp_path, projects=project, model=model, settings=ReceptionSettings(max_answer_operations=3))
    body = desk.ask("Projdi všechno.")["body"]
    assert body["reply"].startswith("Část odpovědi.") and "neúplná" in body["reply"]
    assert body["buttons"] == ["make_task"]
    assert desk.events("WORKSPACE_USED")[0]["body"]["limit"]["kind"] == "operations"


def test_make_task_after_a_partial_answer_starts_the_question_as_a_task(tmp_path, project):
    model = reading("Část odpovědi.", tools=[("list_dir", {"path": "Web"})] * 5)
    desk = Desk(tmp_path, projects=project, model=model, settings=ReceptionSettings(max_answer_operations=3))
    body = desk.ask("Projdi všechny stránky a najdi ceny.")["body"]
    desk.reception.tap(body["conversation"], "make_task", operator="operator", channel="web")
    assert desk.submitted()[0]["goal"] == "Projdi všechny stránky a najdi ceny."


def test_a_file_with_personal_data_raises_the_answers_class(tmp_path, project):
    (tmp_path / "Web" / "kontakt.md").write_text("Pište na jan.novak@example.cz.\n", encoding="utf-8")
    model = reading("Kontakt je jan.novak@example.cz.", tools=(("read_file", {"path": "Web/kontakt.md"}),))
    desk = Desk(tmp_path, projects=project, model=model)
    assert desk.ask("Jaký je kontakt?")["body"]["data_class"] == "personal"


def test_an_unmapped_project_is_answered_from_memory_only(tmp_path):
    model = ReceptionModel([decision("answer", "Podle paměti jsou ceny s DPH.", needs_files=True)])
    desk = Desk(tmp_path, model=model)
    body = desk.ask("Jsou ceny s DPH?")["body"]
    assert len(model.calls) == 1 and body["reply"] == "Podle paměti jsou ceny s DPH." and "reading" not in body


def test_without_a_workspace_connector_the_answer_offers_a_task(tmp_path, project):
    model = ReceptionModel([decision("answer", "Podívám se.", needs_files=True)])  # no features.workspace
    desk = Desk(tmp_path, projects=project, model=model)
    body = desk.ask("Kolik stojí test?")["body"]
    assert body["buttons"] == ["make_task"] and "nemohu" in body["reply"] and len(model.calls) == 1


def test_the_project_instructions_are_in_the_context(tmp_path, project):
    (tmp_path / "Web" / "CLAUDE.md").write_text("Ceny vždy s DPH.\n", encoding="utf-8")
    (tmp_path / "Web" / ".env").write_text("SECRET=x\n", encoding="utf-8")
    model = ReceptionModel([decision("answer", "Ano.")])
    desk = Desk(tmp_path, projects=project, model=model)
    desk.ask("Jak uvádíme ceny?")
    assert "Web/CLAUDE.md:\nCeny vždy s DPH." in model.calls[0].prompt and "SECRET" not in model.calls[0].prompt


def test_a_lesson_is_not_offered_with_an_answer_that_reads_files(tmp_path, project):
    lesson = {"kind": "preference", "text": "Ceny uváděj vždy s DPH."}
    model = ReceptionModel([decision("confirm", "Mám začít?", confidence=0.5),
                            decision("answer", "Podívám se do souborů.", needs_files=True, lesson=lesson),
                            "Cena testu je 2 990 Kč s DPH (Web/ceny.md)."],
                           tools=(("read_file", {"path": "Web/ceny.md"}),))
    desk = Desk(tmp_path, projects=project, model=model)
    body = desk.ask("Cena?")["body"]
    desk.reception.tap(body["conversation"], "differently", operator="operator", channel="web", text="S DPH.")
    desk.reception.decide(body["conversation"])
    assert all("lesson" not in e["body"] and "remember" not in e["body"]["buttons"]
               for e in desk.events("RECEPTION_DECIDED"))
