"""`ooat serve`, `ooat login` and `ooat tokens create | list | revoke` (design 05 §6, §7; ADR 0016).

A token is printed once, at creation, and a sign-in link once, when it is made; nothing else prints or logs either.
"""

import logging
import re
import sqlite3
import webbrowser

from . import runner_lock, tokens
from .catalog import routing_path
from .connectors.registry import Registry
from .ledger import Ledger
from .routing import load_routing
from .sessions import issue_login_code, login_folder
from .task_cli import _blobs_dir

REFUSED = 1
DEFAULT_PORT = 8765
RESPONSIBILITY = """
A token for client or personal data (ADR 0012, ADR 0016). Whatever the token's client reads leaves this machine
and may be stored by its platform, such as a chat service. By answering yes you state that you have a legal basis
and a processing agreement for that. OOAT records your name and today's date with the token.
"""


def add_commands(commands) -> None:
    serve = commands.add_parser("serve", help="the web app and the API on this machine, and the task runner")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1; any other needs [serve] TLS)")
    serve.add_argument("--port", type=int, help=f"port (default {DEFAULT_PORT})")
    serve.add_argument("--no-browser", dest="no_browser", action="store_true", help="do not open the browser")
    login = commands.add_parser("login", help="print a one-time sign-in link for the web app")
    login.add_argument("--operator", required=True, help="who signs in; recorded on everything they do there")
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


def run(args, config, path, stdin, stdout, clock, ask, registry=None, routing=None) -> int:
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    if args.command == "serve":
        return _serve(args, config, stdout, clock, registry, routing)
    if args.command == "login":
        return _login(args, config, stdout, clock)
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


# `ooat serve` and `ooat login` ------------------------------------------------------------------------------------

def serve_settings(config, host: str | None = None, port: int | None = None):
    """(ServeSettings, None) from [serve] and the command line, or (None, why it cannot serve)."""
    from .api import ServeSettings

    serve, blobs = config.serve, _blobs_dir(config)
    if login_folder(config.ledger_url) is None or blobs is None:
        return None, "`ooat serve` needs a ledger file on a local disk ([ledger] url = \"sqlite:///...\").\n"
    settings = ServeSettings(ledger_url=config.ledger_url, blobs_dir=blobs, operator=serve.get("operator"),
                             host=host or serve.get("host", "127.0.0.1"), port=port or serve.get("port", DEFAULT_PORT),
                             hosts=tuple(serve.get("hosts", [])), tls="tls_cert" in serve)
    if not settings.loopback and not settings.tls:  # design 05 §6: beyond loopback only with TLS
        return None, (f"Serving on {settings.host} lets other machines reach OOAT: set [serve] tls_cert and tls_key "
                      "first. Nothing was started.\n")
    return settings, None


def sign_in_link(settings, code: str) -> str:
    """The code goes in the fragment, which the browser never sends to a server."""
    host = settings.hosts[0] if settings.hosts else "127.0.0.1" if settings.loopback else settings.host
    host = f"[{host}]" if ":" in host else host
    return f"{'https' if settings.tls else 'http'}://{host}:{settings.port}/login#code={code}"


def _serve(args, config, stdout, clock, registry, routing) -> int:
    """The API, the sign-in page and the runner until Ctrl+C, holding the runner lock all the while."""
    import uvicorn

    from .api import create_app

    settings, refusal = serve_settings(config, args.host, args.port)
    if refusal:
        stdout.write(refusal)
        return REFUSED
    lock = runner_lock.for_ledger(config.ledger_url)
    if not lock.acquire():
        stdout.write("Another process runs the tasks of this ledger (`ooat serve` or `ooat task run`). "
                     "Nothing was started.\n")
        return REFUSED
    try:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
        app = create_app(settings, config=config, registry=registry or Registry.discover(),
                         routing=routing or load_routing(routing_path()), clock=clock)
        stdout.write(f"OOAT serves {config.ledger_url} on {settings.host}:{settings.port}; the ledger must be on a "
                     "local disk. Stop with Ctrl+C.\n")
        if settings.operator:
            link = sign_in_link(settings, issue_login_code(login_folder(config.ledger_url), settings.operator,
                                                           clock()))
            stdout.write(f"Sign in as {settings.operator} (valid 5 minutes, once): {link}\n")
            if not args.no_browser:
                webbrowser.open(link)
        else:
            stdout.write("Sign in with the link `ooat login --operator <your name>` prints.\n")
        stdout.flush()
        tls = {"ssl_certfile": config.serve["tls_cert"], "ssl_keyfile": config.serve["tls_key"]} if settings.tls \
            else {}
        # No access log: it would record query strings and client addresses; the API logs method, path, status.
        uvicorn.run(app, host=settings.host, port=settings.port, access_log=False, server_header=False,
                    log_level="info", **tls)
        return 0
    finally:
        lock.release()


def _login(args, config, stdout, clock) -> int:
    settings, refusal = serve_settings(config)
    if refusal:
        stdout.write(refusal)
        return REFUSED
    try:
        code = issue_login_code(login_folder(config.ledger_url), args.operator, clock())
    except ValueError as error:
        stdout.write(f"Refused: {error}\n")
        return REFUSED
    stdout.write(f"Sign in as {args.operator.strip()} (valid 5 minutes, once): {sign_in_link(settings, code)}\n")
    return 0


# `ooat tokens` ----------------------------------------------------------------------------------------------------

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
