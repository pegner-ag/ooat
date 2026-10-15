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

    def __init__(self, replies=(), workspace=False):
        manifest = fake_manifest("prv.fake.api", "api", tiers={"workhorse": "fake-model", "economy": "fake-economy"})
        if workspace:
            manifest["features"] = {"workspace": True}
        super().__init__(manifest)
        self.replies = list(replies) or [decision()]
        self.answered = 0

    def complete(self, request, secrets):
        self.calls.append(request)
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
        clock = clock or (lambda: self.now)
        gateway = Gateway(self.ledger, Registry([self.model, self.jev]), RoutingPolicy(routing_document()),
                          self.config, SecretResolver(self.config, {}), clock=clock)
        self.artifacts = ArtifactStore(self.ledger, BlobStore(tmp_path / "blobs"))
        workspaces = Workspaces(self.config, None, tmp_path / "workspaces") if projects else None
        self.runtime = Runtime(self.ledger, gateway, self.artifacts, clock=clock, workspaces=workspaces)
        self.store = MemoryStore(tmp_path / "ooat-memory") if memory else None
        self.queued = []
        self.reception = Reception(self.runtime, self.store, settings or ReceptionSettings(),
                                   projects=self.config.projects, clock=clock, on_task=self.queued.append)

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
