# The Setup Wizard: `ooat init` and the First `ooat serve` (01c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new user runs one command, `ooat serve`, and gets OOAT set up in their user data folder, signed in, and on a Setup page that shows the data, the connectors found and an optional token for a chat bot, then the inbox with a sample task; `ooat init` walks the same steps in the terminal.

**Architecture:** One new module `setup.py` holds what both paths share: the data folder per OS, where the config is looked up, the `ooat.toml` it writes (checked by the parser that reads it, never overwritten), which connectors the machine has and the names of the variables that may hold their API keys, and the chat bridge's token. `init_cli.py` is the terminal dialogue and reuses the existing `ooat connectors enable` dialogue for each connector. The first `ooat serve` without a config writes one with the defaults and signs the operator in to `/setup`; the API gains two web-session-only routes (`GET /setup`, `POST /setup/token`), and the web app a Setup screen.

**Tech Stack:** Python 3.12+ standard library (`tomllib`, `getpass`, `pathlib`), FastAPI (existing), plain ES modules with JSDoc types (existing web app, tsc 6.0.3, `node --test`), pytest.

**Spec:** `tasks/f1-skeleton/task-05-operator-ux/design.md` (approved 2026-10-09; §1 success, §3, §6, §10, §11, §13); `tasks/f1-skeleton/README.md` row 01c; ADR 0008 point 4, ADR 0012, ADR 0016.

## Global Constraints

- The written `ooat.toml` holds no secrets: an API key is named by its environment variable (`secret_env`), never its value; the config parser rejects anything else (gateway design §8). Only variable names are ever shown, in the terminal or the browser.
- An existing `ooat.toml` is never overwritten or edited by setup: a second `ooat init` or `ooat serve` leaves it as it is.
- Setup actions through the API are for a web session only, never an API token: a token must not create tokens (ADR 0016).
- The chat bridge token from setup has the scopes `submit, read, answer, rate` and the data-class cap `internal` (owner decision, design 05 §13), 90 days.
- The ledger is SQLite on a local disk. PostgreSQL and SQL Server (ADR 0008) come with plan 01b; setup offers no other database until a backend exists.
- No new dependency. No change to the schemas or the ledger's event types: setup writes only events that exist (`ADAPTER_ACKNOWLEDGED` through the existing enable dialogue, `OPERATOR_TOKEN_ISSUED`).
- Tests stay offline and never touch the real user data folder: `core/tests/conftest.py` points `OOAT_HOME` at a temporary folder for every test.
- UI strings in `en` and `cs` with the same keys (tsc checks it); page built with `h()` only; no inline script or style (05b's rules).
- Code, comments, docs and commits in English; lines at most 120 characters. Where a line of this plan's code exceeds 120 characters, wrap it; that needs no ruling.

**Decisions this plan takes where the design is silent** (for the owner's review of this plan):
1. **Where the config lives:** `--config` when given; else `./ooat.toml` when the current folder has one (today's behaviour, and how developers and tests work); else `ooat.toml` in OOAT's data folder. The data folder is `OOAT_HOME` when set, else the OS user data directory of design §10 (`%APPDATA%\ooat`, `~/Library/Application Support/ooat`, `$XDG_DATA_HOME/ooat` or `~/.local/share/ooat`). `OOAT_HOME` is what keeps tests (and portable installs) away from the real folder.
2. **`ooat init` chooses where the data goes; the config stays where OOAT looks for it** (the data folder's `ooat.toml`, or `--config`), so every later command finds it from any folder. The ledger is `ooat-ledger.sqlite` in the chosen data folder.
3. **The first `ooat serve` asks nothing in the terminal** (design §1: one command, no flags): it writes the defaults — the data folder, the OS account name as the operator (`operator` when the OS gives none), and `secret_env` for each API connector with exactly one candidate variable — prints where, and opens the browser at `/setup`. An explicit `--config` that does not exist is still refused, as today.
4. **The name is not changed in the browser.** The Setup page shows who is signed in and says how to use another name (`[serve] operator` in the shown file, then start again). A rename from a signed-in page would change the actor of later events behind the operator's back; `ooat init --operator` covers it in the terminal.
5. **Connectors in the browser** are listed with what was found (on `PATH`, an API key variable by name) and their state; enabling stays on the Connectors page with its card, responsibility and typed confirmation (05b), linked from Setup. In the terminal, `ooat init` offers each available connector's card and runs the existing `ooat connectors enable` dialogue.
6. **API key variables** are found by name: set, non-empty variables whose name starts with the vendor (`ANTHROPIC_…`) and ends with `_KEY` or `_TOKEN`. One candidate is written as `secret_env`; several are listed for the operator to pick (`ooat init` asks; the browser shows them).
7. **Databases (ADR 0008 point 4):** detection of PostgreSQL and SQL Server and installing their drivers are deferred to plan 01b, which builds those backends. Setup says the ledger is SQLite on this disk.
8. **The notifier choice** (README row 01c) is the chat bridge step: OOAT has no push notifier yet (design 05 §6: the bridge pulls).
9. **Sample task:** Setup's last step opens the inbox with the new-task form filled in with a short, checkable sample (project `sample`); nothing is submitted until the operator presses Submit.
10. **Setup stays reachable** as a header link, so an operator can come back to create a bridge token or see what was found.

## Review Focus

1. A second `ooat serve` or `ooat init` on a machine already set up → the existing `ooat.toml` is kept byte for byte (Task 1 `test_the_written_config_loads_and_is_never_overwritten`; Task 2 `test_init_leaves_an_existing_setup_alone`; Task 3 `test_the_first_serve_sets_up_and_signs_in_to_the_setup_page`, second start).
2. A folder with its own `ooat.toml` (a developer's checkout, a test) → that file is used and the user's data folder is never written (Task 1 `test_the_config_is_the_named_one_then_the_local_one_then_the_data_folders`; `core/tests/conftest.py`).
3. The environment holds real API keys → only their names reach the file, the terminal and the browser (Task 1 `test_key_variables_are_names_of_set_variables_of_the_vendor`; Task 3 `test_the_setup_state_shows_the_data_and_the_connectors_found`).
4. A bot calls the setup routes with its token to mint itself a broader token → refused (Task 3 `test_setup_is_for_the_web_session_only`).
5. The OS gives no account name, or one OOAT reserves → setup still writes a valid config with `operator` (Task 1 `test_the_default_operator_is_the_os_account_or_operator`).

---

## File Structure

```
core/src/ooat_core/setup.py, core/src/ooat_core/{operator_cli,serve_cli,task_cli}.py,
core/tests/conftest.py, core/tests/test_setup.py                                                   (Task 1)
core/src/ooat_core/init_cli.py, core/src/ooat_core/operator_cli.py, core/tests/test_init_cli.py    (Task 2)
core/src/ooat_core/{api,serve_cli}.py, core/tests/test_setup_web.py, core/tests/test_serve_cli.py  (Task 3)
core/src/ooat_core/web/app/views/setup.js, web/app/{app.js,views/inbox.js,i18n/en.js,i18n/cs.js},
core/src/ooat_core/web/login.js, core/src/ooat_core/api.py, core/tests/test_web.py                 (Task 4)
README.md, docs/description.md, core/description.md, .claude/lessons.md                            (Task 5)
```

How to apply a "replace" step: the old text occurs exactly once in the file; replace it with the new text. Files may
have CRLF line endings on Windows — match the text, not the line endings. When a step adds keys to `en.js` and
`cs.js`, add them before the closing `};` in the same order in both files. Work on a branch `feat/01c-setup` from
`main`; run Python commands from the repository root with the project virtual environment active, and npm commands
from `core/`.

---

### Task 1: Where OOAT keeps its data, and the config it writes

**Files:**
- Create: `core/src/ooat_core/setup.py`
- Create: `core/tests/conftest.py`, `core/tests/test_setup.py`
- Modify: `core/src/ooat_core/operator_cli.py` (`_config`, the missing-config messages)
- Modify: `core/src/ooat_core/serve_cli.py`, `core/src/ooat_core/task_cli.py` (the missing-config message)

**Interfaces:**
- Produces (used by Tasks 2–4):
  - `setup.CONFIG_NAME = "ooat.toml"`, `setup.LEDGER_NAME = "ooat-ledger.sqlite"`, `setup.BRIDGE_SCOPES`.
  - `setup.data_folder(environ=os.environ, platform=sys.platform, home=None) -> Path`.
  - `setup.find_config(explicit: str | None, cwd: Path | None = None, environ=os.environ) -> Path`.
  - `setup.operator_name() -> str`.
  - `setup.config_text(folder: Path, operator: str, secret_envs: dict[str, str] | None = None) -> str` (`ValueError` for a bad name or variable).
  - `setup.write_config(path: Path, text: str) -> None` (`FileExistsError` when the file exists).
  - `setup.key_variables(manifest: dict, environ=os.environ) -> list[str]`.
  - `setup.Found(id, access, available, detail, key_variables: tuple[str, ...])`; `setup.found_connectors(registry, environ=os.environ) -> list[Found]`; `setup.default_secret_envs(found) -> dict[str, str]`.
  - `setup.bridge_token(ledger, operator: str, now: datetime, name: str = "chat") -> tuple[str, dict]`.
  - `setup.missing_config(path: Path) -> str`: the refusal text for commands that need a config.
- Changes: `operator_cli._config(args)` returns `(config | None, path, refusal | None)` with `path = setup.find_config(args.config)`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/conftest.py`:

```python
"""Every test runs with OOAT_HOME in a temporary folder: no test reads or writes the real user data folder."""

import pytest


@pytest.fixture(autouse=True)
def ooat_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("ooat-home")
    monkeypatch.setenv("OOAT_HOME", str(home))
    return home
```

Create `core/tests/test_setup.py`:

```python
"""First-run setup's shared parts (design 05 §10, plan 01c): the data folder, the config, what the machine has."""

import getpass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core import setup
from ooat_core.config import load_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def test_the_data_folder_follows_the_os_unless_ooat_home_is_set(tmp_path):
    home = tmp_path / "jana"
    assert setup.data_folder({"APPDATA": str(tmp_path / "Roaming")}, "win32", home) == tmp_path / "Roaming" / "ooat"
    assert setup.data_folder({}, "win32", home) == home / "AppData" / "Roaming" / "ooat"
    assert setup.data_folder({}, "darwin", home) == home / "Library" / "Application Support" / "ooat"
    assert setup.data_folder({"XDG_DATA_HOME": str(tmp_path / "xdg")}, "linux", home) == tmp_path / "xdg" / "ooat"
    assert setup.data_folder({}, "linux", home) == home / ".local" / "share" / "ooat"
    assert setup.data_folder({"OOAT_HOME": str(tmp_path / "own"), "APPDATA": "x"}, "win32", home) == tmp_path / "own"


def test_the_config_is_the_named_one_then_the_local_one_then_the_data_folders(tmp_path):
    environ = {"OOAT_HOME": str(tmp_path / "home")}
    work = tmp_path / "work"
    work.mkdir()
    assert setup.find_config("other.toml", work, environ) == Path("other.toml")
    assert setup.find_config(None, work, environ) == tmp_path / "home" / "ooat.toml"  # need not exist yet
    (work / "ooat.toml").write_text("", encoding="utf-8")
    assert setup.find_config(None, work, environ) == work / "ooat.toml"


def test_the_written_config_loads_and_is_never_overwritten(tmp_path):
    path = tmp_path / "home" / "ooat.toml"
    text = setup.config_text(tmp_path / "data", "Jana Nováková", {"prv.anthropic.api": "ANTHROPIC_API_KEY"})
    setup.write_config(path, text)
    config = load_config(path)
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'data' / 'ooat-ledger.sqlite').as_posix()}"
    assert config.serve["operator"] == "Jana Nováková"
    assert config.connectors == {"prv.anthropic.api": {"secret_env": "ANTHROPIC_API_KEY"}}
    with pytest.raises(FileExistsError):
        setup.write_config(path, setup.config_text(tmp_path / "elsewhere", "Petr"))
    assert path.read_text(encoding="utf-8") == text


def test_a_bad_name_or_a_pasted_key_is_refused_before_anything_is_written(tmp_path):
    with pytest.raises(ValueError):
        setup.config_text(tmp_path, "   ")
    with pytest.raises(ValueError):
        setup.config_text(tmp_path, "Jana", {"prv.anthropic.api": "sk-ant-123"})  # a value, not a variable's name
    assert list(tmp_path.iterdir()) == []


def test_the_default_operator_is_the_os_account_or_operator(monkeypatch):
    monkeypatch.setattr(getpass, "getuser", lambda: "jana")
    assert setup.operator_name() == "jana"

    def no_name():
        raise OSError("no login name")
    monkeypatch.setattr(getpass, "getuser", no_name)
    assert setup.operator_name() == "operator"
    monkeypatch.setattr(getpass, "getuser", lambda: "default-on-silence")  # reserved for defaults on silence
    assert setup.operator_name() == "operator"


def test_key_variables_are_names_of_set_variables_of_the_vendor():
    environ = {"ANTHROPIC_API_KEY": "sk-1", "ANTHROPIC_TOKEN": "  ", "ANTHROPIC_MODEL": "opus", "OPENAI_API_KEY": "sk-2",
               "ANTHROPIC_ADMIN_KEY": "sk-3"}
    assert setup.key_variables(fake_manifest("prv.anthropic.api"), environ) == ["ANTHROPIC_ADMIN_KEY",
                                                                                "ANTHROPIC_API_KEY"]


def test_found_connectors_report_detection_and_the_key_names_of_api_connectors():
    class Broken(FakeConnector):
        def detect(self):
            raise RuntimeError("plugin bug")

    cli = FakeConnector(fake_manifest("prv.fakecli.subscription_cli", "subscription_cli"))
    broken = Broken(fake_manifest("prv.broken.api"))
    found = setup.found_connectors(Registry([FakeConnector(), cli, broken]), {"FAKE_API_KEY": "sk-1"})
    by_id = {f.id: f for f in found}
    assert by_id["prv.fake.api"] == setup.Found("prv.fake.api", "api", True, "fake connector", ("FAKE_API_KEY",))
    assert by_id["prv.fakecli.subscription_cli"].key_variables == ()
    assert not by_id["prv.broken.api"].available and "plugin bug" in by_id["prv.broken.api"].detail
    assert setup.default_secret_envs(found) == {"prv.fake.api": "FAKE_API_KEY"}


def test_a_bridge_token_may_submit_read_answer_and_rate_up_to_internal(tmp_path):
    ledger = Ledger.open(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    try:
        secret, event = setup.bridge_token(ledger, "Jana", NOW)
    finally:
        ledger.close()
    assert secret and secret not in str(event)
    assert event["body"]["scopes"] == ["submit", "read", "answer", "rate"]
    assert event["body"]["max_data_class"] == "internal" and event["body"]["name"] == "chat"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_setup.py -q`
Expected: FAIL with `ImportError: cannot import name 'setup' from 'ooat_core'`

- [ ] **Step 3: Write `setup.py`**

Create `core/src/ooat_core/setup.py`:

```python
"""First-run setup (design 05 §10, plan 01c): where OOAT keeps its data, the ooat.toml it writes, and what the
machine already has. Shared by `ooat init` in the terminal and the first `ooat serve` in the browser.

The written file holds no secrets: an API key is named by its environment variable. Of the environment only names
leave this module; a value is looked at only to see whether it is set (gateway design §8).
"""

import getpass
import json
import os
import sys
import tomllib
from dataclasses import dataclass
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


def data_folder(environ=os.environ, platform: str = sys.platform, home: Path | None = None) -> Path:
    """OOAT's folder: OOAT_HOME when set, else the OS user data directory (design 05 §10)."""
    if environ.get("OOAT_HOME"):
        return Path(environ["OOAT_HOME"])
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
    or `_TOKEN` last ("ANTHROPIC_API_KEY" for the vendor anthropic)."""
    prefix = manifest["vendor"].upper().replace("-", "_") + "_"
    return sorted(name for name in environ
                  if name.upper().startswith(prefix) and name.upper().endswith(KEY_SUFFIXES) and environ[name].strip())


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
    """For each API connector with exactly one candidate variable, that variable; with several the operator picks."""
    return {f.id: f.key_variables[0] for f in found if len(f.key_variables) == 1}


def bridge_token(ledger: Ledger, operator: str, now: datetime, name: str = "chat") -> tuple[str, dict]:
    """A chat bridge's token: submit, read, answer and rate, capped at internal data (owner decision, design 05 §13)."""
    return tokens.issue(ledger, operator=operator, name=name, scopes=list(BRIDGE_SCOPES), max_data_class="internal",
                        now=now)
```

In `core/src/ooat_core/operator_cli.py`, replace:

```python
from . import connector_admin, serve_cli, task_cli
```

with:

```python
from . import connector_admin, serve_cli, setup, task_cli
```

replace:

```python
    path = Path(args.config or "ooat.toml")
```

with:

```python
    path = setup.find_config(args.config)
```

replace:

```python
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    if config is None:
        stdout.write(f"No {path} found: connectors are shown without ledger state.\n")
```

with:

```python
        stdout.write(setup.missing_config(path))
        return REFUSED
    if config is None:
        stdout.write(f"No ooat.toml found ({path}): connectors are shown without ledger state.\n")
```

and replace:

```python
    parser.add_argument("--config", help="operator config (default: ./ooat.toml)")
```

with:

```python
    parser.add_argument("--config", help="operator config (default: ./ooat.toml, else the one in OOAT's data folder)")
```

In `core/src/ooat_core/serve_cli.py`, replace:

```python
from . import runner_lock, tokens
```

with:

```python
from . import runner_lock, setup, tokens
```

and replace:

```python
    if config is None:
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
        return REFUSED
    if args.command == "serve":
```

with:

```python
    if config is None:
        stdout.write(setup.missing_config(path))
        return REFUSED
    if args.command == "serve":
```

In `core/src/ooat_core/task_cli.py`, replace:

```python
        stdout.write(f"No {path} found: create one with a [ledger] url, or pass --config. Nothing was changed.\n")
```

with:

```python
        stdout.write(setup.missing_config(path))
```

and replace:

```python
from . import hil, runner_lock
```

with:

```python
from . import hil, runner_lock, setup
```

In `core/src/ooat_core/operator_cli.py`, remove the line `from pathlib import Path`: the replaced `_config` line
was its only use.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_setup.py -q`
Expected: `8 passed`

Run: `python -m pytest core/tests -q`
Expected: every test passes (the messages keep "No ooat.toml found"; `OOAT_HOME` is a temporary folder).

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/setup.py core/src/ooat_core/operator_cli.py core/src/ooat_core/serve_cli.py core/src/ooat_core/task_cli.py core/tests/conftest.py core/tests/test_setup.py
git commit -m "feat(core): setup's shared parts - the data folder, the config lookup and writer, connectors and key names found (plan 01c)"
```

---

### Task 2: `ooat init` in the terminal

**Files:**
- Create: `core/src/ooat_core/init_cli.py`
- Modify: `core/src/ooat_core/operator_cli.py` (register and dispatch `init`)
- Test: `core/tests/test_init_cli.py`

**Interfaces:**
- Consumes: `setup.find_config`, `data_folder`, `operator_name`, `found_connectors`, `config_text`, `write_config`, `bridge_token`, `LEDGER_NAME` (Task 1); `operator_cli._enable(args, registry, ledger, url, today, config, stdin, stdout) -> int` and `_ask_or_end(prompt, stdin, stdout) -> str | None` (existing).
- Produces: `ooat init [--data FOLDER] [--operator NAME] [--yes]`; `init_cli.add_commands(commands)`, `init_cli.run(args, path, stdin, stdout, registry, today, clock, ask, enable) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_init_cli.py`:

```python
"""`ooat init` (design 05 §10, plan 01c): the setup steps in the terminal."""

import getpass
import io
from datetime import date, datetime, timezone

import pytest
from connector_fakes import FakeConnector, fake_manifest

from ooat_core.config import load_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.operator_cli import main

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def elsewhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # an ooat.toml in the folder the tests start from must not count


def init(*argv, answers="", connectors=None):
    stdout = io.StringIO()
    registry = Registry(connectors if connectors is not None else [FakeConnector()])
    code = main(["init", *argv], stdin=io.StringIO(answers), stdout=stdout, registry=registry, today=TODAY,
                clock=lambda: NOW)
    return code, stdout.getvalue()


def events(config_path, *types):
    ledger = Ledger.open(load_config(config_path).ledger_url)
    try:
        return ledger.events(types=list(types))
    finally:
        ledger.close()


def test_init_writes_the_config_enables_a_connector_and_shows_a_token_once(tmp_path, monkeypatch, ooat_home):
    monkeypatch.setenv("FAKE_API_KEY", "sk-never-shown")
    cli = FakeConnector(fake_manifest("prv.fakecli.subscription_cli", "subscription_cli"))
    answers = "\n".join([str(tmp_path / "data"),  # data folder
                         "Jana",                   # name
                         "",                       # the key variable of prv.fake.api: the one found
                         "yes", "", "yes", "prv.fake.api",  # enable prv.fake.api: default classes, unattended, confirm
                         "no",                     # not prv.fakecli.subscription_cli
                         "yes"]) + "\n"            # a chat bridge token
    code, out = init(answers=answers, connectors=[FakeConnector(), cli])
    assert code == 0, out
    path = ooat_home / "ooat.toml"
    config = load_config(path)
    assert config.ledger_url == f"sqlite:///{(tmp_path / 'data' / 'ooat-ledger.sqlite').as_posix()}"
    assert config.serve["operator"] == "Jana" and config.connectors == {"prv.fake.api": {"secret_env": "FAKE_API_KEY"}}
    (enabled,) = events(path, "ADAPTER_ACKNOWLEDGED")
    assert enabled["body"]["adapter"] == "prv.fake.api" and enabled["actor"]["id"] == "Jana"
    (token,) = events(path, "OPERATOR_TOKEN_ISSUED")
    assert token["body"]["scopes"] == ["submit", "read", "answer", "rate"] and token["body"]["max_data_class"] == "internal"
    assert out.count("It is shown only now") == 1 and "sk-never-shown" not in out
    assert "FAKE_API_KEY" in out and "ooat serve" in out


def test_init_with_yes_takes_the_defaults_and_enables_nothing(monkeypatch, ooat_home):
    monkeypatch.setattr(getpass, "getuser", lambda: "jana")
    code, out = init("--yes")
    assert code == 0, out
    config = load_config(ooat_home / "ooat.toml")
    assert config.serve["operator"] == "jana"
    assert config.ledger_url == f"sqlite:///{(ooat_home / 'ooat-ledger.sqlite').as_posix()}"
    assert events(ooat_home / "ooat.toml", "ADAPTER_ACKNOWLEDGED", "OPERATOR_TOKEN_ISSUED") == []


def test_init_leaves_an_existing_setup_alone(ooat_home):
    path = ooat_home / "ooat.toml"
    path.write_text('[ledger]\nurl = "sqlite:///mine.sqlite"\n', encoding="utf-8")
    code, out = init("--operator", "Petr", "--yes")
    assert code == 0 and "already set up" in out
    assert path.read_text(encoding="utf-8") == '[ledger]\nurl = "sqlite:///mine.sqlite"\n'


def test_init_cancelled_before_the_config_is_written_writes_nothing(ooat_home):
    code, out = init(answers="")  # the input ends at the first question
    assert code == 1 and "nothing was changed" in out.lower()
    assert not (ooat_home / "ooat.toml").exists()


def test_a_bad_name_is_refused_and_nothing_is_written(tmp_path, ooat_home):
    code, out = init("--data", str(tmp_path / "data"), "--operator", "default-on-silence", "--yes")
    assert code == 1 and "reserved" in out and not (ooat_home / "ooat.toml").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_init_cli.py -q`
Expected: FAIL with `SystemExit: 2` (argparse: invalid choice: 'init')

- [ ] **Step 3: Write `ooat init`**

Create `core/src/ooat_core/init_cli.py`:

```python
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
        operator = args.operator or answer("Your name, recorded on what you do", setup.operator_name())
        stdout.write("\nConnectors found:\n" + "".join(f"  {'●' if f.available else '○'} {f.id}: {f.detail}\n"
                                                         for f in found))
        secret_envs = {}
        for f in (f for f in found if f.access == "api"):
            stdout.write(f"  {f.id} key variables set: {', '.join(f.key_variables) or 'none'}\n")
            default = f.key_variables[0] if len(f.key_variables) == 1 else ""
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
```

In `core/src/ooat_core/operator_cli.py`, replace:

```python
from . import connector_admin, serve_cli, setup, task_cli
```

with:

```python
from . import connector_admin, init_cli, serve_cli, setup, task_cli
```

replace:

```python
    task_cli.add_commands(commands)
    serve_cli.add_commands(commands)
    return parser
```

with:

```python
    task_cli.add_commands(commands)
    serve_cli.add_commands(commands)
    init_cli.add_commands(commands)
    return parser
```

and replace:

```python
        if args.command in ("serve", "login", "tokens"):
```

with:

```python
        if args.command == "init":
            return init_cli.run(args, setup.find_config(args.config), stdin, stdout, registry or Registry.discover(),
                                today or clock().date(), clock, _ask_or_end, _enable)
        if args.command in ("serve", "login", "tokens"):
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_init_cli.py core/tests/test_operator_cli.py -q`
Expected: every test passes (`5 passed` in `test_init_cli.py`).

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/init_cli.py core/src/ooat_core/operator_cli.py core/tests/test_init_cli.py
git commit -m "feat(core): ooat init - data folder, name, key variables, connector cards and a chat bridge token in the terminal (plan 01c)"
```

---

### Task 3: The first `ooat serve`, and the setup routes of the API

**Files:**
- Modify: `core/src/ooat_core/serve_cli.py` (first run, the sign-in link to Setup, the config path)
- Modify: `core/src/ooat_core/api.py` (`ServeSettings.config_path`, `GET /setup`, `POST /setup/token`)
- Test: `core/tests/test_setup_web.py`, `core/tests/test_serve_cli.py`

**Interfaces:**
- Consumes: `setup.data_folder`, `operator_name`, `found_connectors`, `default_secret_envs`, `config_text`, `write_config`, `bridge_token` (Task 1).
- Produces (used by Task 4):
  - `GET /api/v1/setup` (web session only, else 403 `SCOPE`) → `{"operator", "config": str | null, "ledger": str, "connectors": [{"id", "access", "available", "detail", "state", "key_variables": [str], "secret_env": str | null}]}`.
  - `POST /api/v1/setup/token` (web session only) with `{"name": "chat"}` → `201 {"token", "id", "name", "scopes", "max_data_class", "expires"}`; the token is in this reply only.
  - The first `ooat serve` prints and opens `…/login#code=<code>&setup=1`.
  - `ServeSettings(…, config_path: str | None = None)`; `serve_cli.serve_settings(config, host=None, port=None, config_path=None)`; `serve_cli.sign_in_link(settings, code, setup=False)`.

- [ ] **Step 1: Write the failing tests**

Create `core/tests/test_setup_web.py`:

```python
"""The setup routes of `ooat serve` (design 05 §10, plan 01c): for the operator's web session only."""

from api_fakes import Served


def test_the_setup_state_shows_the_data_and_the_connectors_found(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_API_KEY", "sk-never-shown")
    served = Served(tmp_path, config_path=str(tmp_path / "ooat.toml"))
    web = served.login()
    response = served.client.get("/api/v1/setup", headers=web)
    assert response.status_code == 200 and "sk-never-shown" not in response.text
    state = response.json()
    assert state["operator"] == "operator" and state["config"] == str(tmp_path / "ooat.toml")
    assert state["ledger"] == served.url
    fake = next(c for c in state["connectors"] if c["id"] == "prv.fake.api")
    assert fake == {"id": "prv.fake.api", "access": "api", "available": True, "detail": "fake connector",
                    "state": "enabled", "key_variables": ["FAKE_API_KEY"], "secret_env": None}


def test_a_bridge_token_from_setup_is_shown_once_and_reads_but_manages_nothing(tmp_path):
    served = Served(tmp_path)
    web = served.login()
    made = served.client.post("/api/v1/setup/token", headers=web, json={"name": "telegram"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["name"] == "telegram" and body["scopes"] == ["submit", "read", "answer", "rate"]
    assert body["max_data_class"] == "internal"
    bot = {"Authorization": f"Bearer {body['token']}"}
    assert served.client.get("/api/v1/tasks", headers=bot).status_code == 200
    assert served.client.get("/api/v1/connectors", headers=bot).json()["error"]["code"] == "SCOPE"
    assert body["token"] not in served.client.get("/api/v1/setup", headers=web).text
    bad = served.client.post("/api/v1/setup/token", headers=web, json={"name": "Not a name!"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID"


def test_setup_is_for_the_web_session_only(tmp_path):
    served = Served(tmp_path)
    bot = served.token(scopes=("submit", "read", "answer", "rate", "connectors"))
    for method, path in (("GET", "/api/v1/setup"), ("POST", "/api/v1/setup/token")):
        response = served.client.request(method, path, headers=bot, json={} if method == "POST" else None)
        assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE", path
    with served.ledger() as ledger:
        assert len(ledger.events(types=["OPERATOR_TOKEN_ISSUED"])) == 1  # only the test's own token
```

Append to `core/tests/test_serve_cli.py`:

```python
def test_the_first_serve_sets_up_and_signs_in_to_the_setup_page(tmp_path, monkeypatch, started, ooat_home):
    import getpass
    import webbrowser

    monkeypatch.chdir(tmp_path)  # no ooat.toml here, none in OOAT_HOME yet
    monkeypatch.setattr(getpass, "getuser", lambda: "jana")
    opened = []
    monkeypatch.setattr(webbrowser, "open", opened.append)
    first = io.StringIO()
    registry = Registry([ScriptedModel(), decisions()])
    code = main(["serve"], stdout=first, registry=registry, routing=RoutingPolicy(routing_document()),
                clock=lambda: NOW)
    assert code == 0 and len(started) == 1, first.getvalue()
    config = load_config(ooat_home / "ooat.toml")
    assert config.serve["operator"] == "jana"
    assert config.ledger_url == f"sqlite:///{(ooat_home / 'ooat-ledger.sqlite').as_posix()}"
    assert "First run" in first.getvalue() and str(ooat_home) in first.getvalue()
    (link,) = opened
    assert "/login#code=" in link and link.endswith("&setup=1")
    assert started[0]["app"].state.server.settings.config_path == str(ooat_home / "ooat.toml")
    written = (ooat_home / "ooat.toml").read_bytes()
    again = io.StringIO()
    assert main(["serve", "--no-browser"], stdout=again, registry=registry, routing=RoutingPolicy(routing_document()),
                clock=lambda: NOW) == 0
    assert "First run" not in again.getvalue() and "&setup=1" not in again.getvalue()
    assert (ooat_home / "ooat.toml").read_bytes() == written


def test_a_named_config_that_is_missing_is_still_refused(tmp_path, started, ooat_home):
    stdout = io.StringIO()
    assert main(["--config", str(tmp_path / "missing.toml"), "serve"], stdout=stdout) == 1
    assert started == [] and not (ooat_home / "ooat.toml").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_setup_web.py core/tests/test_serve_cli.py -q`
Expected: FAIL: `TypeError: ServeSettings.__init__() got an unexpected keyword argument 'config_path'` and a refused first serve.

- [ ] **Step 3: Write the first run and the routes**

In `core/src/ooat_core/api.py`, replace:

```python
    tls: bool = False

    @property
    def loopback(self) -> bool:
```

with:

```python
    tls: bool = False
    config_path: str | None = None  # the ooat.toml it was started with, shown on the Setup page

    @property
    def loopback(self) -> bool:
```

replace:

```python
from . import hil, tokens, views
```

with:

```python
from . import connector_admin, hil, setup, tokens, views
```

replace:

```python
class LoginIn(BaseModel):
```

with:

```python
class TokenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "chat"


def _web_only(who: Principal) -> None:
    """Setup is the operator's own: a token never sees it, and never creates another token (ADR 0016)."""
    if who.channel != "web":
        raise ApiError(403, "SCOPE", "setup is done in the web app or with `ooat init`, never with an API token")


class LoginIn(BaseModel):
```

and replace:

```python
    @router.get("/status")
    def status(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        return {"runner": server_of(request).runner.status()}
```

with:

```python
    @router.get("/status")
    def status(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        return {"runner": server_of(request).runner.status()}

    @router.get("/setup")
    def setup_state(request: Request, who: Principal = Depends(principal)) -> dict:
        """What Setup shows (plan 01c): the data, who is signed in, the connectors found; variable names only."""
        _web_only(who)
        server = server_of(request)
        states = {s.id: s.state for s in connector_admin.connector_statuses(
            server.registry, server.runtime().ledger, server.clock().date(), server.config)}
        return {"operator": who.operator, "config": server.settings.config_path, "ledger": server.settings.ledger_url,
                "connectors": [{"id": f.id, "access": f.access, "available": f.available, "detail": f.detail,
                                "state": states.get(f.id, "not acknowledged"), "key_variables": list(f.key_variables),
                                "secret_env": server.config.connectors.get(f.id, {}).get("secret_env")}
                               for f in setup.found_connectors(server.registry)]}

    @router.post("/setup/token", status_code=201)
    def setup_token(body: TokenIn, request: Request, who: Principal = Depends(principal)) -> dict:
        """A chat bridge's token (design 05 §10 step 4): in this reply only; the ledger keeps its SHA-256."""
        _web_only(who)
        server = server_of(request)
        secret, event = setup.bridge_token(server.runtime().ledger, who.operator, server.clock(), body.name)
        issued = event["body"]
        return {"token": secret, "id": issued["token"], "name": issued["name"], "scopes": issued["scopes"],
                "max_data_class": issued["max_data_class"], "expires": issued["expires"]}
```

In `core/src/ooat_core/serve_cli.py`, replace:

```python
def run(args, config, path, stdin, stdout, clock, ask, registry=None, routing=None) -> int:
    if config is None:
        stdout.write(setup.missing_config(path))
        return REFUSED
    if args.command == "serve":
        return _serve(args, config, stdout, clock, registry, routing)
```

with:

```python
def run(args, config, path, stdin, stdout, clock, ask, registry=None, routing=None) -> int:
    first = config is None and args.command == "serve" and args.config is None
    if first:
        registry = registry or Registry.discover()
        config = first_run(path, registry, stdout)
    if config is None:
        stdout.write(setup.missing_config(path))
        return REFUSED
    if args.command == "serve":
        return _serve(args, config, path, stdout, clock, registry, routing, first)
```

replace:

```python
def serve_settings(config, host: str | None = None, port: int | None = None):
    """(ServeSettings, None) from [serve] and the command line, or (None, why it cannot serve)."""
```

with:

```python
def first_run(path, registry, stdout):
    """The first `ooat serve` without a config (design 05 §1, §10): write one with the defaults and go on, so the
    browser can take over: the user data folder, the OS account as the operator, API keys found by name."""
    folder = setup.data_folder()
    text = setup.config_text(folder, setup.operator_name(),
                             setup.default_secret_envs(setup.found_connectors(registry)))
    folder.mkdir(parents=True, exist_ok=True)
    setup.write_config(path, text)
    stdout.write(f"First run: OOAT keeps its data in {folder} and its settings in {path}.\n")
    return load_config(path)


def serve_settings(config, host: str | None = None, port: int | None = None, config_path=None):
    """(ServeSettings, None) from [serve] and the command line, or (None, why it cannot serve)."""
```

replace:

```python
                             hosts=tuple(serve.get("hosts", [])), tls="tls_cert" in serve)
```

with:

```python
                             hosts=tuple(serve.get("hosts", [])), tls="tls_cert" in serve,
                             config_path=str(config_path) if config_path is not None else None)
```

replace:

```python
def sign_in_link(settings, code: str) -> str:
    """The code goes in the fragment, which the browser never sends to a server."""
    host = settings.hosts[0] if settings.hosts else "127.0.0.1" if settings.loopback else settings.host
    host = f"[{host}]" if ":" in host else host
    return f"{'https' if settings.tls else 'http'}://{host}:{settings.port}/login#code={code}"
```

with:

```python
def sign_in_link(settings, code: str, setup: bool = False) -> str:
    """The code goes in the fragment, which the browser never sends to a server; `setup` opens Setup after it."""
    host = settings.hosts[0] if settings.hosts else "127.0.0.1" if settings.loopback else settings.host
    host = f"[{host}]" if ":" in host else host
    return f"{'https' if settings.tls else 'http'}://{host}:{settings.port}/login#code={code}" \
        + ("&setup=1" if setup else "")
```

replace:

```python
def _serve(args, config, stdout, clock, registry, routing) -> int:
    """The API, the sign-in page and the runner until Ctrl+C, holding the runner lock all the while."""
    import uvicorn

    from .api import create_app

    settings, refusal = serve_settings(config, args.host, args.port)
```

with:

```python
def _serve(args, config, path, stdout, clock, registry, routing, first=False) -> int:
    """The API, the sign-in page and the runner until Ctrl+C, holding the runner lock all the while."""
    import uvicorn

    from .api import create_app

    settings, refusal = serve_settings(config, args.host, args.port, path)
```

replace:

```python
            link = sign_in_link(settings, issue_login_code(login_folder(config.ledger_url), settings.operator,
                                                           clock()))
```

with:

```python
            link = sign_in_link(settings, issue_login_code(login_folder(config.ledger_url), settings.operator,
                                                           clock()), setup=first)
```

and replace:

```python
from .connectors.registry import Registry
from .ledger import Ledger
```

with:

```python
from .config import load_config
from .connectors.registry import Registry
from .ledger import Ledger
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_setup_web.py core/tests/test_serve_cli.py core/tests/test_api.py core/tests/test_api_security.py -q`
Expected: every test passes (the new routes are covered by `test_every_endpoint_but_the_sign_in_needs_authentication` too).

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/api.py core/src/ooat_core/serve_cli.py core/tests/test_setup_web.py core/tests/test_serve_cli.py
git commit -m "feat(core): the first ooat serve sets OOAT up and signs in to Setup; setup routes for the web session only (plan 01c)"
```

---

### Task 4: The Setup screen and the sample task

**Files:**
- Create: `core/src/ooat_core/web/app/views/setup.js`
- Modify: `core/src/ooat_core/web/app/app.js` (route, header link), `core/src/ooat_core/web/app/views/inbox.js` (sample)
- Modify: `core/src/ooat_core/web/app/i18n/en.js`, `core/src/ooat_core/web/app/i18n/cs.js`
- Modify: `core/src/ooat_core/web/login.js` (open Setup after the first sign-in), `core/src/ooat_core/api.py` (the shell at `/setup`)
- Test: `core/tests/test_web.py`; `npm run check`; the smoke check in Task 5

**Interfaces:**
- Consumes: `GET /api/v1/setup`, `POST /api/v1/setup/token` (Task 3); `h`, `report` (`dom.js`), `t` (`i18n.js`).
- Produces: the screen `/setup`; the inbox fills its new-task form when opened as `/?sample`.

- [ ] **Step 1: Write the failing test**

In `core/tests/test_web.py`, replace:

```python
    for path in ("/", "/tasks/tsk_01ABC", "/usage", "/connectors"):
```

with:

```python
    for path in ("/", "/tasks/tsk_01ABC", "/usage", "/connectors", "/setup"):
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest core/tests/test_web.py -q`
Expected: FAIL on `/setup` (404).

- [ ] **Step 3: Write the screen**

In `core/src/ooat_core/api.py`, replace:

```python
    for path in ("/", "/usage", "/connectors"):
```

with:

```python
    for path in ("/", "/usage", "/connectors", "/setup"):
```

Create `core/src/ooat_core/web/app/views/setup.js`:

```javascript
// Setup (design 05 §10, plan 01c): your data, who you are, the connectors found, an optional token for a chat
// bridge (shown once), then the inbox with a sample task. The steps of `ooat init` in the terminal. Variable names
// only: the server never sends a key's value.
import { h, report } from "../dom.js";
import { t } from "../i18n.js";

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function setup(root, ctx) {
  const state = await ctx.api.json("/setup", {signal: ctx.signal});
  const config = state.config ?? "ooat.toml";
  const name = h("input", {type: "text", value: "chat", required: true, maxlength: "32",
    "aria-label": t("setup.tokenName")});
  const made = h("div");
  const status = h("p", {class: "status", role: "status"});

  /** @param {Event} event */
  async function createToken(event) {
    event.preventDefault();
    status.textContent = "";
    try {
      const token = await ctx.api.json("/setup/token", {method: "POST", body: {name: name.value.trim()}});
      made.replaceChildren(h("p", {}, t("setup.tokenMade", {name: token.name, expires: token.expires})),
        h("pre", {class: "card"}, token.token), h("p", {class: "warning"}, t("setup.tokenOnce")));
    } catch (error) {
      report(status, error);
    }
  }

  root.replaceChildren(
    h("h1", {}, t("setup.title")),
    h("section", {}, h("h2", {}, t("setup.data")), h("p", {}, t("setup.dataText", {ledger: state.ledger, config}))),
    h("section", {}, h("h2", {}, t("setup.who")), h("p", {}, t("setup.you", {operator: state.operator})),
      h("p", {class: "muted"}, t("setup.rename", {config}))),
    h("section", {}, h("h2", {}, t("setup.connectors")),
      h("table", {}, h("tbody", {}, ...state.connectors.map((/** @type {any} */ c) => h("tr", {},
        h("td", {}, `${c.available ? "●" : "○"} ${c.id}`), h("td", {}, c.state),
        h("td", {class: "muted"}, c.detail), h("td", {class: "muted"}, keyText(c)))))),
      h("p", {}, h("a", {href: "/connectors", "data-route": ""}, t("setup.openConnectors")))),
    h("section", {}, h("h2", {}, t("setup.bridge")), h("p", {}, t("setup.bridgeText")),
      h("form", {onsubmit: createToken}, h("label", {}, t("setup.tokenName"), " ", name), " ",
        h("button", {type: "submit"}, t("setup.createToken"))), status, made),
    h("section", {}, h("h2", {}, t("setup.done")),
      h("p", {}, h("a", {href: "/?sample", "data-route": ""}, t("setup.sample")))));
}

/** Where a connector's credentials come from. @param {any} c */
function keyText(c) {
  if (c.access !== "api") return t("setup.ownLogin");
  if (c.secret_env) return t("setup.keyFrom", {name: c.secret_env});
  return c.key_variables.length ? t("setup.keyFound", {names: c.key_variables.join(", ")}) : t("setup.keyMissing");
}
```

In `core/src/ooat_core/web/app/app.js`, replace:

```javascript
import { usage } from "./views/usage.js";
```

with:

```javascript
import { usage } from "./views/usage.js";
import { setup } from "./views/setup.js";
```

replace:

```javascript
  [/^\/connectors$/, (root, ctx) => connectors(root, ctx)],
];
```

with:

```javascript
  [/^\/connectors$/, (root, ctx) => connectors(root, ctx)],
  [/^\/setup$/, (root, ctx) => setup(root, ctx)],
];
```

and replace:

```javascript
  ["/connectors", () => t("nav.connectors")],
];
```

with:

```javascript
  ["/connectors", () => t("nav.connectors")],
  ["/setup", () => t("nav.setup")],
];
```

In `core/src/ooat_core/web/app/views/inbox.js`, replace:

```javascript
  let key = crypto.randomUUID();  // one Idempotency-Key per task typed in: a double click or a retry makes one task
```

with:

```javascript
  let key = crypto.randomUUID();  // one Idempotency-Key per task typed in: a double click or a retry makes one task
  if (new URLSearchParams(location.search).has("sample")) {  // Setup's last step: filled in, sent only on Submit
    goal.value = t("sample.goal");
    acceptance.value = t("sample.acceptance");
    project.value = "sample";
    history.replaceState(null, "", "/");
  }
```

In `core/src/ooat_core/web/login.js`, replace:

```javascript
const code = new URLSearchParams(location.hash.slice(1)).get("code");
```

with:

```javascript
const params = new URLSearchParams(location.hash.slice(1));
const code = params.get("code");
```

and replace:

```javascript
    location.replace("/");
```

with:

```javascript
    location.replace(params.get("setup") === "1" ? "/setup" : "/");  // the first `ooat serve` opens Setup
```

Add these keys to `core/src/ooat_core/web/app/i18n/en.js`:

```javascript
  "nav.setup": "Setup",
  "setup.title": "Setup",
  "setup.data": "1. Your data",
  "setup.dataText": "The ledger (SQLite) is {ledger}; the settings are in {config}.",
  "setup.who": "2. You",
  "setup.you": "You are signed in as {operator}; everything you do here is recorded under this name.",
  "setup.rename": "To use another name, change operator under [serve] in {config} and start `ooat serve` again.",
  "setup.connectors": "3. Connectors found",
  "setup.ownLogin": "uses its own login",
  "setup.keyFrom": "key from {name}",
  "setup.keyFound": "key variable found: {names}; name it as secret_env in ooat.toml",
  "setup.keyMissing": "no key variable set",
  "setup.openConnectors": "Read a connector's card and enable it on the Connectors page",
  "setup.bridge": "4. Chat bridge (optional)",
  "setup.bridgeText": "A token for your own chat bot: it may submit, read, answer and rate, up to internal data. See docs/chat-bridge.md.",
  "setup.tokenName": "Token name",
  "setup.createToken": "Create token",
  "setup.tokenMade": "Token {name}, valid until {expires}:",
  "setup.tokenOnce": "It is shown only now: put it in the bot's own secret store. OOAT keeps only its SHA-256.",
  "setup.done": "5. Done",
  "setup.sample": "Open the inbox with a sample task",
  "sample.goal": "Summarise in five bullet points what OOAT does with a task, from submission to rating.",
  "sample.acceptance": "At most five bullet points\nEach point at most 25 words",
```

and the same keys to `core/src/ooat_core/web/app/i18n/cs.js`:

```javascript
  "nav.setup": "Nastavení",
  "setup.title": "Nastavení",
  "setup.data": "1. Vaše data",
  "setup.dataText": "Ledger (SQLite) je {ledger}; nastavení je v {config}.",
  "setup.who": "2. Vy",
  "setup.you": "Jste přihlášeni jako {operator}; vše, co zde uděláte, se zaznamená pod tímto jménem.",
  "setup.rename": "Jiné jméno: změňte operator v sekci [serve] v {config} a spusťte `ooat serve` znovu.",
  "setup.connectors": "3. Nalezené konektory",
  "setup.ownLogin": "používá vlastní přihlášení",
  "setup.keyFrom": "klíč z {name}",
  "setup.keyFound": "nalezená proměnná s klíčem: {names}; uveďte ji jako secret_env v ooat.toml",
  "setup.keyMissing": "žádná proměnná s klíčem není nastavená",
  "setup.openConnectors": "Kartu konektoru si přečtěte a zapněte ho na stránce Konektory",
  "setup.bridge": "4. Chatovací most (volitelné)",
  "setup.bridgeText": "Token pro vašeho vlastního chatovacího bota: smí zadávat, číst, odpovídat a hodnotit, nejvýše interní data. Viz docs/chat-bridge.md.",
  "setup.tokenName": "Název tokenu",
  "setup.createToken": "Vytvořit token",
  "setup.tokenMade": "Token {name}, platí do {expires}:",
  "setup.tokenOnce": "Zobrazí se jen teď: uložte ho do úložiště tajemství bota. OOAT si ponechá jen jeho SHA-256.",
  "setup.done": "5. Hotovo",
  "setup.sample": "Otevřít přehled s ukázkovou úlohou",
  "sample.goal": "Shrň do pěti odrážek, co OOAT dělá s úlohou od zadání po hodnocení.",
  "sample.acceptance": "Nejvýše pět odrážek\nKaždá odrážka nejvýše 25 slov",
```

- [ ] **Step 4: Run the checks to verify they pass**

Run: `python -m pytest core/tests/test_web.py -q`
Expected: every test passes (the shell at `/setup`; no HTML built from data; no inline handlers).

Run (from `core/`): `npm run check` and `npm test`
Expected: tsc reports nothing (`cs.js` has exactly the keys of `en.js`); every Node test passes.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/web/app/views/setup.js core/src/ooat_core/web/app/app.js core/src/ooat_core/web/app/views/inbox.js core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js core/src/ooat_core/web/login.js core/src/ooat_core/api.py core/tests/test_web.py
git commit -m "feat(web): the Setup screen - data, you, connectors found, a chat bridge token once, and a sample task (plan 01c)"
```

---

### Task 5: Documentation and the smoke check in a browser

**Files:**
- Modify: `README.md`, `docs/description.md`, `core/description.md`, `.claude/lessons.md`

**Interfaces:**
- Consumes: everything of Tasks 1–4, as built.

- [ ] **Step 1: Smoke check in a browser**

From a short folder outside the repository (Windows MAX_PATH, `.claude/lessons.md`), with `OOAT_HOME` pointing at a
new empty folder there and the repository's connectors installed, run `ooat serve` and check in a browser (headless
Edge or Chrome through Playwright, as in plan 05b, or by hand):
1. The terminal says "First run" with the data folder; the browser opens and lands on `/setup` after sign-in.
2. Setup shows the ledger and the settings file under `OOAT_HOME`, the OS account as the operator, and every
   installed connector with ● or ○ and where its credentials come from; no key value appears anywhere on the page.
3. "Create token" shows the token once with its expiry; reloading Setup does not show it again.
4. "Open the inbox with a sample task" fills the new-task form (project `sample`); nothing is submitted until
   Submit is pressed.
5. Switching to Czech shows the Setup texts in Czech.
6. Stop the server and run `ooat serve` again: no "First run", the sign-in link opens the inbox, and `ooat.toml`
   is unchanged.
7. `ooat init` in the same `OOAT_HOME` says OOAT is already set up.
Record the results (pass/fail per item) in the final report; fix what fails before going on.

- [ ] **Step 2: Update the docs**

In `README.md`, replace:

```markdown
Create `ooat.toml` in your working folder (a relative ledger path resolves next to this file):
```

with:

```markdown
`ooat serve` sets OOAT up on its first start: it writes `ooat.toml` and the ledger to your user data folder
(`%APPDATA%\ooat`, `~/Library/Application Support/ooat` or `~/.local/share/ooat`; `OOAT_HOME` overrides it),
signs you in as your OS account and opens Setup in the browser: your data, the connectors found, an optional token
for a chat bot, and the inbox with a sample task. `ooat init` walks the same steps in the terminal. A command uses
`--config` when given, else `./ooat.toml` when the folder has one, else the one in the data folder.

To set the file up by hand, create `ooat.toml` in your working folder (a relative ledger path resolves next to
this file):
```

In `docs/description.md`, replace:

```
Bots use the Python client `ooat-client` (`sdk/python`, standard library only) and its reference chat bridge: a
```

with:

```
The first `ooat serve` sets OOAT up in the user data folder and opens Setup in the browser (data, the operator,
the connectors found, a chat bridge token, a sample task); `ooat init` walks the same steps in the terminal.

Bots use the Python client `ooat-client` (`sdk/python`, standard library only) and its reference chat bridge: a
```

and replace:

```
`ooat.toml` (operator preferences: ledger URL, per-tier pins, connector settings, `[policy]` limits on countries
```

with:

```
`ooat.toml` is `--config`, else `./ooat.toml`, else the one in OOAT's data folder (`OOAT_HOME`, else the OS user
data folder); setup writes it there and never overwrites one (plan 01c). `ooat.toml` holds
(operator preferences: ledger URL, per-tier pins, connector settings, `[policy]` limits on countries
```

In `core/description.md`, replace:

```
- `serve_cli.py` — `ooat serve`, `ooat login --operator`, `ooat tokens create | list | revoke`
```

with:

```
- `serve_cli.py` — `ooat serve`, `ooat login --operator`, `ooat tokens create | list | revoke`; the first
  `ooat serve` without a config writes one with the defaults and signs in to Setup (plan 01c)
- `setup.py` — first-run setup shared by `ooat init` and the browser: the data folder (`OOAT_HOME`, else the OS
  user data folder), the config lookup and writer (never overwrites), connectors and API key variable names found,
  the chat bridge's token
- `init_cli.py` — `ooat init [--data] [--operator] [--yes]`: the setup steps in the terminal
```

Append to `.claude/lessons.md`:

```
- `core/tests/conftest.py` sets `OOAT_HOME` to a temporary folder for every test: commands without `--config` fall
  back to the user data folder's `ooat.toml` (plan 01c), and a test must never read or write the real one.
```

- [ ] **Step 3: Run every check**

Run: `python -m pytest -q`
Expected: every test passes.

Run (from `core/`): `npm run check` and `npm test`
Expected: clean, every Node test passes.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/description.md core/description.md .claude/lessons.md
git commit -m "docs: first-run setup - ooat serve and ooat init, where the config lives (plan 01c)"
```

---

## Self-review against the design

- §10 step 1, the data folder per OS, SQLite (Task 1 `data_folder`, `config_text`; Task 2 asks; Task 3 default);
  PostgreSQL only when a backend exists (Decision 7, deferred to 01b).
- §10 step 2, your name (Task 2 asks, default the OS account; Task 3 default; Decision 4 for the browser).
- §10 step 3, connectors found: CLIs on PATH (their `detect()`), API key variables by name (Task 1
  `found_connectors`, `key_variables`); each opens its card (Task 2 runs the enable dialogue; Task 4 links to the
  Connectors page, Decision 5).
- §10 step 4, the chat bridge token shown once (Task 1 `bridge_token`; Task 2; Task 3 `POST /setup/token`; Task 4).
- §10 step 5, the inbox with a sample task (Task 4, Decision 9).
- §1 "after `pipx install` and one command (`ooat serve`) … a browser tab that walks through setup" (Task 3 first
  run, Task 4 Setup, Task 5 smoke check).
- §6: no secrets in the file, names only; setup routes authenticated and web-only; the token capped at `internal`
  (Global Constraints, Task 3 tests).
- README row 01c: "install only the chosen driver" and "the notifier choice" (Decisions 7, 8).
- Not in 01c: other database backends (01b), a push notifier, renaming the operator from the browser (Decision 4).
