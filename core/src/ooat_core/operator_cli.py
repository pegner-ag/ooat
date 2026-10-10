"""`ooat` command line: `ooat connectors list | show | enable | disable`, and the task and HIL commands of
task_cli.py (`ooat task ...`, `ooat hil ...`)."""

import argparse
import sqlite3
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import connector_admin, task_cli
from .config import REGION, load_config
from .connectors.registry import Registry
from .ledger import Ledger

REFUSED = 1
CANCELLED = 130
RESPONSIBILITY = """
Client or personal data on this connector (ADR 0012). By answering yes you state that you have a legal basis
for it, a processing agreement with the provider that covers it, and that you know where the provider processes
it. OOAT records your name and today's date; the statement holds for 12 months or until the facts on the card
change. OOAT does not check it: you answer for it.
"""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ooat", description="OOAT operator commands.")
    parser.add_argument("--config", help="operator config (default: ./ooat.toml)")
    commands = parser.add_subparsers(dest="command", required=True)
    connectors = commands.add_parser("connectors", help="list, inspect, enable or disable model connectors")
    actions = connectors.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="installed connectors and their state")
    show = actions.add_parser("show", help="print the connection consequences card")
    show.add_argument("connector")
    enable = actions.add_parser("enable", help="acknowledge the consequences card and enable a connector")
    enable.add_argument("connector")
    enable.add_argument("--operator", required=True, help="your name; recorded as the approver")
    enable.add_argument("--classes", help="comma-separated data classes to allow (asked when omitted)")
    enable.add_argument("--automation", choices=["yes", "no"],
                        help="whether your plan's terms allow unattended use (asked when omitted)")
    enable.add_argument("--confirm", help="the connector id, typed again to confirm (asked when omitted)")
    enable.add_argument("--responsibility", choices=["yes", "no"],
                        help="take responsibility for client or personal data (asked when those classes are chosen)")
    enable.add_argument("--regions", help="comma-separated regions under your agreement, e.g. eu (asked when the "
                                          "manifest does not know them)")
    enable.add_argument("--no-training", dest="no_training", choices=["yes", "no"],
                        help="training on your inputs is switched off for this account (asked when unknown)")
    hooks = actions.add_parser("approve-hooks", help="review the hook files a connector's CLI would run and allow them")
    hooks.add_argument("connector")
    hooks.add_argument("--operator", required=True, help="your name; recorded as the approver")
    hooks.add_argument("--confirm", help="the connector id, typed again to confirm (asked when omitted)")
    disable = actions.add_parser("disable", help="disable a connector")
    disable.add_argument("connector")
    disable.add_argument("--operator", required=True)
    disable.add_argument("--reason", required=True)
    task_cli.add_commands(commands)
    return parser


def _ask(prompt: str, stdin, stdout) -> str:
    stdout.write(prompt)
    stdout.flush()
    return stdin.readline().strip()


def _ask_or_end(prompt: str, stdin, stdout) -> str | None:
    """Like _ask, but None when the input has ended, so the end of input is never read as an empty answer."""
    stdout.write(prompt)
    stdout.flush()
    line = stdin.readline()
    return None if line == "" else line.strip()


def main(argv=None, stdin=None, stdout=None, registry: Registry | None = None, today=None, routing=None,
         clock=None) -> int:
    if stdout is None and hasattr(sys.stdout, "reconfigure") and (sys.stdout.encoding or "").lower() != "utf-8":
        # A redirected stdout on Windows uses the ANSI code page, which cannot hold Czech text: write UTF-8.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    args = _parser().parse_args(argv)
    clock = clock or (lambda: datetime.now(timezone.utc))
    try:
        if args.command in ("task", "hil"):
            config, path, refusal = _config(args)
            if refusal is not None:
                stdout.write(refusal)
                return REFUSED
            return task_cli.run(args, config, path, stdin, stdout, registry or Registry.discover(), routing, clock,
                                _ask_or_end)
        return _run(args, stdin, stdout, registry, today or clock().date())
    except KeyboardInterrupt:
        if args.command in ("task", "hil"):  # events may already be in the ledger: say how to go on
            stdout.write("\nInterrupted. What was done is in the ledger; `ooat task run <id>` or "
                         "`ooat task run --all` continues.\n")
        else:
            stdout.write("\nCancelled; nothing was changed.\n")
        return CANCELLED


def _config(args):
    """(config or None, path, refusal message or None)."""
    path = Path(args.config or "ooat.toml")
    if args.config is not None and not path.exists():
        # An explicit config that is missing must not fall back to anything: a disable would land elsewhere.
        return None, path, f"Config file not found: {args.config}\n"
    try:
        return (load_config(path) if path.exists() else None), path, None
    except (tomllib.TOMLDecodeError, ValueError, OSError) as error:
        return None, path, f"Config error in {path}: {error}\n"


def _run(args, stdin, stdout, registry, today) -> int:
    config, path, refusal = _config(args)
    if refusal is not None:
        stdout.write(refusal)
        return REFUSED
    registry = registry or Registry.discover()
    if args.action == "show":  # read-only and ledger-free
        connector = registry.get(args.connector)
        if connector is None:
            stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
            return REFUSED
        stdout.write(connector_admin.consequences_card(connector.manifest, today, config) + "\n")
        return 0
    if config is None and args.action in ("enable", "disable", "approve-hooks"):
        # Without a config the ledger would be wherever the shell happens to be; state changes need the real one.
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    if config is None:
        stdout.write(f"No {path} found: connectors are shown without ledger state.\n")
    url = config.ledger_url if config else "sqlite:///:memory:"
    try:
        ledger = Ledger.open(url)
    except (ValueError, NotImplementedError, sqlite3.Error, OSError) as error:
        stdout.write(f"Cannot open ledger {url}: {error}\n")
        return REFUSED
    try:
        if args.action == "list":
            return _list(registry, ledger, today, config, stdout)
        if args.action == "disable":
            return _disable(args, ledger, url, stdout)
        if args.action == "approve-hooks":
            return _approve_hooks(args, registry, ledger, stdin, stdout)
        return _enable(args, registry, ledger, url, today, config, stdin, stdout)
    finally:
        ledger.close()


def _list(registry, ledger, today, config, stdout) -> int:
    for status in connector_admin.connector_statuses(registry, ledger, today, config):
        state = status.state
        if state == "enabled" and not status.unattended:
            state += ", not usable unattended"
        stale = " (jurisdiction stale: personal data refused)" if status.stale else ""
        tiers = ", ".join(f"{tier}={model or 'set in ooat.toml'}" for tier, model in status.tiers.items())
        stdout.write(f"{status.id}  [{state}]{stale}\n  {status.detail}\n")
        if tiers:
            stdout.write(f"  tiers: {tiers}; unattended use per terms: {status.automation}\n")
        if status.blocked:
            stdout.write(f"  {status.blocked}\n")
        if status.responsibility_until:
            stdout.write(f"  your responsibility for client or personal data holds until "
                         f"{status.responsibility_until}\n")
    return 0


def _approve_hooks(args, registry, ledger, stdin, stdout) -> int:
    """Show every hook file the connector's CLI would run, then record the named operator's approval (ADR 0015)."""
    connector = registry.get(args.connector)
    if connector is None:
        stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
        return REFUSED
    if not hasattr(connector, "hooks"):
        stdout.write(f"{args.connector} does not run hooks; nothing to approve.\n")
        return REFUSED
    files = connector.hooks()
    if not files:
        stdout.write("There are no hooks to approve.\n")
        return REFUSED
    unusable = [path for path, sha, _ in files if not sha]
    if unusable:  # each entry names the file or the command that cannot be fingerprinted
        stdout.write("These hooks cannot be approved:\n" + "".join(f"  {entry}\n" for entry in unusable))
        return REFUSED
    for path, sha, text in files:
        stdout.write(f"--- {path} (sha256 {sha[:12]}...)\n{text.rstrip()}\n")
    stdout.write("These commands run around every call of the connector's CLI, outside OOAT's isolation, and may receive "
                 "its prompts and replies. OOAT "
                 "passes them no ORCA_* or other non-allow-listed variables. Any change to a file needs a new "
                 "approval.\n")
    confirm = args.confirm or _ask(f"Type {args.connector} to approve: ", stdin, stdout)
    if confirm != args.connector:
        stdout.write("Not confirmed; nothing was changed.\n")
        return REFUSED
    try:
        connector_admin.approve_hooks(ledger, connector, args.operator, [(path, sha) for path, sha, _ in files],
                                      channel="cli")
    except ValueError as error:
        stdout.write(f"Refused: {error}; nothing was changed.\n")
        return REFUSED
    stdout.write(f"Hooks approved for {args.connector} by {args.operator.strip()}.\n")
    return 0


def _disable(args, ledger, url, stdout) -> int:  # also allowed for a connector that is no longer installed
    try:
        connector_admin.disable(ledger, args.connector, args.operator, args.reason, channel="cli")
    except ValueError as error:  # includes SpecValidationError, e.g. a malformed connector id
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    stdout.write(f"{args.connector} disabled. Recorded in {url}.\n")
    return 0


def _responsibility(args, manifest, stdin, stdout) -> tuple[dict | None, str | None]:
    """Ask for the operator's responsibility for client or personal data: (responsibility, refusal)."""
    stdout.write(RESPONSIBILITY)
    taken = args.responsibility or _ask("Do you take this responsibility? (yes/no): ", stdin, stdout).lower()
    if taken not in ("yes", "no"):
        return None, "answer yes or no"
    if taken == "no":
        return None, "client_confidential and personal data need your responsibility"
    responsibility = {}
    if not manifest["jurisdiction"]["processing_regions"]:
        answer = args.regions if args.regions is not None else _ask(
            "Regions where the provider processes under your agreement (e.g. eu, us): ",
            stdin, stdout)
        regions = [r.strip() for r in answer.split(",") if r.strip()]
        if not all(REGION.match(r) for r in regions):
            return None, "regions are codes such as eu or us"
        if not regions:  # the gateway would never route there: say so now, not at the first task
            return None, "client and personal data need a known processing region; state it from your agreement"
        responsibility["processing_regions"] = sorted(set(regions))
    if manifest["data_policy"]["training_on_inputs"] is None:
        off = args.no_training or _ask("Is training on your inputs switched off for this account? (yes/no): ",
                                       stdin, stdout).lower()
        if off not in ("yes", "no"):
            return None, "answer yes or no"
        if off == "yes":
            responsibility["no_training"] = True
    return responsibility, None


def _enable(args, registry, ledger, url, today, config, stdin, stdout) -> int:
    connector = registry.get(args.connector)
    if connector is None:
        stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
        return REFUSED
    manifest = connector.manifest
    try:  # refuse what can be refused before asking anything
        operator = connector_admin.checked_operator(args.operator)
        if args.classes is not None and not args.classes.strip():
            raise ValueError("--classes is empty")
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    stdout.write(connector_admin.consequences_card(manifest, today, config) + "\n")
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in manifest["data_policy"]["allowed_data_classes"]]
    if args.classes is not None:
        answer = args.classes
    else:
        hint = f" [{','.join(default)}]" if default else ""
        answer = _ask(f"\nData classes to allow{hint}: ", stdin, stdout) or ",".join(default)
    requested = [c.strip() for c in answer.split(",") if c.strip()]
    responsibility = None
    if set(requested) & set(connector_admin.RESPONSIBLE_CLASSES):
        responsibility, refusal = _responsibility(args, manifest, stdin, stdout)
        if refusal:
            stdout.write(f"Refused: {refusal}; nothing was changed.\n")
            return REFUSED
    try:
        classes = connector_admin.checked_classes(manifest, requested, responsibility)
    except ValueError as error:
        stdout.write(f"Refused: {error}; nothing was changed.\n")
        return REFUSED
    forbidden = connector_admin.unattended_forbidden(manifest)
    if forbidden and args.automation == "yes":
        stdout.write(f"Refused: {forbidden}; nothing was changed.\n")
        return REFUSED
    if forbidden:
        automation = False
    else:
        automation_answer = args.automation or _ask(
            "Do the terms of your plan allow unattended automated use? (yes/no): ", stdin, stdout).lower()
        if automation_answer not in ("yes", "no"):
            stdout.write("Answer yes or no; nothing was changed.\n")
            return REFUSED
        automation = automation_answer == "yes"
    unattended = f"no ({forbidden})" if forbidden else ("yes" if automation else "no")
    stdout.write(f"You are allowing: {', '.join(classes)}; unattended use: {unattended}\n")
    confirmation = args.confirm if args.confirm is not None else _ask(f"Type {manifest['id']} to confirm: ",
                                                                      stdin, stdout)
    if confirmation != manifest["id"]:
        stdout.write("Confirmation did not match; nothing was changed.\n")
        return REFUSED
    try:
        connector_admin.acknowledge(ledger, connector, operator, classes, automation, responsibility, today,
                                    channel="cli")
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    if forbidden:
        mode = forbidden
    else:
        mode = "unattended use confirmed" if automation else "not used unattended until automation is confirmed"
    stdout.write(f"{manifest['id']} enabled for {', '.join(classes)}; {mode}. Recorded in {url}.\n")
    if responsibility is not None:
        stdout.write(f"You took responsibility for client or personal data on it as {operator} on {today}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
