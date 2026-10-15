"""A scripted model for reception tests, and a Reception on a file ledger with fake connectors."""

import json
from datetime import datetime, timezone

from connector_fakes import FakeConnector, fake_manifest
from runtime_fakes import acknowledge, decisions, routing_document

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.config import ReceptionSettings, parse_config
from ooat_core.connectors import ModelResponse
from ooat_core.connectors.registry import Registry
from ooat_core.credentials_env import SecretResolver
from ooat_core.gateway import Gateway
from ooat_core.ledger import Ledger
from ooat_core.memory import MemoryStore
from ooat_core.reception import Reception
from ooat_core.routing import RoutingPolicy
from ooat_core.runtime import Runtime
from ooat_core.workspace.runs import Workspaces
from ooat_core.workspace.tools import ToolError, Workspace

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def decision(kind="task", reply="Dělám na tom.", confidence=0.9, **fields) -> dict:
    found = {"decision": kind, "reply": reply, "confidence": confidence, **fields}
    if kind in ("task", "confirm") and "goal" not in found:
        found["goal"] = "Změnit titulek domovské stránky."
        found.setdefault("acceptance", ["Titulek domovské stránky je nový."])
    return found


class ReceptionModel(FakeConnector):
    """Answers each call with the next scripted reply (a dict goes as JSON, a str as it is); the last one repeats.
    `requests` holds every ModelRequest."""

    def __init__(self, replies=(), workspace=False, tools=()):
        manifest = fake_manifest("prv.fake.api", "api", tiers={"workhorse": "fake-model", "economy": "fake-economy"})
        if workspace or tools:
            manifest["features"] = {"workspace": True}
        super().__init__(manifest)
        self.replies = list(replies) or [decision()]
        self.answered = 0
        self.tools = list(tools)  # tool calls a call with a grant runs through OOAT's own tools, as the MCP server would

    def complete(self, request, secrets):
        self.calls.append(request)
        if request.workspace is not None and self.tools:
            workspace = Workspace(request.workspace)
            for tool, arguments in self.tools:
                try:
                    workspace.call(tool, arguments)
                except ToolError:
                    pass  # the agent reads the refusal and carries on
        reply = self.replies[min(self.answered, len(self.replies) - 1)]
        self.answered += 1
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(request)
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return ModelResponse(text, request.model, 1000, 0, 200, None, "exact")


class Desk:
    """What a test needs: the reception, its runtime and ledger, the model, the memory store, and the queued tasks."""

    def __init__(self, tmp_path, replies=(), projects=None, model=None, memory=True, settings=None, clock=None):
        self.now = NOW
        self.url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
        self.ledger = Ledger.open(self.url)
        self.model = model or ReceptionModel(replies)
        self.jev = decisions()
        acknowledge(self.ledger, self.model, ("public", "internal", "client_confidential", "personal"))
        acknowledge(self.ledger, self.jev)
        self.config = parse_config({"projects": projects or {}})
        self.clock = clock or (lambda: self.now)
        self.blobs, self.settings = tmp_path / "blobs", settings or ReceptionSettings()
        self.workspaces = Workspaces(self.config, None, tmp_path / "workspaces") if projects else None
        self.store = MemoryStore(tmp_path / "ooat-memory") if memory else None
        self.queued = []
        self.reception = self.fresh_reception(self.ledger)
        self.runtime, self.artifacts = self.reception.runtime, self.reception.runtime.artifacts

    def fresh_reception(self, ledger=None) -> Reception:
        """A Reception with its own ledger connection, as another thread of `ooat serve` makes one."""
        ledger = ledger or Ledger.open(self.url)
        gateway = Gateway(ledger, Registry([self.model, self.jev]), RoutingPolicy(routing_document()), self.config,
                          SecretResolver(self.config, {}), clock=self.clock)
        runtime = Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(self.blobs)), clock=self.clock,
                          workspaces=self.workspaces)
        return Reception(runtime, self.store, self.settings, projects=self.config.projects, clock=self.clock,
                         on_task=self.queued.append)

    def say(self, text, project="docs", channel="web", **options):
        return self.reception.receive(operator="operator", project=project, channel=channel, text=text, **options)

    def ask(self, text, **options):
        """A message and its decision."""
        message = self.say(text, **options)
        return self.reception.decide(message["body"]["conversation"])

    def events(self, kind):
        return self.ledger.events(types=[kind])

    def submitted(self):
        return [e["body"] for e in self.events("TASK_SUBMITTED")]
