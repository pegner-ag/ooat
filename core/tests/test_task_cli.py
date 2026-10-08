"""`ooat task` and `ooat hil` end to end on a file ledger with fake connectors (design 04 §8)."""

import io
from datetime import datetime, timezone

import pytest
from runtime_fakes import ScriptedModel, acknowledge, decisions, routing_document

from ooat_core.connectors import ConnectorError
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main
from ooat_core.routing import RoutingPolicy

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path):
    ledger_path = tmp_path / "ledger.sqlite"
    (tmp_path / "ooat.toml").write_text('[ledger]\nurl = "sqlite:///ledger.sqlite"\n', encoding="utf-8")
    model, jev = ScriptedModel(), decisions()
    ledger = Ledger.open(f"sqlite:///{ledger_path.as_posix()}")
    for connector in (model, jev):
        acknowledge(ledger, connector)
    ledger.close()
    return {"config": tmp_path / "ooat.toml", "registry": Registry([model, jev]), "model": model, "dir": tmp_path,
            "ledger": f"sqlite:///{ledger_path.as_posix()}"}


def ooat(env, *argv, answers="", now=NOW):
    stdout = io.StringIO()
    code = main(["--config", str(env["config"]), *argv], stdin=io.StringIO(answers), stdout=stdout,
                registry=env["registry"], routing=RoutingPolicy(routing_document()), clock=lambda: now)
    return code, stdout.getvalue()


def task_id(out):
    return out.split("Submitted ", 1)[1].split(".", 1)[0]


def events(env, task, kind):
    ledger = Ledger.open(env["ledger"])
    found = ledger.events(task=task, types=[kind])
    ledger.close()
    return found


def test_submit_runs_to_a_document_show_prints_it_and_rate_records_the_verdicts(env):
    code, out = ooat(env, "task", "submit", "--operator", "Martin", "--project", "sme-ai",
                     "--goal", "Shrň smlouvu pro jednatele.", "--acceptance", "Shrnutí má nejvýše 300 slov.")
    task = task_id(out)
    assert code == 0 and f"{task}: CLOSED_DONE" in out and "Document: art_" in out
    assert (env["dir"] / "ooat-blobs").is_dir()  # artifacts next to the ledger by default
    code, shown = ooat(env, "task", "show", task)
    assert code == 0 and "TOPOLOGY_DECIDED" in shown and "Cost:" in shown and "estimated" in shown
    assert env["model"].documents[0] in shown
    code, rated = ooat(env, "task", "rate", task, "--operator", "Martin", "--accepted", "yes", "--value", "B",
                       "--confirm-all")
    assert code == 0 and "6 decisions recorded" in rated
    assert {d["verdict"] for d in events(env, task, "TASK_RATED")[0]["body"]["decisions"]} == {"confirmed"}


def test_rating_asks_for_each_decision_when_not_confirming_all(env):
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.")
    task = task_id(out)
    code, rated = ooat(env, "task", "rate", task, "--operator", "Martin", "--accepted", "no", "--value", "C",
                       answers="\n-\ntwo\n\n\n0\n")
    assert code == 0 and "5 decisions recorded" in rated
    verdicts = {d["question"]: d for d in events(env, task, "TASK_RATED")[0]["body"]["decisions"]}
    assert verdicts["a5"] == {"event": verdicts["a5"]["event"], "question": "a5", "verdict": "corrected",
                              "value": "two"}
    assert verdicts["c1"]["value"] == 0 and "a4" not in verdicts


def test_a_question_is_listed_answered_and_the_task_runs_on(env):
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.")
    task = task_id(out)
    assert f"{task}: CLARIFYING" in out and "Answer: ooat hil answer evt_" in out
    request = out.split("Question ", 1)[1].split(" ", 1)[0]
    code, listed = ooat(env, "hil", "list")
    assert code == 0 and request in listed and "do_not_run: Do not run (default on silence)" in listed
    code, answered = ooat(env, "hil", "answer", request, "--operator", "Martin",
                          "--text", "Shrnutí má nejvýše 300 slov.")
    assert code == 0 and f"{task}: CLOSED_DONE" in answered
    assert ooat(env, "hil", "list")[1] == "No open questions.\n"


def test_attachments_are_submitted_as_untrusted_files(env):
    attachment = env["dir"] / "smlouva.txt"
    attachment.write_text("Smlouva o dilu c. 12/2026.", encoding="utf-8")
    code, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň přiloženou smlouvu.",
                     "--acceptance", "Shrnutí má nejvýše 300 slov.", "--file", str(attachment))
    assert code == 0 and "CLOSED_DONE" in out and "Smlouva o dilu" in env["model"].worker_prompts[0]


def test_run_all_moves_every_task_paused_by_a_provider(env):
    env["model"].outages = {("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529")}
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.")
    task = task_id(out)
    assert f"{task}: RUNNING - Paused" in out
    code, resumed = ooat(env, "task", "run", "--all")
    assert code == 0 and f"{task}: CLOSED_DONE" in resumed
    assert ooat(env, "task", "run", "--all")[1] == "No task can move without you.\n"


def test_end_of_input_while_rating_rates_nothing(env):
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.")
    task = task_id(out)
    code, rated = ooat(env, "task", "rate", task, "--operator", "Martin", "--accepted", "yes", "--value", "B",
                       answers="\n")  # one confirmation, then the input ends
    assert code == 1 and "nothing was rated" in rated and events(env, task, "TASK_RATED") == []


def test_ctrl_c_in_a_task_command_says_how_to_go_on(env, monkeypatch):
    import ooat_core.task_cli as task_cli

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(task_cli, "run", interrupted)
    code, out = ooat(env, "task", "run", "--all")
    assert code == 130 and "ooat task run" in out and "nothing was changed" not in out


def test_an_answer_after_the_deadline_is_refused_and_the_default_stands(env):
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.")
    request = out.split("Question ", 1)[1].split(" ", 1)[0]
    later = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    code, answered = ooat(env, "hil", "answer", request, "--operator", "Martin", "--text", "Pozdě.", now=later)
    assert code == 1 and "already answered" in answered


def test_a_missing_artifact_folder_is_reported_without_a_traceback(env):
    import shutil

    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.")
    shutil.rmtree(env["dir"] / "ooat-blobs")
    code, shown = ooat(env, "task", "show", task_id(out))
    assert code == 1 and "artifact" in shown.lower() and "Traceback" not in shown


def test_run_all_goes_on_when_one_task_is_refused(env, monkeypatch):
    _, first = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "A.", "--no-run")
    _, second = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "B.", "--acceptance", "x", "--no-run")
    import ooat_core.runtime as runtime_module
    real_run = runtime_module.Runtime.run

    def refuse_the_first(self, task):
        if task == task_id(first):
            raise ValueError("broken task")
        return real_run(self, task)
    monkeypatch.setattr(runtime_module.Runtime, "run", refuse_the_first)
    code, out = ooat(env, "task", "run", "--all")
    assert code == 0 and "broken task" in out and f"{task_id(second)}: CLOSED_DONE" in out


@pytest.mark.parametrize("argv, message", [
    (["task", "run", "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7"], "unknown task"),
    (["task", "submit", "--operator", "Martin", "--goal", "x", "--file", "missing.txt"], "cannot read the attachment"),
    (["hil", "answer", "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "--operator", "Martin", "--choice", "clarify"],
     "no question"),
    (["hil", "answer", "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "--operator", "Martin"], "--choice, --text or both"),
    (["hil", "answer", "evt_01J9ZQ70A0K3M5N7P9Q1R3S5T7", "--operator", "Martin", "--choice", "narrow_scope"],
     "narrow_scope needs the narrowed scope as --text"),
])
def test_mistakes_are_refused_without_a_traceback(env, argv, message):
    code, out = ooat(env, *argv)
    assert code == 1 and message in out


def test_task_commands_need_a_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stdout = io.StringIO()
    assert main(["task", "run", "tsk_01J9ZQ7A1BK3M5N7P9Q1R3S5T7"], stdout=stdout, registry=Registry([])) == 1
    assert "No ooat.toml found" in stdout.getvalue() and not (tmp_path / "ooat-ledger.sqlite").exists()


def test_an_invalid_rating_answer_is_asked_again(env):
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.")
    task = task_id(out)
    code, rated = ooat(env, "task", "rate", task, "--operator", "Martin", "--accepted", "yes", "--value", "B",
                       answers="\n\nthree\ntwo\n\n\n\n")
    assert code == 0 and "one of" in rated and "6 decisions recorded" in rated


def test_confirm_all_leaves_decisions_the_critic_contradicted_for_the_operator(env):
    env["model"].critic = '{"c1": {"met": false, "confidence": 0.9, "reason": "Too long."}}'
    attachment = env["dir"] / "smlouva.txt"
    attachment.write_text("Smlouva o dilu c. 12/2026.", encoding="utf-8")  # untrusted: the critic confirms
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň přiloženou smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.", "--file", str(attachment))
    task = task_id(out)
    assert "CLOSED_PARTIAL" in out
    code, rated = ooat(env, "task", "rate", task, "--operator", "Martin", "--accepted", "no", "--value", "C",
                       "--confirm-all")
    assert code == 0 and "5 decisions recorded" in rated and "Left out: 2 decisions the critic contradicted" in rated
    assert all(d["question"] != "c1" for d in events(env, task, "TASK_RATED")[0]["body"]["decisions"])


def test_show_names_a_hand_over_to_the_critic_instead_of_a_failed_gate(env):
    attachment = env["dir"] / "smlouva.txt"
    attachment.write_text("Smlouva o dilu c. 12/2026.", encoding="utf-8")  # untrusted: every "met" goes to the critic
    _, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Shrň přiloženou smlouvu.",
                  "--acceptance", "Shrnutí má nejvýše 300 slov.", "--file", str(attachment))
    code, shown = ooat(env, "task", "show", task_id(out))
    assert code == 0 and "HANDED_TO_CRITIC" in shown and "GATE_FAILED" not in shown
