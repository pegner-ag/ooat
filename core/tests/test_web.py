"""The web app's files (design 05 §2, §6; plan 05b): the pinned renderer, and no HTML built from data."""

import hashlib
import re
from pathlib import Path

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
