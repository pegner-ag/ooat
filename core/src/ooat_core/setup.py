"""First-run setup (design 05 §10, plan 01c): where OOAT keeps its data, the ooat.toml it writes, and what the
machine already has. Shared by `ooat init` in the terminal and the first `ooat serve` in the browser.

The written file holds no secrets: an API key is named by its environment variable. Of the environment only names
leave this module; a value is looked at only to see whether it is set (gateway design §8).
"""

import getpass
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime
from pathlib import Path

from . import tokens
from .config import parse_config
from .connector_admin import checked_operator
from .connectors.registry import Registry
from .ledger import Ledger

CONFIG_NAME, LEDGER_NAME = "ooat.toml", "ooat-ledger.sqlite"
BRIDGE_SCOPES = ("submit", "read", "answer", "rate")  # a chat bridge never manages connectors (design 05 §9)
KEY_SUFFIXES = ("_KEY", "_TOKEN")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")  # the names ooat.toml accepts for secret_env


def data_folder(environ=os.environ, platform: str = sys.platform, home: Path | None = None) -> Path:
    """OOAT's folder: OOAT_HOME when set, else the OS user data directory (design 05 §10)."""
    if environ.get("OOAT_HOME"):
        return Path(environ["OOAT_HOME"]).expanduser().resolve()  # the config's relative paths resolve next to it
    home = home or Path.home()
    if platform == "win32":
        return Path(environ.get("APPDATA") or home / "AppData" / "Roaming") / "ooat"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "ooat"
    return Path(environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "ooat"


def find_config(explicit: str | None, cwd: Path | None = None, environ=os.environ) -> Path:
    """The config to use: the one named on the command line, else ./ooat.toml when there is one, else the one in
    OOAT's data folder (which may not exist yet)."""
    if explicit is not None:
        return Path(explicit)
    local = (cwd or Path.cwd()) / CONFIG_NAME
    return local if local.exists() else data_folder(environ) / CONFIG_NAME


def missing_config(path: Path) -> str:
    return (f"No ooat.toml found ({path}): run `ooat init`, or `ooat serve` to set OOAT up in the browser. "
            "Nothing was changed.\n")


def shown_url(url: str) -> str:
    """A ledger URL as it may be shown: a user name and password in it become ***."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit(parts._replace(netloc="***@" + parts.netloc.rsplit("@", 1)[1]))


def operator_name() -> str:
    """The OS account's name as the default operator; "operator" when the OS gives none or a reserved one."""
    try:
        return checked_operator(getpass.getuser())
    except (OSError, KeyError, ValueError):  # no login name (some containers), or a name OOAT reserves
        return "operator"


def _toml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a JSON string is a valid TOML basic string


def config_text(folder: Path, operator: str, secret_envs: dict[str, str] | None = None) -> str:
    """ooat.toml for a ledger in `folder`, checked by the same parser that reads it."""
    lines = ["# Written by OOAT's setup. No secrets here: API keys are named by their environment variable.",
             "[ledger]", f"url = {_toml('sqlite:///' + (folder / LEDGER_NAME).as_posix())}", "",
             "[serve]", f"operator = {_toml(checked_operator(operator))}"]
    for connector_id, name in sorted((secret_envs or {}).items()):
        lines += ["", f"[connectors.{_toml(connector_id)}]", f"secret_env = {_toml(name)}"]
    text = "\n".join(lines) + "\n"
    parse_config(tomllib.loads(text))  # a bad id or variable name fails here, before anything is written
    return text


def write_config(path: Path, text: str) -> None:
    """Create the config; an existing one is never overwritten (FileExistsError)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as file:
        file.write(text)


def key_variables(manifest: dict, environ=os.environ) -> list[str]:
    """Names of set environment variables that look like this connector's API key: the vendor's name first, `_KEY`
    or `_TOKEN` last ("ANTHROPIC_API_KEY" for the vendor anthropic); only names ooat.toml can hold."""
    prefix = manifest["vendor"].upper().replace("-", "_") + "_"
    return sorted(name for name in environ if ENV_NAME.match(name) and name.startswith(prefix)
                  and name.endswith(KEY_SUFFIXES) and environ[name].strip())


@dataclass(frozen=True)
class Found:
    id: str
    access: str  # api, subscription_cli …
    available: bool
    detail: str
    key_variables: tuple[str, ...]  # for an API connector: the variables that may hold its key


def found_connectors(registry: Registry, environ=os.environ) -> list[Found]:
    """What the machine has: each installed connector's detection, and for API connectors the key variables set."""
    found = []
    for connector_id in registry.ids():
        connector = registry.get(connector_id)
        try:
            detection = connector.detect()
            available, detail = detection.available, detection.detail
        except Exception as error:  # plugin code: one faulty connector must not stop the setup
            available, detail = False, f"detect failed: {type(error).__name__}: {error}"
        access = connector.manifest["access"]
        names = tuple(key_variables(connector.manifest, environ)) if access == "api" else ()
        found.append(Found(connector_id, access, available, detail, names))
    return found


def default_secret_envs(found: list[Found]) -> dict[str, str]:
    """For each API connector with exactly one `…_API_KEY` candidate, that variable. Any other key (an admin key,
    several API keys) is never wired without the operator: `ooat init` asks, the browser lists them."""
    bound = {}
    for f in found:
        api_keys = [name for name in f.key_variables if name.endswith("_API_KEY")]
        if len(api_keys) == 1:
            bound[f.id] = api_keys[0]
    return bound


def bridge_token(ledger: Ledger, operator: str, now: datetime, name: str = "chat") -> tuple[str, dict]:
    """A chat bridge's token: submit, read, answer and rate, capped at internal data (owner decision, design 05 §13)."""
    return tokens.issue(ledger, operator=operator, name=name, scopes=list(BRIDGE_SCOPES), max_data_class="internal",
                        now=now)
