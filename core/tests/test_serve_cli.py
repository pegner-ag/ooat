"""`ooat serve`, `ooat login` and the [serve] configuration (design 05 §6, §7); uvicorn is replaced, no socket."""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from runtime_fakes import ScriptedModel, decisions, routing_document

from ooat_core.config import load_config, parse_config
from ooat_core.connectors.registry import Registry
from ooat_core.operator_cli import main
from ooat_core.routing import RoutingPolicy
from ooat_core.runner_lock import RunnerLock

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
def started(monkeypatch):
    """uvicorn.run replaced: records what it was given and whether the runner lock was held meanwhile."""
    import uvicorn

    calls = []

    def run(app, **options):
        lock = RunnerLock(app.state.server.settings.ledger_url.removeprefix("sqlite:///") + ".runner.lock")
        calls.append({"app": app, **options, "lock_free": lock.acquire()})
        lock.release()
    monkeypatch.setattr(uvicorn, "run", run)
    return calls


def write_config(tmp_path, serve=""):
    path = tmp_path / "ooat.toml"
    path.write_text(f'[ledger]\nurl = "sqlite:///ledger.sqlite"\n\n[serve]\n{serve}', encoding="utf-8")
    return path


def ooat(config, *argv):
    stdout = io.StringIO()
    code = main(["--config", str(config), *argv], stdout=stdout, clock=lambda: datetime.now(timezone.utc),
                registry=Registry([ScriptedModel(), decisions()]), routing=RoutingPolicy(routing_document()))
    return code, stdout.getvalue()


def test_serve_listens_on_loopback_without_an_access_log_and_holds_the_runner_lock(tmp_path, started):
    config = write_config(tmp_path, 'operator = "operator"\n')
    code, out = ooat(config, "serve", "--no-browser")
    assert code == 0
    (call,) = started
    assert call["host"] == "127.0.0.1" and call["port"] == 8765 and call["access_log"] is False
    assert "ssl_certfile" not in call and call["lock_free"] is False  # the runner lock was held while serving
    link = next(word for word in out.split() if "/login#code=" in word)
    assert link.startswith("http://127.0.0.1:8765/login#code=")
    client = TestClient(call["app"], base_url="http://127.0.0.1:8765")
    signed_in = client.post("/api/v1/login", json={"code": link.split("#code=")[1]},
                            headers={"Origin": "http://127.0.0.1:8765"})
    assert signed_in.status_code == 200 and signed_in.json()["operator"] == "operator"
    assert RunnerLock(tmp_path / "ledger.sqlite.runner.lock").acquire()  # released when serving ends


def test_a_non_loopback_host_without_tls_refuses_to_start(tmp_path, started):
    code, out = ooat(write_config(tmp_path), "serve", "--host", "0.0.0.0", "--no-browser")
    assert code == 1 and "tls_cert" in out and started == []


def test_beyond_loopback_with_tls_the_certificate_is_used_and_the_link_names_the_host(tmp_path, started):
    config = write_config(tmp_path, 'host = "0.0.0.0"\nhosts = ["ooat.lan"]\ntls_cert = "cert.pem"\n'
                                    'tls_key = "key.pem"\noperator = "operator"\n')
    code, out = ooat(config, "serve", "--no-browser")
    assert code == 0 and "https://ooat.lan:8765/login#code=" in out
    (call,) = started
    assert call["ssl_certfile"] == (tmp_path / "cert.pem").as_posix() and call["host"] == "0.0.0.0"


def test_serve_refuses_while_another_process_runs_the_tasks(tmp_path, started):
    config = write_config(tmp_path)
    lock = RunnerLock(tmp_path / "ledger.sqlite.runner.lock")
    assert lock.acquire()
    try:
        code, out = ooat(config, "serve", "--no-browser")
    finally:
        lock.release()
    assert code == 1 and "Another process" in out and started == []


def test_login_prints_a_one_time_link_for_the_named_operator(tmp_path):
    code, out = ooat(write_config(tmp_path), "login", "--operator", "second-operator")
    assert code == 0 and "Sign in as second-operator" in out and "http://127.0.0.1:8765/login#code=" in out
    assert len(list((tmp_path / "ooat-login").glob("*.json"))) == 1
    code, out = ooat(write_config(tmp_path), "login", "--operator", "default-on-silence")
    assert code == 1 and "reserved" in out


@pytest.mark.parametrize("serve, message", [
    ({"port": 0}, "port"), ({"host": "a b"}, "host"), ({"hosts": "ooat.lan"}, "hosts"),
    ({"tls_cert": "cert.pem"}, "go together"), ({"password": "x"}, "unknown settings"), ({"operator": " "}, "name"),
])
def test_serve_settings_are_checked(serve, message):
    with pytest.raises(ValueError, match=message):
        parse_config({"serve": serve})


def test_tls_paths_are_resolved_against_the_config_folder(tmp_path):
    config = load_config(write_config(tmp_path, 'tls_cert = "tls/cert.pem"\ntls_key = "tls/key.pem"\n'))
    assert config.serve["tls_cert"] == (tmp_path / "tls" / "cert.pem").as_posix()
