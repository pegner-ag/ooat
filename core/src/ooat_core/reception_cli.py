"""`ooat ask`: a message to the reception from the command line (design 08, plan 08a decision 11).

The message is recorded on the channel `cli` and decided at once, without the quiet window of `ooat serve`; the
reply, its numbered options and the task it started are printed. A started task runs with `ooat task run <id>`, or
within a minute when `ooat serve` runs.
"""

import sqlite3

from . import memory, setup
from .artifacts import ArtifactStore
from .blobs import BlobStore
from .catalog import routing_path
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway
from .ledger import Ledger
from .reception import Reception
from .routing import load_routing
from .runtime import Runtime
from .task_cli import _blobs_dir
from .workspace.runs import Workspaces

REFUSED = 1


def add_commands(commands) -> None:
    ask = commands.add_parser("ask", help="ask OOAT as you would a search box: it answers, asks or starts a task")
    ask.add_argument("--project", required=True, help="the project, e.g. a project of ooat.toml")
    ask.add_argument("--operator", required=True, help="your name; recorded as the sender")
    ask.add_argument("text", nargs="+", help="the message")


def run(args, config, path, stdout, registry, routing, clock) -> int:
    if config is None:
        stdout.write(setup.missing_config(path))
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
                          clock=clock, workspaces=Workspaces(config, path, setup.data_folder() / "workspaces"))
        folder = memory.memory_folder(config.ledger_url)
        reception = Reception(runtime, memory.MemoryStore(folder) if folder else None, config.reception,
                              config.projects, clock=clock)
        message = reception.receive(operator=args.operator, project=args.project, channel="cli",
                                    text=" ".join(args.text))
        decided = reception.decide(message["body"]["conversation"])
        if decided is None:
            stdout.write("Nothing to decide.\n")
            return 0
        body = decided["body"]
        stdout.write(body.get("reply", "") + "\n")
        for number, option in enumerate(body.get("options", []), 1):
            stdout.write(f"  {number}. {option}\n")
        if body.get("task") and body["decision"] in ("task", "continue_task"):
            stdout.write(f"Task {body['task']}: it runs with `ooat task run {body['task']}`, or within a minute when "
                         "`ooat serve` runs.\n")
        if body["buttons"]:
            stdout.write(f"Answer in the web app or the chat ({', '.join(body['buttons'])}); conversation "
                         f"{body['conversation']}.\n")
        return 0
    except ValueError as error:  # includes SpecValidationError: the ledger refused the event
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    finally:
        ledger.close()
