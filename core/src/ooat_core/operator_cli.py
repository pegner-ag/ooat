"""`ooat` command line: operator commands. Currently `ooat connectors list | show | enable | disable`."""

import argparse
import sqlite3
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from . import connector_admin
from .config import load_config
from .connectors.registry import Registry
from .ledger import Ledger

REFUSED = 1
CANCELLED = 130


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
    disable = actions.add_parser("disable", help="disable a connector")
    disable.add_argument("connector")
    disable.add_argument("--operator", required=True)
    disable.add_argument("--reason", required=True)
    return parser


def _ask(prompt: str, stdin, stdout) -> str:
    stdout.write(prompt)
    stdout.flush()
    return stdin.readline().strip()


def main(argv=None, stdin=None, stdout=None, registry: Registry | None = None, today=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    args = _parser().parse_args(argv)
    try:
        return _run(args, stdin, stdout, registry, today or datetime.now(timezone.utc).date())
    except KeyboardInterrupt:
        stdout.write("\nCancelled; nothing was changed.\n")
        return CANCELLED


def _run(args, stdin, stdout, registry, today) -> int:
    path = Path(args.config or "ooat.toml")
    if args.config is not None and not path.exists():
        # An explicit config that is missing must not fall back to anything: a disable would land elsewhere.
        stdout.write(f"Config file not found: {args.config}\n")
        return REFUSED
    try:
        config = load_config(path) if path.exists() else None
    except (tomllib.TOMLDecodeError, ValueError, OSError) as error:
        stdout.write(f"Config error in {path}: {error}\n")
        return REFUSED
    registry = registry or Registry.discover()
    if args.action == "show":  # read-only and ledger-free
        connector = registry.get(args.connector)
        if connector is None:
            stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
            return REFUSED
        stdout.write(connector_admin.consequences_card(connector.manifest, today) + "\n")
        return 0
    if config is None and args.action in ("enable", "disable"):
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
            return _list(registry, ledger, today, stdout)
        if args.action == "disable":
            return _disable(args, ledger, url, stdout)
        return _enable(args, registry, ledger, url, today, stdin, stdout)
    finally:
        ledger.close()


def _list(registry, ledger, today, stdout) -> int:
    for status in connector_admin.connector_statuses(registry, ledger, today):
        state = status.state
        if state == "enabled" and not status.unattended:
            state += ", not usable unattended"
        stale = " (jurisdiction stale: personal data refused)" if status.stale else ""
        tiers = ", ".join(f"{tier}={model or 'set in ooat.toml'}" for tier, model in status.tiers.items())
        stdout.write(f"{status.id}  [{state}]{stale}\n  {status.detail}\n")
        if tiers:
            stdout.write(f"  tiers: {tiers}; unattended use per terms: {status.automation}\n")
    return 0


def _disable(args, ledger, url, stdout) -> int:  # also allowed for a connector that is no longer installed
    try:
        connector_admin.disable(ledger, args.connector, args.operator, args.reason)
    except ValueError as error:  # includes SpecValidationError, e.g. a malformed connector id
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    stdout.write(f"{args.connector} disabled. Recorded in {url}.\n")
    return 0


def _enable(args, registry, ledger, url, today, stdin, stdout) -> int:
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
    stdout.write(connector_admin.consequences_card(manifest, today) + "\n")
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in manifest["data_policy"]["allowed_data_classes"]]
    if args.classes is not None:
        answer = args.classes
    else:
        hint = f" [{','.join(default)}]" if default else ""
        answer = _ask(f"\nData classes to allow{hint}: ", stdin, stdout) or ",".join(default)
    try:
        classes = connector_admin.checked_classes(manifest, [c.strip() for c in answer.split(",") if c.strip()])
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
        connector_admin.acknowledge(ledger, connector, operator, classes, automation)
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    if forbidden:
        mode = forbidden
    else:
        mode = "unattended use confirmed" if automation else "not used unattended until automation is confirmed"
    stdout.write(f"{manifest['id']} enabled for {', '.join(classes)}; {mode}. Recorded in {url}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
