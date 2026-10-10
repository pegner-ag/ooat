"""`ooat tokens create | list | revoke` (design 05 §6, ADR 0016); `ooat serve` and `ooat login` join in Task 10.

A token is printed once, at creation; nothing else prints or logs it.
"""

import re
import sqlite3

from . import tokens
from .ledger import Ledger

REFUSED = 1
RESPONSIBILITY = """
A token for client or personal data (ADR 0012, ADR 0016). Whatever the token's client reads leaves this machine
and may be stored by its platform, such as a chat service. By answering yes you state that you have a legal basis
and a processing agreement for that. OOAT records your name and today's date with the token.
"""


def add_commands(commands) -> None:
    group = commands.add_parser("tokens", help="API tokens for bots and scripts")
    actions = group.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="create a token; it is shown once")
    create.add_argument("--operator", required=True, help="the operator the token acts as")
    create.add_argument("--name", required=True, help="what uses it, e.g. telegram")
    create.add_argument("--scopes", required=True, help=f"comma-separated: {','.join(tokens.SCOPES)}")
    create.add_argument("--max-data-class", dest="max_data_class", default="internal", choices=tokens.CAPS,
                        help="the most sensitive data the token may read or write (default internal)")
    create.add_argument("--expires", default=f"{tokens.DEFAULT_DAYS}d", help="days until it expires, e.g. 90d")
    create.add_argument("--responsibility", choices=["yes", "no"],
                        help="take responsibility for client or personal data (asked when such a class is chosen)")
    actions.add_parser("list", help="tokens with their operator, scopes, data class and state")
    revoke = actions.add_parser("revoke", help="revoke a token")
    revoke.add_argument("token")
    revoke.add_argument("--operator", required=True)
    revoke.add_argument("--reason", required=True)


def run(args, config, path, stdin, stdout, clock, ask) -> int:
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    try:
        ledger = Ledger.open(config.ledger_url)
    except (ValueError, NotImplementedError, sqlite3.Error, OSError) as error:
        stdout.write(f"Cannot open ledger {config.ledger_url}: {error}\n")
        return REFUSED
    try:
        handler = {"create": _create, "list": _list, "revoke": _revoke}[args.action]
        return handler(args, ledger, stdin, stdout, clock, ask)
    except ValueError as error:  # includes SpecValidationError
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    finally:
        ledger.close()


def _create(args, ledger, stdin, stdout, clock, ask) -> int:
    match = re.fullmatch(r"(\d{1,3})d", args.expires)
    if match is None:
        raise ValueError("--expires is a number of days, e.g. 90d")
    responsible = False
    if args.max_data_class in tokens.RESPONSIBLE_CAPS:
        stdout.write(RESPONSIBILITY)
        answer = args.responsibility or (ask("Do you take this responsibility? (yes/no): ", stdin, stdout) or "")
        if answer.strip().lower() != "yes":
            stdout.write("No token was created.\n")
            return REFUSED
        responsible = True
    secret, event = tokens.issue(ledger, operator=args.operator, name=args.name,
                                 scopes=[s.strip() for s in args.scopes.split(",") if s.strip()],
                                 max_data_class=args.max_data_class, days=int(match.group(1)),
                                 responsibility=responsible, now=clock())
    body = event["body"]
    stdout.write(f"Token {body['token']} for {body['name']}: acts as {body['operator']}, scopes "
                 f"{','.join(body['scopes'])}, data up to {body['max_data_class']}, expires {body['expires']}.\n"
                 f"\n  {secret}\n\n"
                 "It is shown only now: put it in the client's own secret store. OOAT keeps only its SHA-256.\n")
    return 0


def _list(args, ledger, stdin, stdout, clock, ask) -> int:
    known = tokens.tokens(ledger.events(types=tokens.EVENTS))
    if not known:
        stdout.write("No tokens.\n")
    now = clock()
    for token in known.values():
        state = "revoked" if token.revoked else "expired" if token.expires <= now else "active"
        stdout.write(f"{token.id}  {token.name}  [{state}]  operator {token.operator}  scopes "
                     f"{','.join(sorted(token.scopes))}  data up to {token.max_data_class}  expires "
                     f"{token.expires:%Y-%m-%d}\n")
    return 0


def _revoke(args, ledger, stdin, stdout, clock, ask) -> int:
    tokens.revoke(ledger, operator=args.operator, token_id=args.token, reason=args.reason)
    stdout.write(f"{args.token} revoked; it stops working on its next request.\n")
    return 0
