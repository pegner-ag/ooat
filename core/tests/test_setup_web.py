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
