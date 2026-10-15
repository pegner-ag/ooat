"""Measure the reception against a set of messages (design 08 §11, plan 08a decision 12).

    python evals/reception/run.py --config ooat.toml --cases my-messages.json [--project docs]

Each case is {"text": "...", "expected": "<decision>", "context": [{"person": "...", "reception": "..."}, ...]}:
the earlier turns are written into a scratch ledger as they were, then the reception decides the text with the
operator's real connectors. Nothing is written to the operator's ledger: the scratch ledger lives in memory and gets
only the connectors' acknowledgements, copied from the operator's ledger, so routing is the operator's own.
Tasks the reception starts are submitted to the scratch ledger and never run.

It prints one row per case and then three figures against design 08 §1: the share decided as expected, the share
decided without a question, and the mean cost per message (target USD 0.02). The owner's own messages stay outside
the repository until the owner has picked them and removed anything sensitive; `example.json` is made up.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

DECISIONS = ("answer", "task", "confirm", "ask", "continue_task", "status", "cancel", "command", "switch", "forget")
QUESTIONS = ("ask", "confirm")
TARGET_USD = 0.02


def load_cases(text: str) -> list[dict]:
    """The cases of a file, checked; a bad case is named by its number (from 1)."""
    cases = json.loads(text)
    if not isinstance(cases, list) or not cases:
        raise ValueError("the cases file holds a JSON list of cases")
    for number, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("text"), str) or not case["text"].strip():
            raise ValueError(f"case {number}: it needs a text")
        if case.get("expected") not in DECISIONS:
            raise ValueError(f"case {number}: expected is one of {', '.join(DECISIONS)}")
        for turn in case.get("context", []):
            if not isinstance(turn, dict) or not isinstance(turn.get("person"), str):
                raise ValueError(f"case {number}: each context turn has a person's text (and the reception's reply)")
    return cases


def evaluate(cases: list[dict], decide) -> dict:
    """Run `decide(case) -> (decision, usd)` on every case; the rows and the three figures."""
    rows = []
    for number, case in enumerate(cases, 1):
        got, usd = decide(case)
        rows.append({"case": number, "expected": case["expected"], "got": got, "usd": usd})
    total = len(rows)
    return {"rows": rows, "as_expected": sum(r["got"] == r["expected"] for r in rows) / total,
            "without_question": sum(r["got"] not in QUESTIONS for r in rows) / total,
            "mean_usd": sum(r["usd"] for r in rows) / total}


def _reception(config, path, registry, routing):
    from ooat_core.artifacts import ArtifactStore
    from ooat_core.blobs import BlobStore
    from ooat_core.credentials_env import SecretResolver
    from ooat_core.gate import settings_from_config
    from ooat_core.gateway import Gateway
    from ooat_core.ledger import Ledger
    from ooat_core.reception import Reception
    from ooat_core.runtime import Runtime
    from ooat_core.workspace.runs import Workspaces

    scratch = Ledger.open("sqlite:///:memory:")
    real = Ledger.open(config.ledger_url)
    try:
        for event in real.events(types=["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED"]):
            scratch.append(event)
    finally:
        real.close()
    folder = tempfile.mkdtemp(prefix="ooat-eval-")
    runtime = Runtime(scratch, Gateway(scratch, registry, routing, config, SecretResolver(config)),
                      ArtifactStore(scratch, BlobStore(Path(folder) / "blobs")), settings_from_config(config),
                      workspaces=Workspaces(config, path, Path(folder) / "workspaces"))
    return Reception(runtime, None, config.reception, config.projects)


def _decider(reception, project: str):
    from ooat_core.ledger import new_event
    from ooat_core.reception import ACTOR

    def decide(case: dict) -> tuple[str, float]:
        conversation = None
        for turn in case.get("context", []):
            message = reception.receive(operator="eval", project=project, channel="cli", text=turn["person"],
                                        conversation=conversation)
            conversation = message["body"]["conversation"]
            reception.ledger.append(new_event("RECEPTION_DECIDED", task=None, actor=ACTOR, body={
                "conversation": conversation, "project": project, "messages": [message["id"]],
                "decision": "answer", "reply": turn.get("reception") or "(reply)", "options": turn.get("options", []),
                "buttons": [], "context": [], "data_class": message["body"]["data_class"]}))
        message = reception.receive(operator="eval", project=project, channel="cli", text=case["text"],
                                    conversation=conversation)
        before = len(reception.ledger.events(types=["RECEPTION_DECIDED"]))
        decided = reception.decide(message["body"]["conversation"])
        spent = sum(e.get("cost", {}).get("usd", 0.0)
                    for e in reception.ledger.events(types=["RECEPTION_DECIDED"])[before:])
        reception.close(message["body"]["conversation"], "operator")  # the next case starts afresh
        return (decided["body"]["decision"] if decided else "none"), spent
    return decide


def main(argv=None, stdout=sys.stdout) -> int:
    parser = argparse.ArgumentParser(description="Measure the reception against a set of messages.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--project", default="docs")
    args = parser.parse_args(argv)
    from ooat_core.catalog import routing_path
    from ooat_core.config import load_config
    from ooat_core.connectors.registry import Registry
    from ooat_core.routing import load_routing

    config = load_config(args.config)
    cases = load_cases(Path(args.cases).read_text(encoding="utf-8"))
    reception = _reception(config, args.config, Registry.discover(), load_routing(routing_path()))
    result = evaluate(cases, _decider(reception, args.project))
    for row in result["rows"]:
        mark = "ok" if row["got"] == row["expected"] else "--"
        stdout.write(f"{row['case']:>3} {mark} expected {row['expected']:<13} got {row['got']:<13} "
                     f"{row['usd']:.4f} USD\n")
    stdout.write(f"As expected: {result['as_expected']:.0%}. Without a question: {result['without_question']:.0%}. "
                 f"Mean cost: {result['mean_usd']:.4f} USD per message (target {TARGET_USD:.2f}).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
