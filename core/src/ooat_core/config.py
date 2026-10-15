"""Operator preferences from ooat.toml (gateway design §5).

The file never holds secrets or connector enablement: secrets are named by environment variable, enablement is
ledger state (ADR 0010). Unknown keys are rejected so a pasted API key cannot hide in the file. The [policy] table
holds the operator's limits on where data may go, enforced by the gateway (ADR 0012); [gate] holds the Topology
Gate's values (design 04 §4).
"""

import dataclasses
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

TIERS = frozenset({"local", "economy", "workhorse", "frontier"})
_PROVIDER_ID = re.compile(r"^prv\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_CONNECTOR_KEYS = frozenset({"secret_env", "plan_fee_usd_month", "models"})
_COUNTRY = re.compile(r"^[A-Z]{2}$")
REGION = re.compile(r"^[a-z]{2}(-[a-z0-9-]+)?$")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$|^[0-9a-fA-F:]{{2,39}}$")  # a DNS name, IPv4 or IPv6 address
_GATE_NUMBERS = ("v_min_usd", "default_budget_usd", "hil_deadline_hours")
_GATE_TOKENS = ("expected_output_tokens", "critic_output_tokens", "fallback_tokens_per_question")
_GATE_SHARES = ("retry_prior", "critic_prior")  # estimate priors (plan 04d), a share from 0 to 1
_PROJECT =re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PROJECT_KEYS = frozenset({"folders", "write", "data_class", "deny", "max_operations", "max_write_mb", "timeout_min"})
PROJECT_CLASSES = ("public", "internal", "client_confidential", "personal")


@dataclass(frozen=True)
class Project:
    """[projects.<slug>]: the folders a task on this project works on (design 07 §3). Folders stay as written; the
    workspace grant resolves them to real paths for each call."""
    folders: tuple[str, ...]
    write: bool = False  # read only unless the operator says otherwise
    data_class: str = "internal"  # the highest data class in these folders, the task's minimum
    deny: tuple[str, ...] = ()  # glob patterns relative to each folder, added to the never-visible list
    max_operations: int = 300
    max_write_mb: float = 5
    timeout_min: float = 30


@dataclass(frozen=True)
class ReceptionSettings:
    """[reception]: the reception in front of tasks (design 08, plan 08a)."""
    batch_seconds: float = 8  # messages of a conversation this close together are decided as one (design 08 §14)
    silence_hours: float = 24  # a conversation without a message this long is closed
    context_tokens: int = 3000  # what the reception may see of memory and history
    max_answer_usd: float = 0.05  # the estimate a direct answer that reads files may have
    max_answer_operations: int = 40  # tool operations of such an answer
    theta: float = 0.7  # the reception's threshold until the operator's verdicts calibrate it (plan 08a decision 2)


def _absolute(path: str) -> bool:
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def folder_name(folder: str) -> str:
    """The name the agent sees a folder by: its last path segment, in either convention."""
    return re.split(r"[\\/]", folder.rstrip("\\/"))[-1] if folder.rstrip("\\/") else ""


def _number(value) -> bool:
    return type(value) in (int, float) and value > 0


@dataclass(frozen=True)
class Config:
    ledger_url: str = "sqlite:///ooat-ledger.sqlite"
    pins: dict[str, str] = field(default_factory=dict)  # tier -> connector id
    connectors: dict[str, dict] = field(default_factory=dict)  # connector id -> settings
    blocked_countries: frozenset[str] = frozenset()  # no connector whose vendor or model comes from these
    personal_data_regions: frozenset[str] | None = None  # personal data only processed here; None = no limit
    blobs_dir: str | None = None  # artifact bodies; None = an "ooat-blobs" folder next to the ledger file
    gate: dict = field(default_factory=dict)  # [gate] overrides of GateSettings
    serve: dict = field(default_factory=dict)  # [serve]: operator, host, port, hosts, tls_cert, tls_key (design 05)
    projects: dict[str, Project] = field(default_factory=dict)  # [projects.<slug>] (design 07 §3)
    reception: ReceptionSettings = ReceptionSettings()  # [reception] (design 08)


def _table(data: dict, key: str, allowed: set[str]) -> dict:
    """A config table with only the allowed keys; values are never echoed in errors (they may be pasted secrets)."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table (secrets belong in environment variables)")
    extra = set(value) - allowed if allowed else set()
    if extra:
        raise ValueError(f"{key}: unknown settings {sorted(extra)} (secrets belong in environment variables)")
    return value


def parse_config(data: dict) -> Config:
    unknown = set(data) - {"ledger", "routing", "connectors", "policy", "gate", "serve", "projects", "reception"}
    if unknown:
        raise ValueError(f"unknown config sections: {sorted(unknown)}")
    ledger = _table(data, "ledger", {"url", "blobs"})
    ledger_url = ledger.get("url", Config.ledger_url)
    if not isinstance(ledger_url, str):
        raise ValueError("ledger.url must be a string")
    blobs_dir = ledger.get("blobs")
    if blobs_dir is not None and (not isinstance(blobs_dir, str) or not blobs_dir.strip()):
        raise ValueError("ledger.blobs must be a folder path")
    gate = _table(data, "gate", {"value_usd", *_GATE_TOKENS, *_GATE_SHARES, *_GATE_NUMBERS})
    for key in _GATE_NUMBERS:
        if key in gate and not (type(gate[key]) in (int, float) and gate[key] > 0):
            raise ValueError(f"gate.{key} must be a positive number")
    for key in _GATE_TOKENS:
        if key in gate and not (type(gate[key]) is int and gate[key] > 0):
            raise ValueError(f"gate.{key} must be a positive whole number")
    for key in _GATE_SHARES:
        if key in gate and not (type(gate[key]) in (int, float) and 0 <= gate[key] <= 1):
            raise ValueError(f"gate.{key} must be a share from 0 to 1")
    values = _table(gate, "value_usd", {"A", "B", "C"})
    if not all(type(v) in (int, float) and v >= 0 for v in values.values()):
        raise ValueError("gate.value_usd must map A, B, C to amounts in USD")
    pins = _table(_table(data, "routing", {"pin"}), "pin", set())
    for tier, connector_id in pins.items():
        if tier not in TIERS or not isinstance(connector_id, str) or not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid pin for tier {tier}")
    connectors = _table(data, "connectors", set())
    for connector_id in connectors:
        if not _PROVIDER_ID.match(connector_id):
            raise ValueError(f"invalid connector id: {connector_id}")
        settings = _table(connectors, connector_id, set(_CONNECTOR_KEYS))
        secret_env = settings.get("secret_env")
        if secret_env is not None and (not isinstance(secret_env, str) or not _ENV_NAME.match(secret_env)):
            raise ValueError(f"{connector_id}: secret_env must name an environment variable, not hold a value")
        models = _table(settings, "models", set(TIERS))
        if not all(isinstance(model, str) for model in models.values()):
            raise ValueError(f"{connector_id}: models must map tiers to model ids")
    policy = _table(data, "policy", {"blocked_countries", "personal_data_regions"})
    blocked = policy.get("blocked_countries", [])
    if not isinstance(blocked, list) or not all(isinstance(c, str) and _COUNTRY.match(c) for c in blocked):
        raise ValueError("policy.blocked_countries must list two-letter country codes such as \"CN\"")
    regions = policy.get("personal_data_regions")
    if regions is not None and (not isinstance(regions, list)
                                or not all(isinstance(r, str) and REGION.match(r) for r in regions)):
        raise ValueError("policy.personal_data_regions must list region codes such as \"eu\"")
    return Config(ledger_url=ledger_url, pins=dict(pins), connectors={k: dict(v) for k, v in connectors.items()},
                  blocked_countries=frozenset(blocked),
                  personal_data_regions=frozenset(regions) if regions is not None else None,
                  blobs_dir=blobs_dir, gate=dict(gate), serve=_serve(data), projects=_projects(data),
                  reception=_reception(data))


def _serve(data: dict) -> dict:
    """[serve] of `ooat serve` (design 05 §6). The certificate and key are named by path, never pasted."""
    serve = _table(data, "serve", {"operator", "host", "port", "hosts", "tls_cert", "tls_key"})
    if "operator" in serve and (not isinstance(serve["operator"], str) or not serve["operator"].strip()):
        raise ValueError("serve.operator must be your name")
    if "host" in serve and (not isinstance(serve["host"], str) or not _HOST.match(serve["host"])):
        raise ValueError("serve.host must be an address or a host name, e.g. 127.0.0.1")
    if "port" in serve and not (type(serve["port"]) is int and 1 <= serve["port"] <= 65535):
        raise ValueError("serve.port must be a port number from 1 to 65535")
    hosts = serve.get("hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(h, str) and _HOST.match(h) for h in hosts):
        raise ValueError("serve.hosts must list host names, e.g. [\"ooat.lan\"]")
    for key in ("tls_cert", "tls_key"):
        if key in serve and (not isinstance(serve[key], str) or not serve[key].strip()):
            raise ValueError(f"serve.{key} must be a file path")
    if ("tls_cert" in serve) != ("tls_key" in serve):
        raise ValueError("serve.tls_cert and serve.tls_key go together")
    return dict(serve)


def _reception(data: dict) -> ReceptionSettings:
    table = _table(data, "reception", {f.name for f in dataclasses.fields(ReceptionSettings)})
    for key in ("context_tokens", "max_answer_operations"):
        if key in table and not (type(table[key]) is int and table[key] > 0):
            raise ValueError(f"reception.{key} must be a positive whole number")
    for key in ("silence_hours", "max_answer_usd"):
        if key in table and not _number(table[key]):
            raise ValueError(f"reception.{key} must be a positive number")
    if "batch_seconds" in table and not (type(table["batch_seconds"]) in (int, float) and table["batch_seconds"] >= 0):
        raise ValueError("reception.batch_seconds must be a number of seconds, 0 or more")
    if "theta" in table and not (type(table["theta"]) in (int, float) and 0 <= table["theta"] <= 1):
        raise ValueError("reception.theta must be a share from 0 to 1")
    return ReceptionSettings(**table)


def _projects(data: dict) -> dict[str, Project]:
    table = _table(data, "projects", set())
    projects = {}
    for slug in table:
        if not (isinstance(slug, str) and len(slug) <= 64 and _PROJECT.match(slug)):
            raise ValueError("projects: a project name is lower-case letters, digits, - and _ (up to 64 characters)")
        settings = _table(table, slug, set(_PROJECT_KEYS))
        where = f"projects.{slug}"
        folders = settings.get("folders")
        if not isinstance(folders, list) or not folders or not all(isinstance(f, str) for f in folders):
            raise ValueError(f"{where}.folders must list one or more folders")
        if not all(_absolute(f) for f in folders):
            raise ValueError(f"{where}.folders must be absolute paths")
        names = [folder_name(f) for f in folders]
        if not all(names) or any(re.fullmatch(r"[A-Za-z]:", n) for n in names):
            raise ValueError(f"{where}.folders: a drive or the root cannot be a project folder")
        if len({n.lower() for n in names}) != len(names):
            raise ValueError(f"{where}.folders: two folders have the same last name; the agent tells them apart by it")
        write = settings.get("write", False)
        if not isinstance(write, bool):
            raise ValueError(f"{where}.write must be true or false")
        data_class = settings.get("data_class", "internal")
        if data_class not in PROJECT_CLASSES:
            raise ValueError(f"{where}.data_class must be one of {', '.join(PROJECT_CLASSES)}")
        deny = settings.get("deny", [])
        if not isinstance(deny, list) or not all(
                isinstance(p, str) and p.strip() and not _absolute(p) and not re.match(r"^[A-Za-z]:", p)
                and ".." not in re.split(r"[\\/]", p) for p in deny):
            raise ValueError(f"{where}.deny must list patterns relative to each folder, such as \"logs/**\"")
        limits = {}
        for key, whole in (("max_operations", True), ("max_write_mb", False), ("timeout_min", False)):
            if key in settings:
                value = settings[key]
                if not _number(value) or (whole and type(value) is not int):
                    raise ValueError(f"{where}.{key} must be a positive {'whole ' if whole else ''}number")
                limits[key] = value
        projects[slug] = Project(folders=tuple(folders), write=write, data_class=data_class, deny=tuple(deny),
                                 **limits)
    return projects


def load_config(path: str | Path) -> Config:
    """Load ooat.toml; a relative sqlite ledger path is resolved against the config file's folder."""
    with open(path, "rb") as file:
        config = parse_config(tomllib.load(file))
    prefix = "sqlite:///"
    location = config.ledger_url[len(prefix):] if config.ledger_url.startswith(prefix) else None
    # Absolute in either convention stays as written: a Windows drive path is not "relative" on Linux.
    absolute = PurePosixPath(location).is_absolute() or PureWindowsPath(location).is_absolute() if location else True
    if location and location != ":memory:" and not absolute:
        resolved = (Path(path).resolve().parent / location).as_posix()
        config = dataclasses.replace(config, ledger_url=prefix + resolved)
    blobs = config.blobs_dir
    if blobs is not None and not (PurePosixPath(blobs).is_absolute() or PureWindowsPath(blobs).is_absolute()):
        config = dataclasses.replace(config, blobs_dir=(Path(path).resolve().parent / blobs).as_posix())
    tls = {key: (Path(path).resolve().parent / config.serve[key]).as_posix()  # an absolute path stays as written
           for key in ("tls_cert", "tls_key") if key in config.serve}
    if tls:
        config = dataclasses.replace(config, serve={**config.serve, **tls})
    for slug, project in config.projects.items():
        real = []
        for folder in project.folders:
            if not os.path.isdir(folder):
                raise ValueError(f"projects.{slug}: the folder {folder} does not exist or is not a folder")
            real.append(os.path.normcase(os.path.realpath(folder)))
        for outer in real:
            for inner in real:
                try:
                    nested = inner != outer and os.path.commonpath([inner, outer]) == outer
                except ValueError:  # another drive
                    nested = False
                if nested:
                    raise ValueError(f"projects.{slug}: {inner} is inside {outer}; list only the outer folder")
    return config
