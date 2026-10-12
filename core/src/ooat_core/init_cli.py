"""`ooat init`: the first-run setup in the terminal (design 05 §10, plan 01c), the steps of the browser's Setup.

1. the data folder (the OS user data folder by default; the ledger is SQLite there, ADR 0008), 2. your name,
3. the connectors found: an API connector's key variable by name, and each available connector's card to enable
now, 4. an optional token for a chat bridge, shown once, 5. how to start. `--yes` takes the defaults, enables
nothing and creates no token, for scripts. The config goes where OOAT looks for it, so every later command finds it.
"""

import argparse
from pathlib import Path

from . import setup
from .config import load_config
from .ledger import Ledger

REFUSED = 1


class _Ended(Exception):
    """The input ended before the config was written."""


def add_commands(commands) -> None:
    init = commands.add_parser("init", help="set OOAT up on this machine: data folder, your name, connectors")
    init.add_argument("--data", help="the folder for OOAT's data (default: your user data folder)")
    init.add_argument("--operator", help="your name (default: your OS account name)")
    init.add_argument("--yes", action="store_true", help="take the defaults; enable nothing and create no token")


def run(args, path: Path, stdin, stdout, registry, today, clock, ask, enable) -> int:
    """`path` is where the config goes (setup.find_config); `ask` returns None at the end of the input; `enable` is
    the `ooat connectors enable` dialogue."""
    if path.exists():
        stdout.write(f"OOAT is already set up: {path}. Nothing was changed; start it with `ooat serve`.\n")
        return 0

    def answer(prompt: str, default: str) -> str:
        if args.yes:
            return default
        given = ask(f"{prompt} [{default}]: ", stdin, stdout)
        if given is None:
            raise _Ended
        return given or default

    found = setup.found_connectors(registry)
    try:
        folder = Path(args.data or answer("Data folder for the ledger (SQLite) and files", str(setup.data_folder())))
        folder = folder.expanduser().resolve()  # the ledger URL must not depend on the folder a command runs from
        operator = args.operator or answer("Your name, recorded on what you do", setup.operator_name())
        stdout.write("\nConnectors found:\n" + "".join(f"  {'●' if f.available else '○'} {f.id}: {f.detail}\n"
                                                         for f in found))
        secret_envs = {}
        for f in (f for f in found if f.access == "api"):
            stdout.write(f"  {f.id} key variables set: {', '.join(f.key_variables) or 'none'}\n")
            default = setup.default_secret_envs([f]).get(f.id, "")  # an admin key is never the default
            name = default if args.yes else answer(f"Environment variable with the API key of {f.id} "
                                                   "(empty: set it later in ooat.toml)", default)
            if name:
                secret_envs[f.id] = name
        text = setup.config_text(folder, operator, secret_envs)
    except _Ended:
        stdout.write("\nCancelled; nothing was changed.\n")
        return REFUSED
    except ValueError as error:
        stdout.write(f"Refused: {error}; nothing was changed.\n")
        return REFUSED
    folder.mkdir(parents=True, exist_ok=True)
    setup.write_config(path, text)
    stdout.write(f"\nWrote {path}. The ledger is {folder / setup.LEDGER_NAME}: SQLite on this disk (other databases "
                 "come with plan 01b).\n")
    if not args.yes:
        config = load_config(path)
        ledger = Ledger.open(config.ledger_url)
        try:
            _connectors(found, operator, registry, ledger, config, today, stdin, stdout, ask, enable)
            _bridge(operator, ledger, clock, stdin, stdout, ask)
        finally:
            ledger.close()
    stdout.write("\nDone. Start OOAT with `ooat serve`: the web app opens, and its Setup page ends with a sample "
                 "task.\n")
    return 0


def _yes(ask, prompt: str, stdin, stdout) -> bool:
    return (ask(f"{prompt} (yes/no) [no]: ", stdin, stdout) or "").strip().lower() == "yes"


def _connectors(found, operator, registry, ledger, config, today, stdin, stdout, ask, enable) -> None:
    for f in (f for f in found if f.available):
        if _yes(ask, f"\nRead the card of {f.id} and enable it now?", stdin, stdout):
            enable(argparse.Namespace(connector=f.id, operator=operator, classes=None, automation=None, confirm=None,
                                      responsibility=None, regions=None, no_training=None),
                   registry, ledger, config.ledger_url, today, config, stdin, stdout)


def _bridge(operator, ledger, clock, stdin, stdout, ask) -> None:
    if not _yes(ask, "\nCreate a token for your chat bot (the chat bridge, docs/chat-bridge.md)?", stdin, stdout):
        return
    secret, event = setup.bridge_token(ledger, operator, clock())
    body = event["body"]
    stdout.write(f"Token {body['token']} for {body['name']}: scopes {','.join(body['scopes'])}, data up to "
                 f"{body['max_data_class']}, expires {body['expires']}.\n\n  {secret}\n\n"
                 "It is shown only now: put it in the bot's own secret store. OOAT keeps only its SHA-256.\n")
