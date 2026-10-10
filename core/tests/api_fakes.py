"""`ooat serve` in tests: the app on a file ledger with fake connectors, a bot token and a web session (no network;
the test client talks to the app in-process as http://127.0.0.1:8765)."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from runtime_fakes import ScriptedModel, acknowledge, decisions, routing_document

from ooat_core import tokens
from ooat_core.api import ServeSettings, create_app
from ooat_core.config import parse_config
from ooat_core.connectors.registry import Registry
from ooat_core.ledger import Ledger
from ooat_core.routing import RoutingPolicy
from ooat_core.sessions import issue_login_code, login_folder

ORIGIN = "http://127.0.0.1:8765"
CRITERIA = ["Shrnutí má nejvýše 300 slov."]
PERSONAL_GOAL = "Odpověz panu Novákovi na jan.novak@example.cz ohledně smlouvy."


def now() -> datetime:
    return datetime.now(timezone.utc)  # the ledger stamps events with the real time


class Served:
    def __init__(self, tmp_path, model=None, jev=None, classes=("public", "internal"), **settings):
        self.url = f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}"
        self.model, self.jev = model or ScriptedModel(), jev or decisions()
        with self.ledger() as ledger:
            acknowledge(ledger, self.model, classes)
            acknowledge(ledger, self.jev)
        self.settings = ServeSettings(ledger_url=self.url, blobs_dir=tmp_path / "blobs", operator="operator",
                                      **settings)
        self.app = create_app(self.settings, config=parse_config({}), registry=Registry([self.model, self.jev]),
                              routing=RoutingPolicy(routing_document()), clock=now, start_runner=False)
        self.server = self.app.state.server
        scheme = "https" if self.settings.tls else "http"
        host = self.settings.hosts[0] if self.settings.hosts else "127.0.0.1"
        self.origin = f"{scheme}://{host}:{self.settings.port}"
        self.client = TestClient(self.app, base_url=self.origin)

    def ledger(self):
        return _Opened(self.url)

    def run(self) -> list[str]:
        """What the runner thread does, here in the test's thread: rebuild the queue, run it."""
        self.server.runner.tick()
        return self.server.runner.drain()

    def token(self, scopes=("submit", "read", "answer", "rate"), cap="internal") -> dict:
        with self.ledger() as ledger:
            secret, _ = tokens.issue(ledger, operator="operator", name="telegram", scopes=list(scopes),
                                     max_data_class=cap, responsibility=cap in tokens.RESPONSIBLE_CAPS, now=now())
        return {"Authorization": f"Bearer {secret}"}

    def login(self, operator="operator") -> dict:
        """A web session: the client keeps the cookie; unsafe requests need these headers."""
        code = issue_login_code(login_folder(self.url), operator, now())
        response = self.client.post("/api/v1/login", json={"code": code}, headers={"Origin": self.origin})
        assert response.status_code == 200, response.text
        return {"Origin": self.origin, "X-CSRF-Token": response.json()["csrf"]}

    def submit(self, headers, **body) -> dict:
        response = self.client.post("/api/v1/tasks", headers=headers,
                                    json={"project": "docs", "goal": "Shrň smlouvu pro jednatele.", **body})
        assert response.status_code == 202, response.text
        return response.json()


class _Opened:
    def __init__(self, url):
        self.url = url

    def __enter__(self) -> Ledger:
        self.ledger = Ledger.open(self.url)
        return self.ledger

    def __exit__(self, *exc):
        self.ledger.close()
