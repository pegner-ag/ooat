"""Eval candidates from the operator's ledger (plan 09 decision 8).

    python evals/candidates.py --config ooat.toml --out ../reception-candidates.json [--max-class internal]

Two lists, for the owner to pick from and sanitise:
- reception: every message whose decision got a Differently, in the cases format of evals/reception/run.py with
  `expected` left empty (the owner writes it), the decision it got, the correction and the decision that followed;
- tasks: every task rated rejected, its goal, criteria, closing state and rating note (no attachments).

It reads the ledger and writes only `--out`, which must lie outside the repository: candidates are the operator's
data until the owner has picked them. A case is left out, and counted, when any text it carries (its own turns or
the earlier turns of its conversation) is above `--max-class`.
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ORDER = ("public", "internal", "client_confidential", "personal", "special_category")
REPLACED = ("escalated", "retried")  # calls whose decision the next call replaced: the person never saw them


def _within(data_class: str, cap: str) -> bool:
    return ORDER.index(data_class) <= ORDER.index(cap)


def checked_out(path: Path, repo: Path = REPO) -> Path:
    """The output path, resolved; never inside the repository."""
    resolved, repo = path.resolve(), repo.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError(f"write the candidates outside the repository ({repo})")
    return resolved


def _said(event: dict) -> str | None:
    body = event["body"]
    return body.get("text") or (body.get("tap_text") if body.get("tap") == "differently" else None)


def reception_candidates(events: list[dict], max_class: str) -> tuple[list[dict], int]:
    """(cases, left out): a message whose decision got a Differently, with the earlier turns as its context."""
    by_id = {e["id"]: e for e in events}
    turns: dict[str, list[dict]] = {}  # conversation -> its turns: person, reception, options, the classes seen
    shown: dict[str, dict] = {}  # conversation -> the newest decision the person saw
    waiting: dict[str, dict] = {}  # conversation -> a case waiting for the decision after its correction
    cases, left_out = [], 0
    for event in events:
        body = event["body"]
        cnv = body.get("conversation")
        if event["type"] == "RECEPTION_DECIDED" and body["decision"] not in REPLACED:
            if cnv in waiting:
                waiting.pop(cnv)["then"] = body["decision"]
            said = [by_id[m] for m in body["messages"] if m in by_id]
            turns.setdefault(cnv, []).append({
                "person": " ".join(_said(m) or "" for m in said).strip(), "reception": body.get("reply"),
                "options": body.get("options", []),
                "classes": [body["data_class"], *(m["body"]["data_class"] for m in said)]})
            shown[cnv] = event
        elif event["type"] == "CONVERSATION_MESSAGE" and body.get("tap") == "differently" and cnv in shown:
            wrong = shown.pop(cnv)
            history = turns[cnv]
            classes = [body["data_class"], *(c for turn in history for c in turn["classes"])]
            if not all(_within(c, max_class) for c in classes) or not isinstance(history[-1]["reception"], str):
                left_out += 1
                continue
            context = [{"person": t["person"], "reception": t["reception"], **({"options": t["options"]}
                                                                               if t["options"] else {})}
                       for t in history[:-1]]
            case = {"text": history[-1]["person"], "expected": None, "got": wrong["body"]["decision"],
                    "correction": body.get("tap_text"), "then": None, "context": context}
            cases.append(case)
            waiting[cnv] = case
    return cases, left_out


def task_candidates(events: list[dict], max_class: str, task_class: Callable[[str], str]) -> tuple[list[dict], int]:
    """(cases, left out): every task rated rejected; `task_class(task)` is the class the task ran under, raised by
    personal data in the rating note, which has no class of its own."""
    from ooat_core.pii import raised_class

    submitted = {e["task"]: e for e in events if e["type"] == "TASK_SUBMITTED"}
    closed = {e["task"]: e["body"]["state"] for e in events if e["type"] == "TASK_CLOSED"}
    cases, left_out = [], 0
    for event in events:
        if event["type"] != "TASK_RATED" or event["body"]["accepted"] or event["task"] not in submitted:
            continue
        if not _within(raised_class(task_class(event["task"]), event["body"].get("note") or ""), max_class):
            left_out += 1
            continue
        task = submitted[event["task"]]["body"]
        cases.append({"task": event["task"], "goal": task["goal"], "acceptance": task.get("acceptance", []),
                      "state": closed.get(event["task"]), "note": event["body"].get("note"),
                      "value_class": event["body"]["value_class"]})
    return cases, left_out


def main(argv: list[str] | None = None, stdout=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Export eval candidates from the ledger, outside the repository.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--max-class", default="internal", choices=ORDER)
    args = parser.parse_args(argv)
    out = checked_out(args.out)
    from ooat_core import views
    from ooat_core.config import load_config
    from ooat_core.gate import settings_from_config
    from ooat_core.ledger import Ledger

    config = load_config(args.config)
    ledger = Ledger.open(config.ledger_url)
    try:
        events = ledger.events()
        settings = settings_from_config(config)

        def task_class(task: str) -> str:
            return views.task_class([e for e in events if e["task"] == task],
                                    lambda ref: ledger.artifact(ref)["data_class"], settings)

        reception, left_reception = reception_candidates(events, args.max_class)
        tasks, left_tasks = task_candidates(events, args.max_class, task_class)
    finally:
        ledger.close()
    out.write_text(json.dumps({"reception": reception, "tasks": tasks}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    stdout.write(f"{len(reception)} reception and {len(tasks)} task candidates written to {out}; "
                 f"{left_reception + left_tasks} left out above {args.max_class}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
