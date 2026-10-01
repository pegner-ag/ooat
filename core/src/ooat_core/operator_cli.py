"""`ooat` command line: operator commands. Currently `ooat connectors list | show | enable | disable`."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import connector_admin
from .config import Config, load_config
from .connectors.registry import Registry
from .ledger import Ledger

REFUSED = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ooat", description="OOAT operator commands.")
    parser.add_argument("--config", help="operator config (default: ./ooat.toml if present)")
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
    if args.config is not None and not Path(args.config).exists():
        # An explicit config that is missing must not fall back to a default ledger: a disable would land elsewhere.
        stdout.write(f"Config file not found: {args.config}\n")
        return REFUSED
    path = args.config or "ooat.toml"
    config = load_config(path) if Path(path).exists() else Config()
    registry = registry or Registry.discover()
    today = today or datetime.now(timezone.utc).date()
    ledger = Ledger.open(config.ledger_url)
    try:
        return _connectors(args, ledger, registry, today, stdin, stdout)
    finally:
        ledger.close()


def _connectors(args, ledger, registry, today, stdin, stdout) -> int:
    if args.action == "list":
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
    if args.action == "disable":  # also allowed for a connector that is no longer installed
        try:
            connector_admin.disable(ledger, args.connector, args.operator, args.reason)
        except ValueError as error:  # includes SpecValidationError, e.g. a malformed connector id
            stdout.write(f"Refused: {error}\n")
            return REFUSED
        stdout.write(f"{args.connector} disabled.\n")
        return 0
    connector = registry.get(args.connector)
    if connector is None:
        stdout.write(f"{args.connector} is not installed (see `ooat connectors list`).\n")
        return REFUSED
    stdout.write(connector_admin.consequences_card(connector.manifest, today) + "\n")
    if args.action == "show":
        return 0
    return _enable(args, ledger, connector, stdin, stdout)


def _enable(args, ledger, connector, stdin, stdout) -> int:
    accepted = connector.manifest["data_policy"]["allowed_data_classes"]
    default = [c for c in connector_admin.DEFAULT_CLASSES if c in accepted]
    answer = args.classes if args.classes is not None else _ask(
        f"\nData classes to allow [{','.join(default)}]: ", stdin, stdout)
    classes = [c.strip() for c in answer.split(",") if c.strip()] or default
    forbidden = connector_admin.unattended_forbidden(connector.manifest)
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
    confirmation = args.confirm if args.confirm is not None else _ask(
        f"Type {connector.manifest['id']} to confirm: ", stdin, stdout)
    if confirmation != connector.manifest["id"]:
        stdout.write("Confirmation did not match; nothing was changed.\n")
        return REFUSED
    try:
        connector_admin.acknowledge(ledger, connector, args.operator, classes, automation)
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    if forbidden:
        mode = f"{forbidden}"
    else:
        mode = "unattended use confirmed" if automation else "not used unattended until automation is confirmed"
    stdout.write(f"{connector.manifest['id']} enabled for {', '.join(classes)}; {mode}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
