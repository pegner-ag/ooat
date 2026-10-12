"""The web app's files (design 05 §2, §6; plan 05b): the pinned renderer, and no HTML built from data."""

import hashlib
import re
from pathlib import Path

from api_fakes import Served

WEB = Path(__file__).resolve().parents[1] / "src" / "ooat_core" / "web"
APP = WEB / "app"
MARKDOWN_IT_SHA256 = "85feb50fd6ce1b7c49acb02b0337eb622ecc4fc2ed4ae0dcbb8c084556d463b6"  # markdown-it 15.0.2


def test_the_vendored_markdown_renderer_is_the_pinned_release_with_its_licence():
    vendored = APP / "vendor" / "markdown-it.esm.min.mjs"
    assert hashlib.sha256(vendored.read_bytes()).hexdigest() == MARKDOWN_IT_SHA256
    assert "Permission is hereby granted, free of charge" in (APP / "vendor" / "LICENSE").read_text(encoding="utf-8")


def test_only_the_markdown_view_writes_html_and_nothing_evaluates_code():
    scripts = [p for p in APP.rglob("*.js")] + [WEB / "login.js"]
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        for banned in ("outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert banned not in source, (script.name, banned)
        if script.name != "markdown.js":
            assert "innerHTML" not in source, script.name


def test_html_files_have_no_inline_script_handler_or_style():
    for page in WEB.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        assert all("src=" in tag for tag in re.findall(r"<script[^>]*>", source)), page.name
        assert not re.search(r"\son[a-z]+\s*=", source) and " style=" not in source and "<style" not in source


def test_the_app_shell_is_served_for_each_screen_without_a_session(tmp_path):
    served = Served(tmp_path)
    for path in ("/", "/tasks/tsk_01ABC", "/usage", "/connectors", "/setup"):
        response = served.client.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/html"), path
        assert '<script type="module" src="/app/app.js">' in response.text
        assert "default-src 'self'" in response.headers["content-security-policy"]


def test_app_files_are_served_with_their_type_and_nothing_else(tmp_path):
    served = Served(tmp_path)
    for path, kind in (("/app/app.js", "text/javascript"), ("/app/app.css", "text/css"),
                       ("/app/views/inbox.js", "text/javascript"),
                       ("/app/vendor/markdown-it.esm.min.mjs", "text/javascript")):
        response = served.client.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith(kind), path
    for path in ("/app/missing.js", "/app/../api.py", "/app/%2e%2e/api.py", "/app/vendor/LICENSE",
                 "/app/vendor/markdown-it.esm.min.d.mts", "/app/i18n"):
        assert served.client.get(path).status_code == 404, path
