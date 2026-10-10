"""`ooat serve`'s shell: sign-in, sessions, tokens, Host / Origin / CSRF, limits and the log (design 05 §6, §14)."""

import logging
import os
import stat
from datetime import timedelta

import pytest
from api_fakes import ORIGIN, Served, now

from ooat_core import tokens
from ooat_core.api import ServeSettings
from ooat_core.sessions import issue_login_code, login_folder


def test_a_sign_in_code_works_once_and_its_session_acts_as_its_operator(tmp_path):
    served = Served(tmp_path)
    code = issue_login_code(login_folder(served.url), "operator", now())
    assert not any(code in path.name for path in login_folder(served.url).iterdir())  # only its hash is on disk
    first = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN})
    assert first.status_code == 200 and first.json()["operator"] == "operator"
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=43200" in cookie
    assert "secure" not in cookie  # plain http on loopback
    again = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN})
    assert again.status_code == 401 and again.json()["error"]["code"] == "UNAUTHENTICATED"
    me = served.client.get("/api/v1/me").json()
    assert me["operator"] == "operator" and me["channel"] == "web" and me["max_data_class"] is None
    assert me["csrf"] == first.json()["csrf"]


def test_an_expired_sign_in_code_is_refused(tmp_path):
    served = Served(tmp_path)
    code = issue_login_code(login_folder(served.url), "operator", now() - timedelta(minutes=6))
    assert served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": ORIGIN}).status_code == 401


def test_logging_out_ends_the_session(tmp_path):
    served = Served(tmp_path)
    headers = served.login()
    assert served.client.post("/api/v1/logout", headers=headers).status_code == 200
    assert served.client.get("/api/v1/me").status_code == 401


def test_a_page_of_another_site_cannot_sign_in_or_act_for_the_operator(tmp_path):
    served = Served(tmp_path)
    headers = served.login()
    code = issue_login_code(login_folder(served.url), "second-operator", now())
    assert served.client.post("/api/v1/login", json={"code": code},
                              headers={"Origin": "http://evil.example"}).status_code == 403
    for refused in ({"Origin": "http://evil.example"}, {}, {"Origin": "http://127.0.0.1:9999"}, {"Origin": "null"},
                    {"Origin": "https://127.0.0.1:8765"}):
        response = served.client.post("/api/v1/logout", headers={**refused, "X-CSRF-Token": headers["X-CSRF-Token"]})
        assert response.status_code == 403 and response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED", refused
    wrong = served.client.post("/api/v1/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": "x"})
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "CSRF"
    assert served.client.get("/api/v1/me").status_code == 200  # still signed in: nothing was done


def test_a_dns_rebinding_host_is_refused_before_anything_else(tmp_path):
    served = Served(tmp_path)
    token = served.token()
    for host in ("attacker.example", "attacker.example:8765", "127.0.0.1.attacker.example"):
        response = served.client.get("/api/v1/me", headers={**token, "Host": host})
        assert response.status_code == 400 and response.json()["error"]["code"] == "HOST_NOT_ALLOWED", host
    assert served.client.get("/api/v1/me", headers={**token, "Host": "localhost:8765"}).status_code == 200


def test_a_bearer_token_needs_no_origin_but_needs_its_scope(tmp_path):
    served = Served(tmp_path)
    submitter = served.token(scopes=("submit",))
    response = served.client.get("/api/v1/status", headers=submitter)
    assert response.status_code == 403 and response.json()["error"]["code"] == "SCOPE"
    assert served.client.get("/api/v1/status", headers=served.token(scopes=("read",))).json()["runner"] == {
        "state": "idle", "task": None, "queued": 0}
    for bad in ("Bearer ooat_not-a-token", "Basic dXNlcjpwYXNz", "ooat_x"):
        assert served.client.get("/api/v1/me", headers={"Authorization": bad}).status_code == 401, bad
    me = served.client.get("/api/v1/me", headers=submitter).json()
    assert me["channel"].startswith("token:tok_") and me["scopes"] == ["submit"] and "csrf" not in me


def test_a_revoked_token_stops_working_at_once(tmp_path):
    served = Served(tmp_path)
    headers = served.token()
    assert served.client.get("/api/v1/me", headers=headers).status_code == 200
    with served.ledger() as ledger:
        (token,) = tokens.tokens(ledger.events(types=tokens.EVENTS))
        tokens.revoke(ledger, operator="operator", token_id=token, reason="leaked")
    assert served.client.get("/api/v1/me", headers=headers).status_code == 401


def test_every_response_carries_the_security_headers_and_the_api_is_not_cached(tmp_path):
    served = Served(tmp_path)
    for path in ("/login", "/api/v1/me"):
        response = served.client.get(path)
        assert response.headers["content-security-policy"].startswith("default-src 'self'")
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-content-type-options"] == "nosniff"
    assert served.client.get("/api/v1/me").headers["cache-control"] == "no-store"
    page = served.client.get("/login").text
    assert '<script type="module" src="/login.js">' in page and "<script>" not in page  # no inline script
    assert "fetch(" in served.client.get("/login.js").text


def test_a_request_above_twenty_megabytes_is_refused_unread(tmp_path):
    served = Served(tmp_path)
    response = served.client.post("/api/v1/logout", headers=served.token(), content=b"x" * (20 * 1024 * 1024 + 1))
    assert response.status_code == 413 and response.json()["error"]["code"] == "TOO_LARGE"


def test_a_content_length_that_is_not_a_number_is_invalid(tmp_path):
    served = Served(tmp_path)
    for length in ("abc", "-1", "1e3"):
        response = served.client.post("/api/v1/login", content=b'{"code": "x"}',
                                      headers={"Origin": ORIGIN, "Content-Length": length})
        assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID", length


@pytest.mark.skipif(os.name == "nt", reason="Windows ignores the mode; the folder inherits the profile's ACL")
def test_the_sign_in_folder_is_private_to_its_owner(tmp_path):
    folder = tmp_path / "ooat-login"
    issue_login_code(folder, "operator", now())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    folder.chmod(0o755)  # e.g. made by hand before
    issue_login_code(folder, "operator", now())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_a_code_file_naming_a_reserved_or_broken_operator_signs_nobody_in(tmp_path):
    import json

    from ooat_core.sessions import redeem_login_code

    folder = tmp_path / "ooat-login"
    for operator in ("default-on-silence", "line\nbreak", ""):
        code = issue_login_code(folder, "operator", now())
        (path,) = folder.glob("*.json")
        path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "operator": operator}),
                        encoding="utf-8")  # whoever can write the folder
        assert redeem_login_code(folder, code, now()) is None, operator


def test_the_log_records_method_path_and_status_only(tmp_path, caplog):
    served = Served(tmp_path)
    headers = served.token()
    with caplog.at_level(logging.INFO, logger="ooat.serve"):
        served.client.get("/api/v1/me?secret=Kocka123", headers=headers)
        served.login()
    assert "GET /api/v1/me 200" in caplog.text and "POST /api/v1/login 200" in caplog.text
    assert headers["Authorization"].split()[1] not in caplog.text and "Kocka123" not in caplog.text
    assert "ooat_session" not in caplog.text


def test_served_beyond_loopback_a_web_session_is_capped_like_a_token(tmp_path):
    served = Served(tmp_path, host="192.168.1.10", hosts=("ooat.lan",), tls=True)
    code = issue_login_code(login_folder(served.url), "operator", now())
    signed_in = served.client.post("/api/v1/login", json={"code": code}, headers={"Origin": served.origin})
    assert "secure" in signed_in.headers["set-cookie"].lower()
    assert served.client.get("/api/v1/me").json()["max_data_class"] == "internal"


@pytest.mark.parametrize("host, loopback", [("127.0.0.1", True), ("::1", True), ("localhost", True),
                                            ("0.0.0.0", False), ("192.168.1.10", False)])
def test_what_counts_as_loopback(tmp_path, host, loopback):
    assert ServeSettings(ledger_url="sqlite:///x", blobs_dir=tmp_path, host=host).loopback is loopback
