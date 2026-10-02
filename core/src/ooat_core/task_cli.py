"""`ooat task submit | run | show | rate` and `ooat hil list | answer` (design 04 §5).

Local commands are trusted as the operator's own hand: whoever can run them can also edit the ledger file. The
`--operator` name is self-declared; remote identity (REST, Telegram) is verified in 05. Only these commands, and the
runtime applying a declared default after a deadline, append `actor.kind = hil` events.
"""

import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath

from .artifacts import ArtifactStore
from .blobs import BlobStore
from .catalog import routing_path
from .connector_admin import checked_operator
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway, GatewayError
from .ledger import DATA_CLASSES, Ledger, new_event
from .rating import rate, task_decisions
from .routing import load_routing
from .runtime import RunOutcome, Runtime
from .state import task_state

REFUSED = 1


def add_commands(commands) -> None:
    task = commands.add_parser("task", help="submit, run, show and rate tasks")
    actions = task.add_subparsers(dest="action", required=True)
    submit = actions.add_parser("submit", help="submit a task and run it in the foreground")
    submit.add_argument("--operator", required=True, help="your name; recorded as the submitter")
    submit.add_argument("--goal", required=True)
    submit.add_argument("--project", help="your project, e.g. sme-ai")
    submit.add_argument("--expected-output", dest="expected_output")
    submit.add_argument("--acceptance", action="append", default=[], help="an acceptance criterion (repeatable)")
    value = submit.add_mutually_exclusive_group()
    value.add_argument("--value", choices=["A", "B", "C"], help="value class (USD amounts in ooat.toml [gate])")
    value.add_argument("--value-usd", dest="value_usd", type=float)
    submit.add_argument("--budget", type=float, help="budget in USD (default from ooat.toml [gate])")
    submit.add_argument("--data-class", dest="data_class", choices=sorted(DATA_CLASSES),
                        help="the most sensitive data in the task (default internal); personal data such as e-mail "
                             "addresses or phone numbers is detected and raises it, names or health details are not")
    submit.add_argument("--risk-class", dest="risk_class", choices=["R0", "R1"])
    submit.add_argument("--file", action="append", default=[], help="an attachment, treated as untrusted data")
    submit.add_argument("--no-run", dest="no_run", action="store_true", help="only submit")
    run_parser = actions.add_parser("run", help="run a task as far as it can go; a paused task runs on")
    target = run_parser.add_mutually_exclusive_group(required=True)
    target.add_argument("task", nargs="?")
    target.add_argument("--all", dest="all_tasks", action="store_true",
                        help="every task that can move without you, e.g. those paused by a provider failure")
    actions.add_parser("show", help="timeline, costs and the document").add_argument("task")
    rating = actions.add_parser("rate", help="rate a closed task and confirm or correct its decisions")
    rating.add_argument("task")
    rating.add_argument("--operator", required=True)
    rating.add_argument("--accepted", choices=["yes", "no"], required=True)
    rating.add_argument("--value", choices=["A", "B", "C"], required=True, help="the value the result had")
    rating.add_argument("--note")
    rating.add_argument("--confirm-all", dest="confirm_all", action="store_true",
                        help="confirm every decision without asking")
    hil = commands.add_parser("hil", help="list and answer questions waiting for you")
    hil_actions = hil.add_subparsers(dest="action", required=True)
    hil_actions.add_parser("list", help="open questions with deadline, recommendation and default")
    answer = hil_actions.add_parser("answer", help="answer a question; the task then runs on")
    answer.add_argument("request")
    answer.add_argument("--operator", required=True)
    answer.add_argument("--choice")
    answer.add_argument("--text")


def _blobs_dir(config) -> Path | None:
    if config.blobs_dir:
        return Path(config.blobs_dir)
    location = config.ledger_url.removeprefix("sqlite:///")
    if location == config.ledger_url or location == ":memory:":
        return None
    absolute = PurePosixPath(location).is_absolute() or PureWindowsPath(location).is_absolute()
    return Path(location).parent / "ooat-blobs" if absolute else None


def run(args, config, path, stdin, stdout, registry, routing, clock, ask) -> int:
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    blobs = _blobs_dir(config)
    if blobs is None:
        stdout.write("Set [ledger] blobs in ooat.toml: artifacts need a folder. Nothing was changed.\n")
        return REFUSED
    try:
        ledger = Ledger.open(config.ledger_url)
    except (ValueError, NotImplementedError, sqlite3.Error, OSError) as error:
        stdout.write(f"Cannot open ledger {config.ledger_url}: {error}\n")
        return REFUSED
    try:
        gateway = Gateway(ledger, registry, routing or load_routing(routing_path()), config, SecretResolver(config),
                          clock=clock)
        runtime = Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(blobs)), settings_from_config(config),
                          clock=clock)
        handler = {("task", "submit"): _submit, ("task", "run"): _run_task, ("task", "show"): _show,
                   ("task", "rate"): _rate, ("hil", "list"): _hil_list, ("hil", "answer"): _hil_answer}
        return handler[(args.command, args.action)](args, ledger, runtime, stdin, stdout, ask)
    except ValueError as error:  # includes SpecValidationError: the ledger refused the event
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    except GatewayError as error:  # e.g. a quota cool-down: the task stays where it was
        stdout.write(f"Not now ({error.code}): {error.message}\n")
        return REFUSED
    finally:
        ledger.close()


def _report(task: str, outcome: RunOutcome, ledger: Ledger, stdout) -> int:
    stdout.write(f"{task}: {outcome.state} - {outcome.summary}\n")
    if outcome.request:
        request = next(e for e in ledger.events(task=task, types=["HIL_REQUEST"]) if e["id"] == outcome.request)
        stdout.write(_question(request))
        stdout.write(f"Answer: ooat hil answer {request['id']} --operator <name> --choice <id> | --text \"...\"\n")
    if outcome.artifact:
        stdout.write(f"Document: {outcome.artifact} (ooat task show {task})\n")
    return 0


def _question(request: dict) -> str:
    body = request["body"]
    lines = [f"Question {request['id']} (deadline {body['deadline']}): {body['question']}"]
    for option in body["options"]:
        marks = [m for m, on in (("recommended", option["id"] == body["recommended"]),
                                 ("default on silence", option["id"] == body["default_on_silence"])) if on]
        lines.append(f"  {option['id']}: {option['label']}" + (f" ({', '.join(marks)})" if marks else ""))
    return "\n".join(lines) + "\n"


def _submit(args, ledger, runtime, stdin, stdout, ask) -> int:
    try:
        files = [Path(name).read_bytes() for name in args.file]
    except OSError as error:
        raise ValueError(f"cannot read the attachment: {error}") from None
    value = {"class": args.value} if args.value else ({"usd": args.value_usd} if args.value_usd is not None else None)
    task = runtime.submit(operator=args.operator, goal=args.goal, acceptance=args.acceptance, project=args.project,
                          expected_output=args.expected_output, value=value, budget_usd=args.budget,
                          data_class=args.data_class, risk_class=args.risk_class, files=files)
    stdout.write(f"Submitted {task}.\n")
    if args.no_run:
        return 0
    return _report(task, runtime.run(task), ledger, stdout)


def _run_task(args, ledger, runtime, stdin, stdout, ask) -> int:
    if not args.all_tasks:
        return _report(args.task, runtime.run(args.task), ledger, stdout)
    tasks = runtime.runnable()
    if not tasks:
        stdout.write("No task can move without you.\n")
    for task in tasks:
        try:
            _report(task, runtime.run(task), ledger, stdout)
        except GatewayError as error:  # one provider down must not stop the others
            stdout.write(f"{task}: not now ({error.code}): {error.message}\n")
    return 0


def _show(args, ledger, runtime, stdin, stdout, ask) -> int:
    events = ledger.events(task=args.task)
    if not events:
        raise ValueError(f"unknown task {args.task}")
    stdout.write(f"{args.task}: {task_state(events)}\n")
    for event in events:
        usd = event.get("cost", {}).get("usd")
        cost = f"  {usd:.4f} USD" if usd is not None else ""
        stdout.write(f"  {event['ts'][:19]}  {event['type']:<17} {event['actor']['id']}{cost}\n")
    decided = [e for e in events if e["type"] == "TOPOLOGY_DECIDED"]
    estimates = [c["model_usd"] for c in decided[-1]["body"]["candidates"] if "model_usd" in c] if decided else []
    closed = [e for e in events if e["type"] == "TASK_CLOSED"]
    if closed:
        body = closed[-1]["body"]
        total = sum(body["cost"].values())
        estimate = f"; estimated {estimates[0]:.4f} USD" if estimates else ""
        stdout.write(f"Cost: {total:.4f} USD (contracts {body['cost']['contracts_usd']:.4f}, gate "
                     f"{body['cost']['gate_usd']:.4f}, checks {body['cost']['critic_usd']:.4f}){estimate}\n")
        if body.get("missing"):
            stdout.write(f"Missing: {body['missing']}\n")
        for ref in body.get("artifacts", []):
            stdout.write(f"\n--- {ref} ---\n{runtime.artifacts.read(ref).decode('utf-8', errors='replace')}\n")
    return 0


def _rate(args, ledger, runtime, stdin, stdout, ask) -> int:
    decisions = task_decisions(ledger.events(task=args.task))
    verdicts = {}
    for decision in decisions:
        key = (decision.event, decision.question)
        if args.confirm_all:
            verdicts[key] = "confirmed"
            continue
        answer = ask(f"{decision.kind} {decision.question}: answered {decision.answer} (confidence "
                     f"{decision.confidence:.2f}). Enter = confirm, '-' = skip, or the right answer: ", stdin, stdout)
        if answer == "":
            verdicts[key] = "confirmed"
        elif answer != "-":
            verdicts[key] = int(answer) if answer in ("0", "1") else answer
    event = rate(ledger, args.task, operator=args.operator, accepted=args.accepted == "yes", value_class=args.value,
                 verdicts=verdicts, note=args.note)
    stdout.write(f"Rated {args.task}: {len(event['body']['decisions'])} decisions recorded.\n")
    return 0


def _hil_list(args, ledger, runtime, stdin, stdout, ask) -> int:
    runtime.expire()
    events = ledger.events(types=["HIL_REQUEST", "HIL_RESPONSE"])
    answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
    open_requests = [e for e in events if e["type"] == "HIL_REQUEST" and e["id"] not in answered]
    if not open_requests:
        stdout.write("No open questions.\n")
    for request in open_requests:
        stdout.write(f"Task {request['task']}\n{_question(request)}")
    return 0


def _hil_answer(args, ledger, runtime, stdin, stdout, ask) -> int:
    if args.choice is None and not (args.text or "").strip():
        raise ValueError("give --choice, --text or both")
    request = next((e for e in ledger.events(types=["HIL_REQUEST"]) if e["id"] == args.request), None)
    if request is None:
        raise ValueError(f"no question {args.request}")
    body = {"request": args.request}
    if args.choice is not None:
        body["choice"] = args.choice
    if args.text and args.text.strip():
        body["text"] = args.text.strip()
    ledger.append(new_event("HIL_RESPONSE", task=request["task"], actor={"kind": "hil",
                                                                         "id": checked_operator(args.operator)},
                            body=body))
    stdout.write(f"Answered {args.request}.\n")
    return _report(request["task"], runtime.run(request["task"]), ledger, stdout)
