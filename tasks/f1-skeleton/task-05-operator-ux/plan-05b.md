# The Web App: Inbox, Task Page, Cards, Usage and Connectors (05b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ooat serve` opens a browser app in which the operator submits a task, watches its timeline, reads every attempt's document (rendered, as source, as a diff), answers questions with one click, rates the task, enables connectors and sees usage, in English or Czech, without a command line.

**Architecture:** Plain ES modules with JSDoc types under `core/src/ooat_core/web/app/`, served by `ooat serve` as static files from the wheel (no build step, ADR 0016). Pure modules (`api.js`, `sse.js`, `format.js`, `i18n.js`, `markdown.js`, `rating.js`, `timeline.js`) hold the logic and are tested with Node's built-in test runner; DOM modules (`dom.js`, `cards.js`, `app.js`, `views/*.js`) only build elements and are type-checked by `tsc --noEmit --checkJs`. One vendored library: markdown-it with raw HTML off. The server gains the app's shell routes, a session key on every request of a web session, and three fields the screens need.

**Tech Stack:** JavaScript (ES2022 modules, JSDoc types), TypeScript 6.0.3 as checker only, Node 22 `node --test` (CI and developers only; the operator needs no Node), markdown-it 15.0.2 (MIT, vendored), Python 3.12+ / FastAPI for the server side, pytest.

**Spec:** `tasks/f1-skeleton/task-05-operator-ux/design.md` (approved 2026-10-09; §2, §3, §4, §6, §11, §13); spec §3, §9, §10; ADR 0012, 0015, 0016.

## Global Constraints

- No build step and no Node for the operator: the browser loads the files as they are in the wheel (design §2, ADR 0016 point 7).
- The page never turns data into HTML: elements and text nodes only (`dom.js` `h()`); the one `innerHTML` is in `markdown.js`, from markdown-it with `html: false`. `javascript:` links are refused (design §6). A test holds this.
- CSP stays `default-src 'self'` with no inline script: no `<script>` without `src`, no `on…=` attributes and no `style=` attributes in HTML files; event handlers are attached in JS.
- A web session is the HttpOnly cookie plus the session key: the key is kept in `localStorage["ooat.session"]` and sent as `X-CSRF-Token` on every API request (Decision 1).
- The actor of everything the page writes is the session's operator; the page never sends an operator name.
- UI strings in `en` and `cs` (spec §10); every visible string goes through `t(key)`; `cs.js` has exactly the keys of `en.js` (tsc checks it). Event types, states, error codes and data classes are shown as they are (English).
- New dependencies: none for Python. Developer-only, in `core/package.json`, pinned exactly: `typescript` `6.0.3`, `markdown-it` `15.0.2` (its types and the source of the vendored file). `core/package-lock.json` is committed; CI runs `npm ci`.
- Vendored file: `core/src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs` is byte-identical to `markdown-it@15.0.2/dist/browser/markdown-it.esm.min.mjs`, SHA-256 `85feb50fd6ce1b7c49acb02b0337eb622ecc4fc2ed4ae0dcbb8c084556d463b6`, with its `LICENSE` beside it.
- Tests stay offline. Python: FastAPI `TestClient` as in 05a. JavaScript: `node --test` with injected `fetch`, no browser.
- Code, comments, docs and commits in English; lines at most 120 characters (Python and JavaScript; string values in `i18n/*.js` may be longer); 2-space indentation and double quotes in JavaScript. Where a line of this plan's code exceeds 120 characters, wrap it; that needs no ruling.

**Decisions this plan takes where the design is silent or 05a left a deferred item** (for the owner's review of this plan):
1. **Session key on every request** (fixes 05a deferred minor "loopback session cookie is port-blind"). A cookie is not bound to a port, so any other service on `127.0.0.1` the browser visits receives `ooat_session`. 05a let that cookie read everything and get the CSRF token from `GET /me`. Now every request of a cookie session must carry the key (`X-CSRF-Token`), GETs too; `/me` no longer returns it; the page keeps it in `localStorage`, which is bound to the origin including its port. The header name and the error code `CSRF` stay, so ADR 0016's code list is unchanged. This amends design §6 ("a CSRF token for unsafe methods") and fixes the `/me` 500 after a session expires (another deferred minor), since `/me` no longer reads the session twice.
2. **The app's code is served without a session:** `/`, `/tasks/{id}`, `/usage`, `/connectors` (the shell) and `/app/…` (scripts, styles, the vendored renderer). They hold no data; every data call is authenticated as before. `/app/` serves only files found in the package at start-up (a lookup table, no path from the URL reaches the file system). This amends 05a's list of open routes.
3. **The shared web intake key stays as it is** (05a deferred minor). The page makes a fresh random `Idempotency-Key` (`crypto.randomUUID()`) for every task typed in, so two operators never share one, and web sessions see every task anyway. Changing ADR 0016's uniqueness rule would buy nothing.
4. **Where the app lives:** `core/src/ooat_core/web/` (shipped in the wheel). `dashboard/` stays an empty placeholder. Node tests in `core/web-tests/`, the toolchain files in `core/`.
5. **TypeScript 6.0.3**, the last release of the JavaScript-based compiler; TypeScript 7 (the native port) changes JSDoc handling. Moving to 7 is a separate, measured change.
6. **Live updates:** the task page follows the timeline as Server-Sent Events read with `fetch` (an `EventSource` cannot send the session key). The inbox refreshes every 15 s, but not while the focus is inside its lists, so a half-typed answer is never wiped. The header refreshes every 30 s.
7. **Inbox rating card:** `Accepted A`, `Accepted B`, `Accepted C` rate in one click with no decision verdicts; `Not accepted…` opens the task page's full rating card, where the value and the decisions are marked. Decisions left unmarked stay unrated (design §4).
8. **"Stuck":** the inbox lists open tasks paused by a provider failure, with the time the runner tries again (`resume_after`, new in `GET /tasks`). No other heuristics.
9. **Language:** the browser's language (`cs…` → Czech, else English), switchable in the header; the choice is kept in `localStorage["ooat.language"]`.
10. **Attachments** in the new-task form total at most 14 MB (20 MB per request after base64); the page says so before sending. Artifacts download through `fetch` and a temporary object URL (a plain link cannot carry the session key).

## Review Focus

1. Another web service on `127.0.0.1` (any port) receives the session cookie and calls the API with it → it reads nothing and writes nothing (Task 1 test `test_a_session_cookie_without_its_key_reads_and_writes_nothing`).
2. A document derived from an untrusted attachment contains `<script>`, `<img src=x onerror=…>` or `[x](javascript:…)` → it shows as text, the image has no handler, the link has no `javascript:` target (Task 2 test `markdown never passes raw HTML or a javascript: link`).
3. The timeline stream ends after 15 minutes or the network drops → the page reconnects from the last event it showed, without gaps or duplicates (Task 2 test `follow reconnects after the last event it saw`).
4. The session expires while a screen is open → the page says how to sign in again, never a half-drawn screen or a raw error (Task 2 test `a 401 or a CSRF refusal signs the page out`; Task 7 smoke step).
5. The operator double-clicks Submit, or retries after a network error → one task (Task 3: one `Idempotency-Key` per task typed in, the button disabled while sending; Task 7 smoke step).

---

## File Structure

```
core/src/ooat_core/api.py, views.py, web/login.html, web/login.js,
core/tests/api_fakes.py, test_api_security.py, test_views.py                              (Task 1)
core/package.json, core/package-lock.json, core/tsconfig.json, .github/workflows/tests.yml,
core/src/ooat_core/web/app/{dom,i18n,format,sse,api,markdown}.js, web/app/i18n/{en,cs}.js,
core/src/ooat_core/web/app/vendor/{markdown-it.esm.min.mjs,markdown-it.esm.min.d.mts,LICENSE},
core/web-tests/{format,sse,api,markdown}.test.mjs, core/tests/test_web.py                  (Task 2)
core/src/ooat_core/web/index.html, web/app/{app.js,app.css,rating.js,cards.js}, web/app/views/inbox.js,
core/src/ooat_core/api.py, core/web-tests/rating.test.mjs, core/tests/test_web.py           (Task 3)
core/src/ooat_core/web/app/{timeline.js,views/task.js,app.js}, core/web-tests/timeline.test.mjs   (Task 4)
core/src/ooat_core/web/app/{views/usage.js,app.js,format.js}, core/web-tests/format.test.mjs     (Task 5)
core/src/ooat_core/web/app/{views/connectors.js,app.js}                                     (Task 6)
core/description.md, docs/description.md, README.md, .claude/lessons.md, CONTRIBUTING.md     (Task 7)
```

How to apply a "replace" step: the old text occurs exactly once in the file; replace it with the new text. Files may
have CRLF line endings on Windows — match the text, not the line endings. When a step adds keys to `en.js` and
`cs.js`, add them before the closing `};` in the same order in both files. Work on a branch `feat/05b-web` from
`main`; run Python commands from the repository root with the project virtual environment active, and npm/node
commands from `core/`.

---

### Task 1: The server side: a session key on every request, and what the screens need

**Files:**
- Modify: `core/src/ooat_core/api.py` (principal, `/me`)
- Modify: `core/src/ooat_core/views.py` (`task_summary`, `task_detail`, `rating_queue`)
- Modify: `core/src/ooat_core/web/login.js`, `core/src/ooat_core/web/login.html`
- Test: `core/tests/api_fakes.py`, `core/tests/test_api_security.py`, `core/tests/test_views.py`

**Interfaces:**
- Produces (API, consumed by Tasks 2–6):
  - every request of a cookie session needs `X-CSRF-Token: <key>`, else 403 `CSRF`;
  - `POST /api/v1/login` → `{"operator", "csrf"}` (unchanged), and `GET /me` → `{"operator", "channel", "scopes", "max_data_class"}` without `csrf`;
  - `GET /tasks` and `GET /tasks/{id}` entries gain `resume_after` (ISO time with `Z`, or `null`);
  - each `GET /tasks/{id}` artifact gains `name` (the attachment's file name, else `null`);
  - each `GET /ratings/queue` decision gains `options` (sorted option ids for a choice decision, else `null`).
- Produces (browser): `login.js` stores the key in `localStorage["ooat.session"]` and opens `/`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/api_fakes.py`, replace:

```python
        """A web session: the client keeps the cookie; unsafe requests need these headers."""
        code = issue_login_code(login_folder(self.url), operator, now())
        response = self.client.post("/api/v1/login", json={"code": code}, headers={"Origin": self.origin})
        assert response.status_code == 200, response.text
        return {"Origin": self.origin, "X-CSRF-Token": response.json()["csrf"]}
```

with:

```python
        """A web session: the client keeps the cookie and sends the session key on every request, as the page does;
        unsafe requests also need these headers."""
        code = issue_login_code(login_folder(self.url), operator, now())
        response = self.client.post("/api/v1/login", json={"code": code}, headers={"Origin": self.origin})
        assert response.status_code == 200, response.text
        self.client.headers["X-CSRF-Token"] = response.json()["csrf"]
        return {"Origin": self.origin, "X-CSRF-Token": response.json()["csrf"]}
```

In `core/tests/test_api_security.py`, replace:

```python
    me = served.client.get("/api/v1/me").json()
    assert me["operator"] == "operator" and me["channel"] == "web" and me["max_data_class"] is None
    assert me["csrf"] == first.json()["csrf"]
```

with:

```python
    me = served.client.get("/api/v1/me", headers={"X-CSRF-Token": first.json()["csrf"]}).json()
    assert me["operator"] == "operator" and me["channel"] == "web" and me["max_data_class"] is None
    assert "csrf" not in me  # the key is what the cookie alone lacks; the page keeps it from the sign-in
```

and append to the same file:

```python
def test_a_session_cookie_without_its_key_reads_and_writes_nothing(tmp_path):
    # A cookie is not bound to a port: another service on 127.0.0.1 the browser visits receives it (05a review).
    served = Served(tmp_path)
    headers = served.login()
    task = served.submit(headers)["task"]
    for method, path in (("GET", "/api/v1/tasks"), ("GET", f"/api/v1/tasks/{task}"), ("GET", "/api/v1/me"),
                         ("GET", "/api/v1/hil"), ("GET", "/api/v1/stats"), ("POST", f"/api/v1/tasks/{task}/cancel")):
        response = served.client.request(method, path, headers={"Origin": ORIGIN, "X-CSRF-Token": ""})
        assert response.status_code == 403 and response.json()["error"]["code"] == "CSRF", (method, path)
    with served.ledger() as ledger:  # the refused cancel recorded nothing
        assert not [e for e in ledger.events(task=task, types=["DECISION"]) if e["actor"]["kind"] == "hil"]
```

In `core/tests/test_views.py`, add the imports (keep the existing ones):

```python
from runtime_fakes import ScriptedModel

from ooat_core.connectors import ConnectorError
from ooat_core.rating import CHOICE_OPTIONS
```

and append:

```python
def test_a_task_paused_by_a_provider_failure_says_when_it_is_tried_again(tmp_path):
    setup = Setup(tmp_path, model=ScriptedModel(outages={("worker", 1): ConnectorError("UNAVAILABLE", "HTTP 529")}))
    task = setup.submit()
    setup.runtime.run(task)
    tasks, found = classes(setup)
    summary = task_summary(task, tasks[task], found[task], None)
    assert summary["state"] == "RUNNING" and summary["resume_after"].endswith("Z")
    setup.runtime.run(task)  # the provider is back
    tasks, found = classes(setup)
    assert task_summary(task, tasks[task], found[task], None)["resume_after"] is None


def test_an_attachment_is_listed_with_its_file_name_within_the_cap(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit(files=[b"Draft of the release notes."], file_names=["notes.txt"])
    setup.runtime.run(task)
    tasks, found = classes(setup)
    detail = task_detail(task, tasks[task], found[task], None, setup.ledger.artifact, [])
    attachment = next(a for a in detail["artifacts"] if a["type"] == "attachment")
    assert attachment["name"] == "notes.txt"
    assert all(a["name"] is None for a in detail["artifacts"] if a["type"] != "attachment")


def test_a_choice_decision_in_the_rating_queue_lists_what_it_may_be_corrected_to(tmp_path):
    setup = Setup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    tasks, found = classes(setup)
    decisions = {d["question"]: d for d in rating_queue(tasks, found, None)[0]["decisions"]}
    assert decisions["a5"]["options"] == sorted(CHOICE_OPTIONS["a5"])
    assert decisions["a10"]["options"] == sorted(CHOICE_OPTIONS["a10"])
    assert decisions["a1.1"]["options"] is None  # yes/no: corrected to the other answer
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest core/tests/test_api_security.py core/tests/test_views.py -q`
Expected: FAIL. The first test fails on `"csrf" not in me`; the new security test gets 200 instead of 403 on the GETs; the views tests fail with `KeyError: 'resume_after'`, `KeyError: 'name'` and `KeyError: 'options'`.

- [ ] **Step 3: Implement**

In `core/src/ooat_core/api.py`, replace:

```python
    if request.method not in SAFE_METHODS and not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode("utf-8"), session.csrf.encode("utf-8")):
        raise ApiError(403, "CSRF", "missing or wrong X-CSRF-Token header")
```

with:

```python
    # Every request of a cookie session carries its key, reads too: a cookie is not bound to a port, so another
    # service on this host may receive it; the page keeps the key in storage bound to this origin, port included.
    if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode("utf-8"),
                               session.csrf.encode("utf-8")):
        raise ApiError(403, "CSRF", "missing or wrong X-CSRF-Token header")
```

and replace:

```python
    @router.get("/me")
    def me(request: Request, who: Principal = Depends(principal)) -> dict:
        found = {"operator": who.operator, "channel": who.channel, "scopes": sorted(who.scopes),
                 "max_data_class": who.max_data_class}
        if who.channel == "web":  # the page needs it after a reload; no other origin can read this response
            server = server_of(request)
            found["csrf"] = server.sessions.get(request.cookies[SESSION_COOKIE], server.clock()).csrf
        return found
```

with:

```python
    @router.get("/me")
    def me(who: Principal = Depends(principal)) -> dict:
        # Never the session key: it is the half of a web session the cookie alone lacks.
        return {"operator": who.operator, "channel": who.channel, "scopes": sorted(who.scopes),
                "max_data_class": who.max_data_class}
```

In `core/src/ooat_core/views.py`, replace:

```python
from .gate import GateSettings, gated_data_class
from .pii import ORDER, higher_class
from .rating import task_decisions
from .runtime import CLOSED
from .state import task_state
```

with:

```python
from .gate import GateSettings, gated_data_class
from .pii import ORDER, higher_class
from .rating import CHOICE_OPTIONS, task_decisions
from .runner import resume_after
from .runtime import CLOSED
from .state import task_state
```

replace:

```python
    estimates = [c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c] if decided else []
    return {
```

with:

```python
    estimates = [c["model_usd"] for c in decided["body"]["candidates"] if "model_usd" in c] if decided else []
    paused = resume_after(events) if task_state(events) not in CLOSED else None  # the inbox's "stuck" list
    return {
```

replace:

```python
        "closed": closed["body"]["state"] if closed else None,
    }
```

with:

```python
        "closed": closed["body"]["state"] if closed else None,
        "resume_after": paused.isoformat().replace("+00:00", "Z") if paused else None,
    }
```

replace:

```python
    refs = list(dict.fromkeys(ref for e in events for ref in e["refs"] if ref.startswith("art_")))
    artifacts = []
    for ref in refs:
        record = artifact_record(ref)
        artifacts.append({"ref": ref, "type": record["type"], "data_class": record["data_class"],
                          "untrusted": record["untrusted"], "readable": within(record["data_class"], cap)})
```

with:

```python
    refs = list(dict.fromkeys(ref for e in events for ref in e["refs"] if ref.startswith("art_")))
    names = dict(zip(submitted["refs"], submitted["body"].get("attachment_names", []))) if visible else {}
    artifacts = []
    for ref in refs:
        record = artifact_record(ref)
        artifacts.append({"ref": ref, "type": record["type"], "data_class": record["data_class"],
                          "untrusted": record["untrusted"], "readable": within(record["data_class"], cap),
                          "name": names.get(ref)})
```

and replace:

```python
        entry["decisions"] = [{"event": d.event, "question": d.question, "kind": d.kind, "answer": d.answer,
                               "confidence": d.confidence, "disputed": d.disputed} for d in task_decisions(events)]
```

with:

```python
        entry["decisions"] = [{"event": d.event, "question": d.question, "kind": d.kind, "answer": d.answer,
                               "confidence": d.confidence, "disputed": d.disputed,
                               "options": sorted(CHOICE_OPTIONS[d.question])
                               if isinstance(d.answer, str) and d.question in CHOICE_OPTIONS else None}
                              for d in task_decisions(events)]
```

In `core/src/ooat_core/web/login.js`, replace:

```javascript
  const body = await response.json();
  status.textContent = response.ok ? `Signed in as ${body.operator}.` : body.error.message;
}
```

with:

```javascript
  const body = await response.json();
  if (response.ok) {
    // The session's second half: storage is bound to this origin, port included; the cookie is not (design 05 §6).
    localStorage.setItem("ooat.session", body.csrf);
    location.replace("/");
  } else {
    status.textContent = body.error.message;
  }
}
```

In `core/src/ooat_core/web/login.html`, replace:

```html
  <script type="module" src="/login.js"></script>
```

with:

```html
  <link rel="stylesheet" href="/app/app.css">
  <script type="module" src="/login.js"></script>
```

(`/app/app.css` arrives in Task 3; until then the sign-in page renders unstyled.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest core/tests/test_api_security.py core/tests/test_views.py core/tests/test_api.py -q`
Expected: PASS. If a test in `test_api.py` makes a GET with a cookie session on a fresh `TestClient` or
after a second `served.login()`, it carries the latest key through `client.headers`; any test that still fails
with 403 `CSRF` is fixed by passing the key the way the page does (`headers={"X-CSRF-Token": ...}`), never by
weakening the check. Record each such change as a ruling.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS (957 + 4 new, 6 skipped as on `main`).

- [ ] **Step 6: Commit**

```bash
git add core/src/ooat_core/api.py core/src/ooat_core/views.py core/src/ooat_core/web/login.js \
  core/src/ooat_core/web/login.html core/tests/api_fakes.py core/tests/test_api_security.py core/tests/test_views.py
git commit -m "feat(core): a web session's key on every request; resume_after, attachment names and choice options for the web app (plan 05b)"
```

---

### Task 2: The toolchain and the pure modules

**Files:**
- Create: `core/package.json`, `core/package-lock.json` (generated), `core/tsconfig.json`
- Create: `core/src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs`, `markdown-it.esm.min.d.mts`, `LICENSE`
- Create: `core/src/ooat_core/web/app/{dom,i18n,format,sse,api,markdown}.js`, `core/src/ooat_core/web/app/i18n/{en,cs}.js`
- Create: `core/web-tests/{format,sse,api,markdown}.test.mjs`, `core/tests/test_web.py`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Consumes: Task 1's session key rule and `localStorage["ooat.session"]`.
- Produces (every later task imports these):
  - `dom.js`: `h(tag, props?, ...children)` returns the typed element, and `props` holds attributes or `on<event>` handler functions. Also `radios(name, [[value, label], …])` → `{element, value(): string | null}` and `report(element, error)`.
  - `i18n.js`: `t(key, vars?)`, `setLanguage(preferred) → "en" | "cs"`, `currentLanguage()`.
  - `format.js`: `money(usd)`, `count(n)`, `ago(ts, now)`, `until(ts, now)`, `clock(ts)`, `title(goal)`, `text(value)`.
  - `sse.js`: `parseSse(buffer) → {messages: {id, event, data}[], rest}`.
  - `api.js`: `KEY_STORAGE`, `ApiError` (`status`, `code`, `signedOut`), `createApi({fetch, storage, onSignedOut, sleep?})` → `{json(path, {method?, body?, headers?, signal?}), raw(path, signal?), follow(task, after, onEvent, signal)}`, and the typedefs `Api` and `Context = {api, navigate(path), signal}`.
  - `markdown.js`: `renderMarkdown(text) → string`, `showMarkdown(element, text)`.

- [ ] **Step 1: Toolchain files**

Create `core/package.json`:

```json
{
  "name": "ooat-web-checks",
  "private": true,
  "type": "module",
  "description": "Type checks and tests of the web app ooat-core serves. Not needed to install or run OOAT.",
  "scripts": {
    "check": "tsc -p tsconfig.json",
    "test": "node --test \"web-tests/*.test.mjs\""
  },
  "devDependencies": {
    "markdown-it": "15.0.2",
    "typescript": "6.0.3"
  }
}
```

Create `core/tsconfig.json`:

```json
{
  "compilerOptions": {
    "allowJs": true,
    "checkJs": true,
    "noEmit": true,
    "strict": true,
    "target": "es2022",
    "module": "esnext",
    "moduleResolution": "bundler",
    "lib": ["es2023", "dom", "dom.iterable"],
    "types": [],
    "skipLibCheck": true
  },
  "include": ["src/ooat_core/web/**/*.js", "src/ooat_core/web/**/*.d.mts"]
}
```

Run (from `core/`): `npm install`
Expected: `added … packages`, a new `core/package-lock.json`, and `core/node_modules/` (already ignored by `.gitignore`).

- [ ] **Step 2: Vendor markdown-it**

Run (from `core/`):

```bash
mkdir -p src/ooat_core/web/app/vendor
cp node_modules/markdown-it/dist/browser/markdown-it.esm.min.mjs src/ooat_core/web/app/vendor/
cp node_modules/markdown-it/LICENSE src/ooat_core/web/app/vendor/LICENSE
sha256sum src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs
```

Expected: `85feb50fd6ce1b7c49acb02b0337eb622ecc4fc2ed4ae0dcbb8c084556d463b6`. Any other value: stop. The pinned package
is not the one verified on 2026-10-11.

Create `core/src/ooat_core/web/app/vendor/markdown-it.esm.min.d.mts` (types for tsc from the same pinned package;
`/app/` never serves this file):

```typescript
export { default } from "markdown-it";
```

- [ ] **Step 3: Write the failing Python tests**

Create `core/tests/test_web.py`:

```python
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
```

Run: `python -m pytest core/tests/test_web.py -q`
Expected: the vendored-file test PASSES (Step 2 put it there); the two guard tests PASS trivially, since only
`login.js` and `login.html` exist so far. Keep them: they guard every file later tasks add.

- [ ] **Step 4: Write the failing Node tests**

Create `core/web-tests/format.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { ago, count, money, text, title, until } from "../src/ooat_core/web/app/format.js";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";

const now = new Date("2026-10-11T10:00:00Z");

test("money shows cents, or the digits that matter below a cent", () => {
  assert.equal(money(0.42), "$0.42");
  assert.equal(money(3.1), "$3.10");
  assert.equal(money(0), "$0.00");
  assert.equal(money(0.002), "$0.002");
  assert.equal(money(0.00004), "<$0.0001");
  assert.equal(money(null), "—");
});

test("counts of tokens are short", () => {
  assert.deepEqual([count(950), count(410_000), count(2_400_000)], ["950", "410k", "2.4M"]);
});

test("times are relative, in the chosen language", () => {
  setLanguage("en");
  assert.equal(ago("2026-10-11T09:58:00Z", now), "2 min");
  assert.equal(until("2026-10-12T09:00:00Z", now), "in 23 h");
  assert.equal(until("2026-10-11T09:00:00Z", now), "overdue");
  setLanguage("cs-CZ");
  assert.equal(until("2026-10-11T10:05:00Z", now), "za 5 min");
  setLanguage("en");
});

test("a goal becomes a one-line title, and a redaction stub its notice", () => {
  assert.equal(title("Release notes 0.3\nwith details"), "Release notes 0.3");
  assert.equal(title("x".repeat(100)).length, 80);
  const stub = {redacted: "above this token's data class; open in the web app", link: "/tasks/tsk_1"};
  assert.equal(title(stub), "Above this session's data class: not shown.");
  assert.equal(text(stub), "Above this session's data class: not shown.");
  assert.equal(text("plain"), "plain");
});
```

Create `core/web-tests/sse.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseSse } from "../src/ooat_core/web/app/sse.js";

test("whole messages are parsed and an unfinished one is kept for the next chunk", () => {
  const {messages, rest} = parseSse("id: evt_1\nevent: RESULT\ndata: {\"a\":1}\n\n: keepalive\n\nid: evt_2\nda");
  assert.deepEqual(messages, [{id: "evt_1", event: "RESULT", data: "{\"a\":1}"}]);
  assert.equal(rest, "id: evt_2\nda");
});

test("a keepalive comment alone is no message", () => {
  assert.deepEqual(parseSse(": keepalive\n\n"), {messages: [], rest: ""});
});
```

Create `core/web-tests/api.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, createApi, KEY_STORAGE } from "../src/ooat_core/web/app/api.js";

const storage = {getItem: (/** @type {string} */ key) => (key === KEY_STORAGE ? "key-1" : null)};

/** @param {unknown} body @param {number} [status] */
const reply = (body, status = 200) => new Response(JSON.stringify(body), {status,
  headers: {"Content-Type": "application/json"}});

/** @param {string[]} chunks */
const stream = (chunks) => new Response(new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
    controller.close();
  },
}), {headers: {"Content-Type": "text/event-stream"}});

const sse = (/** @type {string} */ id, /** @type {string} */ type) =>
  `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify({id, type})}\n\n`;

test("every request carries the session key, and JSON goes both ways", async () => {
  /** @type {any[]} */
  const calls = [];
  const api = createApi({storage, onSignedOut: () => assert.fail("signed out"),
    fetch: async (url, init) => { calls.push([url, init]); return reply({task: "tsk_1"}, 202); }});
  assert.deepEqual(await api.json("/tasks", {method: "POST", body: {goal: "x"}, headers: {"Idempotency-Key": "k"}}),
    {task: "tsk_1"});
  const [url, init] = calls[0];
  assert.equal(url, "/api/v1/tasks");
  assert.equal(init.method, "POST");
  assert.equal(init.body, "{\"goal\":\"x\"}");
  assert.deepEqual(init.headers, {"Content-Type": "application/json", "Idempotency-Key": "k", "X-CSRF-Token": "key-1"});
});

test("an error body becomes an ApiError with its code", async () => {
  const api = createApi({storage, onSignedOut: () => assert.fail("signed out"),
    fetch: async () => reply({error: {code: "ALREADY_ANSWERED", message: "evt_1 is already answered"}}, 409)});
  await assert.rejects(api.json("/hil/evt_1/answer", {method: "POST", body: {choice: "a"}}),
    (/** @type {ApiError} */ error) => error instanceof ApiError && error.code === "ALREADY_ANSWERED"
      && error.status === 409 && !error.signedOut);
});

test("a 401 or a CSRF refusal signs the page out", async () => {
  for (const [status, code] of [[401, "UNAUTHENTICATED"], [403, "CSRF"]]) {
    let signedOut = 0;
    const api = createApi({storage, onSignedOut: () => { signedOut += 1; },
      fetch: async () => reply({error: {code, message: "sign in"}}, /** @type {number} */ (status))});
    await assert.rejects(api.json("/me"));
    assert.equal(signedOut, 1, String(code));
  }
});

test("follow reconnects after the last event it saw and stops at TASK_CLOSED", async () => {
  /** @type {(string | null)[]} */
  const cursors = [];
  const responses = [stream([sse("evt_1", "RESULT").slice(0, 10), sse("evt_1", "RESULT").slice(10) + sse("evt_2",
    "GATE_PASSED")]), stream([sse("evt_3", "TASK_CLOSED")])];
  const api = createApi({storage, onSignedOut: () => assert.fail("signed out"), sleep: async () => {},
    fetch: async (_url, init) => {
      cursors.push(/** @type {Record<string, string>} */ (init?.headers)["Last-Event-ID"] ?? null);
      return /** @type {Response} */ (responses.shift());
    }});
  /** @type {string[]} */
  const seen = [];
  await api.follow("tsk_1", "evt_0", (event) => seen.push(event.id), new AbortController().signal);
  assert.deepEqual(seen, ["evt_1", "evt_2", "evt_3"]);
  assert.deepEqual(cursors, ["evt_0", "evt_2"]);
});

test("follow ends when the server says the reader is no longer signed in", async () => {
  let signedOut = 0;
  const api = createApi({storage, onSignedOut: () => { signedOut += 1; }, sleep: async () => {},
    fetch: async () => stream(["event: UNAUTHENTICATED\ndata: {}\n\n"])});
  await api.follow("tsk_1", null, () => assert.fail("no event"), new AbortController().signal);
  assert.equal(signedOut, 1);
});
```

Create `core/web-tests/markdown.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderMarkdown } from "../src/ooat_core/web/app/markdown.js";

test("markdown renders headings and safe links", () => {
  assert.match(renderMarkdown("# Release notes"), /<h1>Release notes<\/h1>/);
  assert.match(renderMarkdown("[docs](https://example.org)"), /<a href="https:\/\/example.org">docs<\/a>/);
});

test("markdown never passes raw HTML or a javascript: link", () => {
  const html = renderMarkdown("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))");
  assert.doesNotMatch(html, /<script|<img|href="javascript:/i);  // the refused link stays as plain text
  assert.match(html, /&lt;script&gt;/);
});

test("the vendored renderer is the pinned package's file", () => {
  const vendored = readFileSync(new URL("../src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs", import.meta.url));
  const pinned = readFileSync(new URL("../node_modules/markdown-it/dist/browser/markdown-it.esm.min.mjs",
    import.meta.url));
  assert.ok(vendored.equals(pinned));
});
```

Run (from `core/`): `npm test`
Expected: FAIL. Every file fails with `ERR_MODULE_NOT_FOUND` for the module it imports.

- [ ] **Step 5: Implement the pure modules**

Create `core/src/ooat_core/web/app/dom.js`:

```javascript
// The one way the app builds the page: elements and text nodes, never HTML from data (design 05 §6). Only
// markdown.js sets innerHTML, from markdown-it with raw HTML off; core/tests/test_web.py holds that rule.

/** @typedef {string | boolean | undefined | ((event: Event) => void)} Prop */
/** @typedef {Node | string | null | undefined | false} Child */

/**
 * An element with attributes, `on<event>` handlers and children.
 * @template {keyof HTMLElementTagNameMap} K
 * @param {K} tag
 * @param {Record<string, Prop>} [props]
 * @param {...Child} children
 * @returns {HTMLElementTagNameMap[K]}
 */
export function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (typeof value === "function") element.addEventListener(name.slice(2), value);
    else if (value === true) element.setAttribute(name, "");
    else if (typeof value === "string") element.setAttribute(name, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) element.append(child);
  }
  return element;
}

/**
 * A group of radio buttons; `value()` is the checked one, or null.
 * @param {string} name unique on the page
 * @param {[string, string][]} options value and label
 */
export function radios(name, options) {
  const inputs = options.map(([value]) => h("input", {type: "radio", name, value}));
  const element = h("span", {class: "radios"}, ...options.map(([, label], i) => h("label", {}, inputs[i], label)));
  return {element, value: () => inputs.find((input) => input.checked)?.value ?? null};
}

/**
 * Shows an error where the screen is. Not when the screen was left (an aborted request) or the session ended
 * (the sign-in notice is already shown).
 * @param {Element} element
 * @param {unknown} error
 */
export function report(element, error) {
  if (error instanceof DOMException && error.name === "AbortError") return;
  if (error instanceof Error && "signedOut" in error && error.signedOut) return;
  element.append(h("span", {class: "error", role: "alert"}, error instanceof Error ? error.message : String(error)));
}
```

Create `core/src/ooat_core/web/app/i18n/en.js`:

```javascript
// English UI strings (spec §10). cs.js has exactly these keys; tsc checks it.
export default {
  "common.redacted": "Above this session's data class: not shown.",
  "common.yes": "yes",
  "common.no": "no",
  "time.now": "now",
  "time.minutes": "{n} min",
  "time.hours": "{n} h",
  "time.overdue": "overdue",
  "time.inMinutes": "in {n} min",
  "time.inHours": "in {n} h",
};
```

Create `core/src/ooat_core/web/app/i18n/cs.js`:

```javascript
// Czech UI strings (spec §10): the keys of en.js, no more and no fewer.
/** @type {Record<keyof typeof import("./en.js").default, string>} */
export default {
  "common.redacted": "Nad datovou třídou této relace: nezobrazeno.",
  "common.yes": "ano",
  "common.no": "ne",
  "time.now": "teď",
  "time.minutes": "{n} min",
  "time.hours": "{n} h",
  "time.overdue": "po termínu",
  "time.inMinutes": "za {n} min",
  "time.inHours": "za {n} h",
};
```

Create `core/src/ooat_core/web/app/i18n.js`:

```javascript
// The UI in English or Czech (spec §10): the browser's language, or the operator's choice in the header.
import cs from "./i18n/cs.js";
import en from "./i18n/en.js";

/** @typedef {keyof typeof en} Key */

/** @type {"en" | "cs"} */
let language = "en";

/**
 * @param {string | null | undefined} preferred a stored choice or navigator.language
 * @returns {"en" | "cs"}
 */
export function setLanguage(preferred) {
  language = preferred?.toLowerCase().startsWith("cs") ? "cs" : "en";
  return language;
}

export function currentLanguage() {
  return language;
}

/**
 * The string for `key` in the current language, with `{name}` filled from `vars`.
 * @param {Key} key
 * @param {Record<string, string | number>} [vars]
 */
export function t(key, vars = {}) {
  const found = (language === "cs" ? cs : en)[key];
  return found.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
}
```

Create `core/src/ooat_core/web/app/format.js`:

```javascript
// Money, counts and times as the screens show them (design 05 §4).
import { currentLanguage, t } from "./i18n.js";

const MINUTE_MS = 60_000;

/** Dollars: cents, or the digits that matter below a cent ("$0.002"). @param {number | null | undefined} usd */
export function money(usd) {
  if (usd === null || usd === undefined) return "—";
  if (usd === 0 || Math.abs(usd) >= 0.01) return `$${usd.toFixed(2)}`;
  const small = usd.toFixed(4).replace(/0+$/, "");
  return small.endsWith(".") ? "<$0.0001" : `$${small}`;
}

/** 410000 → "410k". @param {number} n */
export function count(n) {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** How long ago: "now", "2 min", "3 h", or the date. @param {string} ts @param {Date} now */
export function ago(ts, now) {
  const minutes = Math.floor((now.getTime() - Date.parse(ts)) / MINUTE_MS);
  if (minutes < 1) return t("time.now");
  if (minutes < 60) return t("time.minutes", {n: minutes});
  if (minutes < 24 * 60) return t("time.hours", {n: Math.floor(minutes / 60)});
  return new Date(ts).toLocaleDateString(currentLanguage());
}

/** Until a deadline: "in 5 min", "in 23 h", or "overdue". @param {string} ts @param {Date} now */
export function until(ts, now) {
  const minutes = Math.ceil((Date.parse(ts) - now.getTime()) / MINUTE_MS);
  if (minutes <= 0) return t("time.overdue");
  if (minutes < 60) return t("time.inMinutes", {n: minutes});
  return t("time.inHours", {n: Math.floor(minutes / 60)});
}

/** "10:02" in the reader's time zone. @param {string} ts */
export function clock(ts) {
  return new Date(ts).toLocaleTimeString(currentLanguage(), {hour: "2-digit", minute: "2-digit"});
}

/**
 * A goal as a one-line title of at most 80 characters; a redaction stub as its notice.
 * @param {string | {redacted: string} | null | undefined} goal
 */
export function title(goal) {
  if (typeof goal !== "string") return t("common.redacted");
  const line = goal.split("\n", 1)[0].trim();
  return line.length > 80 ? `${line.slice(0, 79)}…` : line;
}

/** Text that may be a redaction stub. @param {string | {redacted: string} | null | undefined} value */
export function text(value) {
  if (typeof value === "string") return value;
  return value ? t("common.redacted") : "";
}
```

Create `core/src/ooat_core/web/app/sse.js`:

```javascript
// Server-Sent Events as `ooat serve` writes them: `id:`, `event:`, `data:` lines, a blank line ends a message, a
// line starting with ":" is a comment (the keepalive).

/** @typedef {{id: string | null, event: string, data: string}} SseMessage */

/**
 * The whole messages in `buffer`, and the unfinished rest to prepend to the next chunk.
 * @param {string} buffer
 * @returns {{messages: SseMessage[], rest: string}}
 */
export function parseSse(buffer) {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  /** @type {SseMessage[]} */
  const messages = [];
  for (const block of blocks) {
    /** @type {SseMessage} */
    const message = {id: null, event: "message", data: ""};
    const data = [];
    for (const line of block.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "id") message.id = value;
      else if (field === "event") message.event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length) messages.push({...message, data: data.join("\n")});
  }
  return {messages, rest};
}
```

Create `core/src/ooat_core/web/app/api.js`:

```javascript
// The page's one door to `ooat serve` (design 05 §5, §6). A web session has two halves: the HttpOnly cookie and the
// session key, kept in this origin's storage and sent as X-CSRF-Token on every request. A cookie is not bound to a
// port, so another service on 127.0.0.1 may receive it; the storage is bound to the origin, port included.
import { parseSse } from "./sse.js";

export const KEY_STORAGE = "ooat.session";
const RECONNECT_MS = 1000;

export class ApiError extends Error {
  /** @param {number} status @param {string} code @param {string} message */
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }

  /** The session is gone, or this page lacks its key: sign in again. */
  get signedOut() {
    return this.status === 401 || this.code === "CSRF";
  }
}

/**
 * @typedef {object} Env
 * @property {typeof fetch} fetch
 * @property {Pick<Storage, "getItem">} storage
 * @property {() => void} onSignedOut
 * @property {(ms: number) => Promise<void>} [sleep]
 */

/** @param {Env} env */
export function createApi(env) {
  const sleep = env.sleep ?? ((/** @type {number} */ ms) => new Promise((resolve) => setTimeout(resolve, ms)));

  /** @param {Record<string, string>} [extra] @returns {Record<string, string>} */
  function headers(extra = {}) {
    const key = env.storage.getItem(KEY_STORAGE);
    return key ? {...extra, "X-CSRF-Token": key} : extra;
  }

  /** @param {Response} response */
  async function failure(response) {
    let code = "INVALID";
    let message = `HTTP ${response.status}`;
    try {
      ({code, message} = (await response.json()).error);
    } catch {
      // not an API error body; keep the status
    }
    const error = new ApiError(response.status, code, message);
    if (error.signedOut) env.onSignedOut();
    return error;
  }

  /**
   * JSON in and out; an error response throws ApiError.
   * @param {string} path below /api/v1, e.g. "/tasks"
   * @param {{method?: string, body?: unknown, headers?: Record<string, string>, signal?: AbortSignal}} [options]
   * @returns {Promise<any>}
   */
  async function json(path, options = {}) {
    const hasBody = options.body !== undefined;
    const response = await env.fetch(`/api/v1${path}`, {
      method: options.method ?? "GET",
      headers: headers({...(hasBody ? {"Content-Type": "application/json"} : {}), ...options.headers}),
      body: hasBody ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
    if (!response.ok) throw await failure(response);
    return response.json();
  }

  /**
   * The response of a GET as it is (artifact text, a diff, a download); an error response throws ApiError.
   * @param {string} path below /api/v1
   * @param {AbortSignal} [signal]
   */
  async function raw(path, signal) {
    const response = await env.fetch(`/api/v1${path}`, {headers: headers(), signal});
    if (!response.ok) throw await failure(response);
    return response;
  }

  /**
   * Follows a task's timeline until its TASK_CLOSED, or until `signal` aborts. The server ends a stream after
   * 15 minutes; the next one starts after the last event seen, so nothing is shown twice or missed.
   * @param {string} task
   * @param {string | null} after the last event already shown
   * @param {(event: any) => void} onEvent
   * @param {AbortSignal} signal
   */
  async function follow(task, after, onEvent, signal) {
    let cursor = after;
    while (!signal.aborted) {
      const response = await env.fetch(`/api/v1/tasks/${encodeURIComponent(task)}/events`, {
        headers: headers({Accept: "text/event-stream", ...(cursor ? {"Last-Event-ID": cursor} : {})}), signal,
      });
      if (!response.ok || !response.body) throw await failure(response);
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const {value, done} = await reader.read();
        if (done) break;
        const parsed = parseSse(buffer + value);
        buffer = parsed.rest;
        for (const message of parsed.messages) {
          if (message.event === "UNAUTHENTICATED") {
            env.onSignedOut();
            return;
          }
          const event = JSON.parse(message.data);
          cursor = event.id;
          onEvent(event);
          if (event.type === "TASK_CLOSED") return;
        }
      }
      await sleep(RECONNECT_MS);
    }
  }

  return {json, raw, follow};
}

/** @typedef {ReturnType<typeof createApi>} Api */

/**
 * What every screen gets: the API, in-app navigation, and a signal that aborts when the screen is left.
 * @typedef {object} Context
 * @property {Api} api
 * @property {(path: string) => void} navigate
 * @property {AbortSignal} signal
 */
```

Create `core/src/ooat_core/web/app/markdown.js`:

```javascript
// Documents may derive from untrusted attachments: never trusted markup (design 05 §6). Raw HTML is off, so tags
// show as text; markdown-it refuses javascript:, vbscript:, file: and non-image data: links.
import MarkdownIt from "./vendor/markdown-it.esm.min.mjs";

const md = new MarkdownIt({html: false, linkify: false, typographer: false});

/** @param {string} source @returns {string} HTML */
export function renderMarkdown(source) {
  return md.render(source);
}

/**
 * The app's only innerHTML: markdown-it's output, which escapes everything it does not produce itself.
 * @param {Element} element
 * @param {string} source
 */
export function showMarkdown(element, source) {
  element.innerHTML = renderMarkdown(source);
}
```

- [ ] **Step 6: Run the tests and the type check**

Run (from `core/`): `npm test`
Expected: PASS (all tests in the four files).

Run (from `core/`): `npm run check`
Expected: no output, exit code 0. A type error is fixed in the code (a missing JSDoc type, a missing null
check), not by `// @ts-ignore` or by loosening `tsconfig.json`.

Run: `python -m pytest core/tests/test_web.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: CI job**

In `.github/workflows/tests.yml`, append after the `pytest` job (same indentation as `pytest:`):

```yaml
  web:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: core
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v6
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: core/package-lock.json
      - run: npm ci
      - run: npm run check
      - run: npm test
```

Before committing, check the current major of `actions/setup-node` on github.com/actions/setup-node/releases and use
it if newer than `v6` (the repository uses the current majors of `checkout` and `setup-python`); record the version
as a ruling.

- [ ] **Step 8: Commit**

```bash
git add core/package.json core/package-lock.json core/tsconfig.json .github/workflows/tests.yml \
  core/src/ooat_core/web/app/dom.js core/src/ooat_core/web/app/i18n.js core/src/ooat_core/web/app/format.js \
  core/src/ooat_core/web/app/sse.js core/src/ooat_core/web/app/api.js core/src/ooat_core/web/app/markdown.js \
  core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js \
  core/src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs core/src/ooat_core/web/app/vendor/markdown-it.esm.min.d.mts \
  core/src/ooat_core/web/app/vendor/LICENSE core/web-tests/format.test.mjs core/web-tests/sse.test.mjs \
  core/web-tests/api.test.mjs core/web-tests/markdown.test.mjs core/tests/test_web.py
git commit -m "feat(web): toolchain (tsc, node --test, CI), vendored markdown-it, and the app's pure modules (plan 05b)"
```

---

### Task 3: The shell, the cards and the inbox

**Files:**
- Create: `core/src/ooat_core/web/index.html`, `core/src/ooat_core/web/app/{app.js,app.css,rating.js,cards.js}`,
  `core/src/ooat_core/web/app/views/inbox.js`, `core/web-tests/rating.test.mjs`
- Modify: `core/src/ooat_core/api.py` (app routes), `core/src/ooat_core/web/app/i18n/{en,cs}.js`, `core/tests/test_web.py`

**Interfaces:**
- Consumes: Task 2's modules; Task 1's `resume_after` and decision `options`.
- Produces:
  - `api.py` `app_routes()`: the shell at `/`, `/tasks/{task}`, `/usage` and `/connectors`, and `/app/{path}` for `.js`, `.mjs` and `.css` files of `web/app`.
  - `app.js`: the `ROUTES` and `NAV` tables, which Tasks 4–6 extend.
  - `rating.js`: `ratingBody({accepted, valueClass, note, marks})` and `decisionText(decision)`.
  - `cards.js`: `questionCard(request, ctx, onDone)` and `ratingCard(entry, ctx, {compact, onDone})`.
  - `views/inbox.js`: `inbox(root, ctx)`.

- [ ] **Step 1: Write the failing tests**

In `core/tests/test_web.py`, add `from api_fakes import Served` to the imports at the top, and append:

```python
def test_the_app_shell_is_served_for_each_screen_without_a_session(tmp_path):
    served = Served(tmp_path)
    for path in ("/", "/tasks/tsk_01ABC", "/usage", "/connectors"):
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
```

Create `core/web-tests/rating.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";
import { decisionText, ratingBody } from "../src/ooat_core/web/app/rating.js";

const gate = {event: "evt_g", question: "a1.1", kind: "gate", answer: 0.93, confidence: 0.9, disputed: false,
  options: null};
const branch = {event: "evt_g", question: "a5", kind: "gate", answer: "one", confidence: 0.8, disputed: false,
  options: ["one", "two"]};
const check = {event: "evt_c", question: "c1", kind: "acceptance", answer: 0.41, confidence: 0.7, disputed: true,
  options: null};

test("marked decisions become verdicts; a wrong yes/no is corrected to the other answer", () => {
  assert.deepEqual(ratingBody({accepted: false, valueClass: "B", note: "  too short  ", marks: [
    {decision: gate, mark: "right"}, {decision: check, mark: "wrong"}, {decision: branch, mark: "wrong",
      option: "two"}]}), {
    accepted: false, value_class: "B", note: "too short", decisions: [
      {event: "evt_g", question: "a1.1", verdict: "confirmed"},
      {event: "evt_c", question: "c1", verdict: "corrected", value: 1},
      {event: "evt_g", question: "a5", verdict: "corrected", value: "two"}]});
});

test("no marks and no note: a one-click rating", () => {
  assert.deepEqual(ratingBody({accepted: true, valueClass: "A", note: "", marks: []}),
    {accepted: true, value_class: "A", decisions: []});
});

test("a decision reads as what was decided, and how sure", () => {
  setLanguage("en");
  assert.equal(decisionText(gate), "Gate A1.1: yes (0.93)");
  assert.equal(decisionText(branch), "Gate A5: one");
  assert.equal(decisionText(check), "Acceptance C1: no (0.41) · the critic disagreed");
});
```

Run: `python -m pytest core/tests/test_web.py -q` and (from `core/`) `npm test`
Expected: FAIL. The Python shell tests get 404 for `/` and `/app/app.js`; `rating.test.mjs` fails with
`ERR_MODULE_NOT_FOUND`.

- [ ] **Step 2: Serve the shell and the app files**

In `core/src/ooat_core/api.py`, replace:

```python
SESSION_COOKIE = "ooat_session"
```

with:

```python
SESSION_COOKIE = "ooat_session"
APP_TYPES = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
             ".css": "text/css; charset=utf-8"}
```

replace:

```python
    app.include_router(login_routes())
```

with:

```python
    app.include_router(login_routes())
    app.include_router(app_routes())
```

and insert this before `def session_routes() -> APIRouter:`:

```python
def _app_files(folder, prefix: str = "") -> dict[str, tuple[bytes, str]]:
    """Every script and style of web/app by its path, read once at start-up."""
    found = {}
    for entry in folder.iterdir():
        if entry.is_dir():
            found |= _app_files(entry, f"{prefix}{entry.name}/")
        elif Path(entry.name).suffix in APP_TYPES:
            found[prefix + entry.name] = (entry.read_bytes(), APP_TYPES[Path(entry.name).suffix])
    return found


def app_routes() -> APIRouter:
    """The web app (05b): its shell for each screen and its files. Code only, no data, so no session is needed;
    every data call the page makes is authenticated like any other client's. /app/ serves only the files found
    at start-up: no path from the URL reaches the file system."""
    router = APIRouter()
    web = files("ooat_core") / "web"
    shell = (web / "index.html").read_bytes()
    app_files = _app_files(web / "app")

    def page() -> Response:
        return Response(shell, media_type="text/html; charset=utf-8")

    for path in ("/", "/usage", "/connectors"):
        router.add_api_route(path, page, methods=["GET"])

    @router.get("/tasks/{task}")
    def task_page(task: str) -> Response:  # the page reads the id from its address
        return page()

    @router.get("/app/{path:path}")
    def app_file(path: str) -> Response:
        found = app_files.get(path)
        if found is None:
            raise ApiError(404, "NOT_FOUND", "no such file")
        return Response(found[0], media_type=found[1])

    return router
```

- [ ] **Step 3: The page and its styles**

Create `core/src/ooat_core/web/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>OOAT</title>
  <link rel="stylesheet" href="/app/app.css">
  <script type="module" src="/app/app.js"></script>
</head>
<body>
  <header id="top"></header>
  <main id="view"></main>
</body>
</html>
```

Create `core/src/ooat_core/web/app/app.css`:

```css
/* The web app's look: system fonts, light and dark, one column on a phone (design 05 §4). */
:root {
  --bg: #ffffff; --fg: #1d1f23; --muted: #646a73; --line: #d9dce1; --card: #f6f7f9;
  --accent: #2459c9; --ok: #1d7a3a; --fail: #b3261e; --ask: #8a5a00;
  color-scheme: light dark;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #15171a; --fg: #e6e8eb; --muted: #9aa1ab; --line: #30343a; --card: #1e2125;
    --accent: #7aa2ff; --ok: #5cc27a; --fail: #ff8a80; --ask: #e0b25c; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; }
#top { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--line); }
#top nav { display: flex; gap: 16px; }
main { max-width: 1200px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.4rem; margin: 0 0 12px; }
h2 { font-size: 1.05rem; margin: 24px 0 8px; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.error { display: block; color: var(--fail); }
.status { min-height: 1.5em; margin: 4px 0 0; color: var(--muted); }
.warning { color: var(--ask); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; margin: 8px 0; }
.card p { margin: 0 0 8px; }
.actions, .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
button, .button, input, select, textarea { font: inherit; color: inherit; }
button, .button { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px;
  cursor: pointer; text-decoration: none; }
button.recommended { border-color: var(--accent); font-weight: 600; }
button.active { background: var(--accent); color: var(--bg); }
button.danger { border-color: var(--fail); color: var(--fail); }
button.link { border: 0; background: none; padding: 0; color: var(--accent); text-decoration: underline; }
button:disabled { opacity: 0.5; cursor: default; }
input, select, textarea { background: var(--bg); border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; }
textarea { width: 100%; }
.new-task textarea { margin-bottom: 8px; }
.radios { display: inline-flex; gap: 10px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
td.number, th.number { text-align: right; }
.columns { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 24px; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { padding: 3px 0; }
.timeline time { color: var(--muted); font-variant-numeric: tabular-nums; margin-right: 6px; }
.timeline .ok { color: var(--ok); }
.timeline .fail { color: var(--fail); }
.timeline .ask { color: var(--ask); }
.viewer { border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; overflow-x: auto; }
pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: 13px/1.45 ui-monospace, monospace; }
.source .ln { display: inline-block; width: 3em; color: var(--muted); user-select: none; }
.diff .add { color: var(--ok); }
.diff .del { color: var(--fail); }
.diff .hunk { color: var(--muted); }
@media (max-width: 720px) { .columns { grid-template-columns: 1fr; } }
```

- [ ] **Step 4: The rating logic, the cards, the inbox and the entry**

Add these keys to `core/src/ooat_core/web/app/i18n/en.js`:

```javascript
  "app.notFound": "There is no such page.",
  "app.signedOut": "You are signed out. Open the link that `ooat login --operator <name>` prints in your terminal.",
  "nav.inbox": "Inbox",
  "top.spend": "today {day} · week {week}",
  "top.busy": "● runner busy",
  "top.idle": "● runner idle",
  "top.signOut": "Sign out",
  "inbox.title": "Inbox",
  "inbox.waiting": "Waiting for you ({n})",
  "inbox.stuck": "Stuck ({n})",
  "inbox.paused": "paused after a provider failure; tries again at {at}",
  "inbox.tasks": "Tasks",
  "inbox.task": "Task",
  "inbox.state": "State",
  "inbox.topology": "Topology",
  "inbox.cost": "Cost / budget",
  "inbox.updated": "Updated",
  "new.goal": "What should be done?",
  "new.acceptance": "Done when (one per line, optional)",
  "new.project": "Project",
  "new.dataClass": "Data class",
  "new.budget": "Budget $ (optional)",
  "new.attach": "Attachments",
  "new.submit": "Submit",
  "new.tooLarge": "Attachments may total at most 14 MB.",
  "hil.note": "Note or narrowed scope (optional)",
  "hil.answered": "Answer recorded.",
  "hil.default": "If nobody answers: {option}, {deadline}.",
  "hil.r3": "An irreversible (R3) action needs an approver bound to a passkey or an OS account. It cannot be answered here yet (ADR 0016).",
  "rating.acceptedAs": "Accepted {value}",
  "rating.notAccepted": "Not accepted…",
  "rating.saved": "Rating saved.",
  "rating.accepted": "Accepted?",
  "rating.value": "Value",
  "rating.note": "Note (optional)",
  "rating.decisions": "Decisions OOAT made alone: were they right?",
  "rating.right": "Right",
  "rating.wrong": "Wrong",
  "rating.correct": "Correct answer",
  "rating.save": "Save rating",
  "rating.incomplete": "Choose whether it is accepted, and a value, first.",
  "rating.gate": "Gate",
  "rating.acceptance": "Acceptance",
  "rating.disputed": "the critic disagreed",
```

and the same keys to `core/src/ooat_core/web/app/i18n/cs.js`:

```javascript
  "app.notFound": "Taková stránka neexistuje.",
  "app.signedOut": "Jste odhlášeni. Otevřete odkaz, který v terminálu vypíše `ooat login --operator <jméno>`.",
  "nav.inbox": "Přehled",
  "top.spend": "dnes {day} · týden {week}",
  "top.busy": "● běží úloha",
  "top.idle": "● nic neběží",
  "top.signOut": "Odhlásit",
  "inbox.title": "Přehled",
  "inbox.waiting": "Čeká na vás ({n})",
  "inbox.stuck": "Uvízlé ({n})",
  "inbox.paused": "pozastaveno po výpadku poskytovatele; další pokus v {at}",
  "inbox.tasks": "Úlohy",
  "inbox.task": "Úloha",
  "inbox.state": "Stav",
  "inbox.topology": "Topologie",
  "inbox.cost": "Náklady / rozpočet",
  "inbox.updated": "Změna",
  "new.goal": "Co je potřeba udělat?",
  "new.acceptance": "Hotovo, když (po řádcích, nepovinné)",
  "new.project": "Projekt",
  "new.dataClass": "Datová třída",
  "new.budget": "Rozpočet $ (nepovinný)",
  "new.attach": "Přílohy",
  "new.submit": "Zadat",
  "new.tooLarge": "Přílohy mohou mít dohromady nejvýš 14 MB.",
  "hil.note": "Poznámka nebo zúžené zadání (nepovinné)",
  "hil.answered": "Odpověď zaznamenána.",
  "hil.default": "Když nikdo neodpoví: {option}, {deadline}.",
  "hil.r3": "Nevratná akce (R3) potřebuje schvalovatele ověřeného passkey nebo účtem v systému. Zde ji zatím odpovědět nelze (ADR 0016).",
  "rating.acceptedAs": "Přijato {value}",
  "rating.notAccepted": "Nepřijato…",
  "rating.saved": "Hodnocení uloženo.",
  "rating.accepted": "Přijato?",
  "rating.value": "Hodnota",
  "rating.note": "Poznámka (nepovinná)",
  "rating.decisions": "Rozhodnutí, která OOAT udělal sám: byla správná?",
  "rating.right": "Správně",
  "rating.wrong": "Špatně",
  "rating.correct": "Správná odpověď",
  "rating.save": "Uložit hodnocení",
  "rating.incomplete": "Nejdřív zvolte, zda je přijato, a hodnotu.",
  "rating.gate": "Brána",
  "rating.acceptance": "Akceptace",
  "rating.disputed": "kritik nesouhlasil",
```

Create `core/src/ooat_core/web/app/rating.js`:

```javascript
// What a rating sends (design 05 §4, ADR 0011): marked decisions become verdicts, unmarked ones stay unrated.
import { t } from "./i18n.js";

/**
 * A decision OOAT made alone, as GET /ratings/queue lists it.
 * @typedef {{event: string, question: string, kind: string, answer: number | string, confidence: number,
 *            disputed: boolean, options: string[] | null}} Decision
 */

/**
 * The body of POST /tasks/{id}/rating. "wrong" corrects a yes/no decision to the other answer and a choice to the
 * option picked.
 * @param {{accepted: boolean, valueClass: string, note: string,
 *          marks: {decision: Decision, mark: string, option?: string}[]}} input
 */
export function ratingBody(input) {
  const note = input.note.trim();
  return {
    accepted: input.accepted, value_class: input.valueClass, ...(note ? {note} : {}),
    decisions: input.marks.map(({decision, mark, option}) => ({
      event: decision.event, question: decision.question,
      ...(mark === "right" ? {verdict: "confirmed"} : {
        verdict: "corrected",
        value: typeof decision.answer === "number" ? (decision.answer >= 0.5 ? 0 : 1) : option,
      }),
    })),
  };
}

/** "Gate A1.1: yes (0.93)". @param {Decision} decision */
export function decisionText(decision) {
  const who = decision.kind === "gate" ? t("rating.gate") : t("rating.acceptance");
  const answer = typeof decision.answer === "number"
    ? `${decision.answer >= 0.5 ? t("common.yes") : t("common.no")} (${decision.answer.toFixed(2)})`
    : decision.answer;
  return `${who} ${decision.question.toUpperCase()}: ${answer}${decision.disputed ? ` · ${t("rating.disputed")}` : ""}`;
}
```

Create `core/src/ooat_core/web/app/cards.js`:

```javascript
// The cards the operator acts on, in the inbox and on the task page (design 05 §4): a question with one button per
// option (★ the recommended one; the default on silence and the deadline always printed), and the rating card.
import { h, radios } from "./dom.js";
import { money, text, title, until } from "./format.js";
import { t } from "./i18n.js";
import { decisionText, ratingBody } from "./rating.js";

/**
 * @param {any} request an entry of GET /hil
 * @param {import("./api.js").Context} ctx
 * @param {() => void} onDone after the answer is recorded
 */
export function questionCard(request, ctx, onDone) {
  const status = h("p", {class: "status", role: "status"});
  const label = (/** @type {any} */ option) => text(option.label);
  const fallback = request.options.find((/** @type {any} */ o) => o.id === request.default_on_silence);
  const footer = h("p", {class: "muted"}, t("hil.default", {
    option: fallback ? label(fallback) : request.default_on_silence, deadline: until(request.deadline, new Date())}));
  const question = h("p", {}, "? ", h("a", {href: `/tasks/${request.task}`, "data-route": ""}, text(request.question)));
  if (request.risk_class === "R3") {
    return h("article", {class: "card question"}, question, h("p", {class: "warning"}, t("hil.r3")), footer);
  }
  const note = h("input", {type: "text", maxlength: "20000", placeholder: t("hil.note"), "aria-label": t("hil.note")});
  const buttons = request.options.map((/** @type {any} */ option) => h("button", {
    type: "button", class: option.id === request.recommended ? "recommended" : undefined,
    onclick: () => answer(option.id),
  }, label(option) + (option.id === request.recommended ? " ★" : "")
    + (option.cost_usd ? ` · ${money(option.cost_usd)}` : "")));

  /** @param {string} choice */
  async function answer(choice) {
    for (const button of buttons) button.disabled = true;
    const typed = note.value.trim();
    try {
      await ctx.api.json(`/hil/${encodeURIComponent(request.request)}/answer`,
        {method: "POST", body: {choice, ...(typed ? {text: typed} : {})}});
      status.textContent = t("hil.answered");
      onDone();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
      for (const button of buttons) button.disabled = false;
    }
  }

  return h("article", {class: "card question"}, question, h("div", {class: "actions"}, ...buttons), note, footer,
    status);
}

/**
 * @param {any} entry an entry of GET /ratings/queue
 * @param {import("./api.js").Context} ctx
 * @param {{compact: boolean, onDone: () => void}} options compact: one-click buttons for the inbox
 */
export function ratingCard(entry, ctx, {compact, onDone}) {
  const status = h("p", {class: "status", role: "status"});
  const heading = h("p", {}, "★ ", h("a", {href: `/tasks/${entry.task}`, "data-route": ""}, title(entry.goal)),
    ` · ${entry.state} · ${money(entry.cost_usd)}`);

  /** @param {object} body */
  async function save(body) {
    try {
      await ctx.api.json(`/tasks/${encodeURIComponent(entry.task)}/rating`, {method: "POST", body});
      status.textContent = t("rating.saved");
      onDone();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
    }
  }

  if (compact) {
    return h("article", {class: "card rating"}, heading, h("div", {class: "actions"},
      ...["A", "B", "C"].map((value) => h("button", {type: "button", onclick: () =>
        save(ratingBody({accepted: true, valueClass: value, note: "", marks: []}))}, t("rating.acceptedAs", {value}))),
      h("a", {href: `/tasks/${entry.task}`, "data-route": "", class: "button"}, t("rating.notAccepted"))), status);
  }

  const accepted = radios(`accepted-${entry.task}`, [["yes", t("common.yes")], ["no", t("common.no")]]);
  const value = radios(`value-${entry.task}`, [["A", "A"], ["B", "B"], ["C", "C"]]);
  const note = h("input", {type: "text", maxlength: "5000", placeholder: t("rating.note"), "aria-label": t("rating.note")});
  const decisions = /** @type {import("./rating.js").Decision[]} */ (entry.decisions);
  const marks = decisions.map((decision, i) => {
    const mark = radios(`decision-${entry.task}-${i}`, [["right", t("rating.right")], ["wrong", t("rating.wrong")]]);
    const option = decision.options ? h("select", {"aria-label": t("rating.correct")},
      ...decision.options.map((o) => h("option", {value: o}, o))) : null;
    return {decision, mark, option, element: h("li", {}, decisionText(decision), " ", mark.element, " ", option)};
  });
  return h("form", {class: "card rating", onsubmit: (event) => {
    event.preventDefault();
    const yes = accepted.value();
    const valueClass = value.value();
    if (yes === null || valueClass === null) {
      status.textContent = t("rating.incomplete");
      return;
    }
    save(ratingBody({accepted: yes === "yes", valueClass, note: note.value,
      marks: marks.filter((m) => m.mark.value() !== null)
        .map((m) => ({decision: m.decision, mark: m.mark.value() ?? "", option: m.option?.value}))}));
  }}, heading,
  h("p", {}, t("rating.accepted"), " ", accepted.element, "  ", t("rating.value"), " ", value.element), note,
  marks.length ? h("p", {class: "muted"}, t("rating.decisions")) : null,
  marks.length ? h("ul", {}, ...marks.map((m) => m.element)) : null,
  h("button", {type: "submit"}, t("rating.save")), status);
}
```

Create `core/src/ooat_core/web/app/views/inbox.js`:

```javascript
// Home (design 05 §4): what waits for me, what is stuck, the tasks, and the box for a new task.
import { questionCard, ratingCard } from "../cards.js";
import { h, report } from "../dom.js";
import { ago, clock, money, title } from "../format.js";
import { t } from "../i18n.js";

const REFRESH_MS = 15_000;
const MAX_ATTACHMENT_BYTES = 14 * 1024 * 1024;  // a request carries at most 20 MB; base64 adds a third
const DATA_CLASSES = ["public", "internal", "client_confidential", "personal"];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function inbox(root, ctx) {
  const lists = h("div");
  const form = newTask(ctx);
  root.replaceChildren(h("h1", {}, t("inbox.title")), form.element, lists);

  async function draw() {
    const [tasks, questions, ratings] = await Promise.all([
      ctx.api.json("/tasks?limit=50", {signal: ctx.signal}), ctx.api.json("/hil", {signal: ctx.signal}),
      ctx.api.json("/ratings/queue", {signal: ctx.signal})]);
    form.known(tasks.tasks);
    const again = () => { draw().catch((error) => report(lists, error)); };
    const stuck = tasks.tasks.filter((/** @type {any} */ task) => task.resume_after);
    lists.replaceChildren(
      h("h2", {}, t("inbox.waiting", {n: questions.requests.length + ratings.tasks.length})),
      ...questions.requests.map((/** @type {any} */ request) => questionCard(request, ctx, again)),
      ...ratings.tasks.map((/** @type {any} */ entry) => ratingCard(entry, ctx, {compact: true, onDone: again})),
      h("h2", {}, t("inbox.stuck", {n: stuck.length})),
      ...stuck.map((/** @type {any} */ task) => h("p", {}, "⏸ ", link(task), " ",
        t("inbox.paused", {at: clock(task.resume_after)}))),
      h("h2", {}, t("inbox.tasks")), table(tasks.tasks));
  }

  await draw();
  const timer = setInterval(() => {
    if (!lists.contains(document.activeElement)) draw().catch((error) => report(lists, error));  // keep typed text
  }, REFRESH_MS);
  ctx.signal.addEventListener("abort", () => clearInterval(timer));
}

/** @param {any} task */
function link(task) {
  return h("a", {href: `/tasks/${task.task}`, "data-route": ""}, title(task.goal));
}

/** @param {any[]} tasks */
function table(tasks) {
  const now = new Date();
  const heads = [t("inbox.task"), t("inbox.state"), t("inbox.topology"), t("inbox.cost"), t("inbox.updated")];
  return h("table", {}, h("thead", {}, h("tr", {}, ...heads.map((head) => h("th", {}, head)))),
    h("tbody", {}, ...tasks.map((task) => h("tr", {}, h("td", {}, link(task)), h("td", {}, task.state),
      h("td", {}, task.topology ?? "—"), h("td", {}, `${money(task.cost_usd)} / ${money(task.budget_usd)}`),
      h("td", {}, ago(task.updated, now))))));
}

/** @param {import("../api.js").Context} ctx */
function newTask(ctx) {
  const goal = h("textarea", {rows: "3", required: true, maxlength: "20000", placeholder: t("new.goal"),
    "aria-label": t("new.goal")});
  const acceptance = h("textarea", {rows: "2", placeholder: t("new.acceptance"), "aria-label": t("new.acceptance")});
  const project = h("input", {required: true, pattern: "[a-z0-9][a-z0-9_\\-]*", maxlength: "64",
    list: "ooat-projects", placeholder: t("new.project"), "aria-label": t("new.project")});
  const projects = h("datalist", {id: "ooat-projects"});
  const dataClass = h("select", {"aria-label": t("new.dataClass")},
    ...DATA_CLASSES.map((name) => h("option", {value: name}, name)));
  dataClass.value = "internal";
  const budget = h("input", {type: "number", min: "0.01", step: "0.01", placeholder: t("new.budget"),
    "aria-label": t("new.budget")});
  const attachments = h("input", {type: "file", multiple: true, "aria-label": t("new.attach")});
  const submit = h("button", {type: "submit"}, t("new.submit"));
  const status = h("p", {class: "status", role: "status"});
  let key = crypto.randomUUID();  // one Idempotency-Key per task typed in: a double click or a retry makes one task

  /** @param {Event} event */
  async function send(event) {
    event.preventDefault();
    const chosen = [...(attachments.files ?? [])];
    if (chosen.reduce((sum, file) => sum + file.size, 0) > MAX_ATTACHMENT_BYTES) {
      status.textContent = t("new.tooLarge");
      return;
    }
    submit.disabled = true;
    status.textContent = "";
    try {
      const body = {
        project: project.value.trim(), goal: goal.value, data_class: dataClass.value,
        acceptance: acceptance.value.split("\n").map((line) => line.trim()).filter(Boolean),
        ...(budget.value ? {budget_usd: Number(budget.value)} : {}),
        attachments: await Promise.all(chosen.map(async (file) => ({name: file.name, content_base64: await base64(file)}))),
      };
      const created = await ctx.api.json("/tasks", {method: "POST", body, headers: {"Idempotency-Key": key}});
      key = crypto.randomUUID();
      ctx.navigate(`/tasks/${created.task}`);
    } catch (error) {
      report(status, error);
    } finally {
      submit.disabled = false;
    }
  }

  const element = h("form", {class: "card new-task", onsubmit: send}, goal, acceptance,
    h("div", {class: "row"}, project, projects, dataClass, budget, attachments, submit), status);
  return {
    element,
    /** The projects of the listed tasks, offered as you type; the newest is the default. @param {any[]} tasks */
    known(tasks) {
      const names = [...new Set(tasks.map((task) => task.project).filter(Boolean))];
      projects.replaceChildren(...names.sort().map((name) => h("option", {value: name})));
      if (!project.value && names.length) project.value = tasks.find((task) => task.project)?.project ?? "";
    },
  };
}

/** @param {File} file @returns {Promise<string>} */
function base64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
```

Create `core/src/ooat_core/web/app/app.js`:

```javascript
// The web app's entry (design 05 §2, §4): the header, the screen for the path, signing out. Plain ES modules with
// JSDoc types checked by tsc; no build step (ADR 0016).
import { createApi, KEY_STORAGE } from "./api.js";
import { h, report } from "./dom.js";
import { money } from "./format.js";
import { currentLanguage, setLanguage, t } from "./i18n.js";
import { inbox } from "./views/inbox.js";

const LANGUAGE_STORAGE = "ooat.language";
const HEADER_REFRESH_MS = 30_000;
const main = /** @type {HTMLElement} */ (document.getElementById("view"));
const top = /** @type {HTMLElement} */ (document.getElementById("top"));

/** @typedef {(root: HTMLElement, ctx: import("./api.js").Context, match: RegExpMatchArray) => Promise<void>} Screen */
/** @type {[RegExp, Screen][]} */
const ROUTES = [
  [/^\/$/, (root, ctx) => inbox(root, ctx)],
];
/** @type {[string, () => string][]} */
const NAV = [
  ["/", () => t("nav.inbox")],
];

const api = createApi({fetch: window.fetch.bind(window), storage: localStorage, onSignedOut: signedOut});
/** @type {AbortController | null} */
let screen = null;
let timer = 0;

function route() {
  screen?.abort();
  screen = new AbortController();
  const ctx = {api, navigate, signal: screen.signal};
  document.documentElement.lang = currentLanguage();
  main.replaceChildren();
  drawTop().catch(() => {});  // the header is a convenience; a failed refresh keeps the last one
  for (const [pattern, show] of ROUTES) {
    const match = location.pathname.match(pattern);
    if (match) {
      show(main, ctx, match).catch((error) => report(main, error));
      return;
    }
  }
  main.append(h("p", {class: "error"}, t("app.notFound")));
}

/** @param {string} path */
function navigate(path) {
  history.pushState(null, "", path);
  route();
}

async function drawTop() {
  const [me, day, week, status] = await Promise.all([api.json("/me"), api.json("/stats?period=1d"),
    api.json("/stats?period=7d"), api.json("/status")]);
  const spent = (/** @type {any} */ stats) => money(stats.spend.metered_usd + stats.spend.shadow_usd);
  top.replaceChildren(
    h("nav", {}, ...NAV.map(([path, label]) => h("a", {href: path, "data-route": ""}, label()))),
    h("span", {class: "muted"}, t("top.spend", {day: spent(day), week: spent(week)}), " · ",
      status.runner.state === "running" ? t("top.busy") : t("top.idle")),
    h("span", {}, me.operator, " · ",
      h("button", {type: "button", class: "link", onclick: switchLanguage}, currentLanguage() === "cs" ? "EN" : "CS"),
      " · ", h("button", {type: "button", class: "link", onclick: signOut}, t("top.signOut"))));
}

function switchLanguage() {
  const next = setLanguage(currentLanguage() === "cs" ? "en" : "cs");
  localStorage.setItem(LANGUAGE_STORAGE, next);
  route();
}

async function signOut() {
  try {
    await api.json("/logout", {method: "POST", body: {}});
  } finally {
    localStorage.removeItem(KEY_STORAGE);
    signedOut();
  }
}

function signedOut() {
  screen?.abort();
  clearInterval(timer);
  top.replaceChildren();
  main.replaceChildren(h("h1", {}, "OOAT"), h("p", {}, t("app.signedOut")));
}

document.addEventListener("click", (event) => {  // in-app links change the screen without a reload
  const link = event.target instanceof Element ? event.target.closest("a[data-route]") : null;
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(link.getAttribute("href") ?? "/");
});
window.addEventListener("popstate", route);

setLanguage(localStorage.getItem(LANGUAGE_STORAGE) ?? navigator.language);
if (localStorage.getItem(KEY_STORAGE)) {
  route();
  timer = window.setInterval(() => drawTop().catch(() => {}), HEADER_REFRESH_MS);
} else {
  signedOut();
}
```

- [ ] **Step 5: Run the tests and the type check**

Run: `python -m pytest core/tests/test_web.py core/tests/test_api_security.py -q`
Expected: PASS.

Run (from `core/`): `npm test` and then `npm run check`
Expected: all Node tests PASS; `tsc` prints nothing, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add core/src/ooat_core/api.py core/src/ooat_core/web/index.html core/src/ooat_core/web/app/app.js \
  core/src/ooat_core/web/app/app.css core/src/ooat_core/web/app/rating.js core/src/ooat_core/web/app/cards.js \
  core/src/ooat_core/web/app/views/inbox.js core/src/ooat_core/web/app/i18n/en.js \
  core/src/ooat_core/web/app/i18n/cs.js core/tests/test_web.py core/web-tests/rating.test.mjs
git commit -m "feat(web): the app shell, question and rating cards, and the inbox with the new-task box (plan 05b)"
```

---

### Task 4: The task page: live timeline, artifact viewer, cancel, questions, rating

**Files:**
- Create: `core/src/ooat_core/web/app/timeline.js`, `core/src/ooat_core/web/app/views/task.js`,
  `core/web-tests/timeline.test.mjs`
- Modify: `core/src/ooat_core/web/app/app.js`, `core/src/ooat_core/web/app/i18n/{en,cs}.js`

**Interfaces:**
- Consumes: `api.follow`, `api.raw`, `questionCard`, `ratingCard`, `showMarkdown`, Task 1's artifact `name`.
- Produces: `timeline.js` `describe(event) → {tone: "info" | "ok" | "fail" | "ask", text}`; `views/task.js` `taskPage(root, ctx, id)`.

- [ ] **Step 1: Write the failing test**

Create `core/web-tests/timeline.test.mjs`:

```javascript
import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";
import { describe } from "../src/ooat_core/web/app/timeline.js";

/** @param {string} type @param {object} body @param {string} [who] */
const event = (type, body, who = "operator") => ({id: "evt_1", ts: "2026-10-11T10:02:00Z", type,
  actor: {kind: "hil", id: who}, refs: [], cost: null, body});

test("each event reads as what happened, with its tone", () => {
  setLanguage("en");
  assert.deepEqual(describe(event("TASK_SUBMITTED", {goal: "x", channel: "web"})),
    {tone: "info", text: "Submitted by operator (web)"});
  assert.deepEqual(describe(event("RESULT", {outcome: "FAILED"}, "general.worker")),
    {tone: "fail", text: "Attempt: FAILED"});
  assert.deepEqual(describe(event("TASK_CLOSED", {state: "CLOSED_DONE"}, "ooat-runtime")),
    {tone: "ok", text: "Closed: CLOSED_DONE"});
  assert.deepEqual(describe(event("HIL_RESPONSE", {request: "evt_0", choice: "run_as_is", default_applied: true},
    "default-on-silence")), {tone: "info", text: "No answer by the deadline: default run_as_is applied"});
});

test("a redacted body and an unknown type still make a line", () => {
  setLanguage("en");
  assert.deepEqual(describe(event("RESULT", {redacted: "above", link: "/tasks/t"})),
    {tone: "info", text: "RESULT · Above this session's data class: not shown."});
  assert.deepEqual(describe(event("QUOTA_WARNING", {})), {tone: "info", text: "QUOTA_WARNING"});
});
```

Run (from `core/`): `npm test`
Expected: FAIL. `timeline.test.mjs` fails with `ERR_MODULE_NOT_FOUND`.

- [ ] **Step 2: Implement**

Add these keys to `en.js`:

```javascript
  "timeline.submitted": "Submitted by {who} ({channel})",
  "timeline.gate": "Gate: {topology}",
  "timeline.contract": "Contract issued",
  "timeline.result": "Attempt: {outcome}",
  "timeline.passed": "✓ acceptance checks passed",
  "timeline.failed": "✗ acceptance checks failed",
  "timeline.decision": "{who}: {decision}",
  "timeline.asked": "? {question}",
  "timeline.answered": "Answered by {who}: {choice}",
  "timeline.defaulted": "No answer by the deadline: default {choice} applied",
  "timeline.closed": "Closed: {state}",
  "timeline.rated": "Rated by {who}: accepted {verdict}, value {value}",
  "task.timeline": "Timeline",
  "task.result": "Result",
  "task.cost": "{cost} of {budget} (estimate {estimate})",
  "task.document": "Document",
  "task.version": "Document v{n}",
  "task.markdown": "Markdown",
  "task.source": "Source",
  "task.diff": "Diff",
  "task.noEarlier": "There is no earlier document to compare with.",
  "task.binary": "Not text: download it.",
  "task.attachments": "Attachments:",
  "task.untrusted": "untrusted",
  "task.cancel": "Cancel the task",
  "task.cancelConfirm": "Cancel this task? A call in flight finishes first.",
  "task.cancelled": "Cancel requested.",
```

and to `cs.js`:

```javascript
  "timeline.submitted": "Zadal(a) {who} ({channel})",
  "timeline.gate": "Brána: {topology}",
  "timeline.contract": "Kontrakt vydán",
  "timeline.result": "Pokus: {outcome}",
  "timeline.passed": "✓ akceptační kontroly prošly",
  "timeline.failed": "✗ akceptační kontroly neprošly",
  "timeline.decision": "{who}: {decision}",
  "timeline.asked": "? {question}",
  "timeline.answered": "Odpověděl(a) {who}: {choice}",
  "timeline.defaulted": "Bez odpovědi do termínu: použita výchozí volba {choice}",
  "timeline.closed": "Uzavřeno: {state}",
  "timeline.rated": "Hodnotil(a) {who}: přijato {verdict}, hodnota {value}",
  "task.timeline": "Průběh",
  "task.result": "Výsledek",
  "task.cost": "{cost} z {budget} (odhad {estimate})",
  "task.document": "Dokument",
  "task.version": "Dokument v{n}",
  "task.markdown": "Markdown",
  "task.source": "Zdroj",
  "task.diff": "Rozdíl",
  "task.noEarlier": "Není s čím porovnat: žádný starší dokument.",
  "task.binary": "Není to text: stáhněte si ho.",
  "task.attachments": "Přílohy:",
  "task.untrusted": "nedůvěryhodná",
  "task.cancel": "Zrušit úlohu",
  "task.cancelConfirm": "Zrušit tuto úlohu? Rozběhnuté volání se nejdřív dokončí.",
  "task.cancelled": "Zrušení vyžádáno.",
```

Create `core/src/ooat_core/web/app/timeline.js`:

```javascript
// One line per ledger event on the task page (design 05 §4). "Live" is this timeline of typed events, not model
// tokens or agent conversation (spec §10).
import { text } from "./format.js";
import { t } from "./i18n.js";

/**
 * @param {any} event an event of GET /tasks/{id}/events
 * @returns {{tone: "info" | "ok" | "fail" | "ask", text: string}}
 */
export function describe(event) {
  const body = event.body ?? {};
  if (body.redacted) return {tone: "info", text: `${event.type} · ${t("common.redacted")}`};
  const who = event.actor.id;
  switch (event.type) {
    case "TASK_SUBMITTED":
      return {tone: "info", text: t("timeline.submitted", {who, channel: body.channel ?? "cli"})};
    case "TOPOLOGY_DECIDED":
      return {tone: "info", text: t("timeline.gate", {topology: body.topology})};
    case "CONTRACT_ISSUED":
      return {tone: "info", text: t("timeline.contract")};
    case "RESULT":
      return {tone: body.outcome === "FAILED" ? "fail" : "ok", text: t("timeline.result", {outcome: body.outcome})};
    case "GATE_PASSED":
      return {tone: "ok", text: t("timeline.passed")};
    case "GATE_FAILED":
      return {tone: "fail", text: t("timeline.failed")};
    case "DECISION":
      return {tone: "info", text: t("timeline.decision", {who, decision: body.decision})};
    case "HIL_REQUEST":
      return {tone: "ask", text: t("timeline.asked", {question: text(body.question)})};
    case "HIL_RESPONSE":
      return {tone: "info", text: body.default_applied ? t("timeline.defaulted", {choice: body.choice})
        : t("timeline.answered", {who, choice: body.choice ?? body.text ?? ""})};
    case "TASK_CLOSED":
      return {tone: body.state === "CLOSED_DONE" ? "ok" : "fail", text: t("timeline.closed", {state: body.state})};
    case "TASK_RATED":
      return {tone: "info", text: t("timeline.rated", {who, value: body.value_class,
        verdict: body.accepted ? t("common.yes") : t("common.no")})};
    default:
      return {tone: "info", text: event.type};
  }
}
```

Create `core/src/ooat_core/web/app/views/task.js`:

```javascript
// A task (design 05 §4): its live timeline, the document of every attempt (rendered, as source, as a diff with the
// attempt before), its attachments, its open questions, the rating card once closed, and cancel while open.
import { questionCard, ratingCard } from "../cards.js";
import { h, report } from "../dom.js";
import { clock, money, text, title } from "../format.js";
import { t } from "../i18n.js";
import { showMarkdown } from "../markdown.js";
import { describe } from "../timeline.js";

const CLOSED = ["CLOSED_DONE", "CLOSED_PARTIAL", "CLOSED_ABSTAINED", "CANCELLED"];
const REDRAW_ON = ["RESULT", "HIL_REQUEST", "HIL_RESPONSE", "TASK_CLOSED"];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx @param {string} id */
export async function taskPage(root, ctx, id) {
  const path = `/tasks/${encodeURIComponent(id)}`;
  const head = h("header");
  const actions = h("div");
  const timeline = h("ol", {class: "timeline"});
  const result = h("div");
  root.replaceChildren(head, actions, h("div", {class: "columns"},
    h("section", {}, h("h2", {}, t("task.timeline")), timeline),
    h("section", {}, h("h2", {}, t("task.result")), result)));

  async function draw() {
    const detail = await ctx.api.json(path, {signal: ctx.signal});
    head.replaceChildren(h("h1", {}, title(detail.goal)), h("p", {class: "muted"}, [detail.state,
      detail.topology ?? "—", t("task.cost", {cost: money(detail.cost_usd), budget: money(detail.budget_usd),
        estimate: money(detail.estimate_usd)})].join(" · ")));
    await drawActions(actions, ctx, detail, () => { draw().catch((error) => report(actions, error)); });
    drawResult(result, ctx, detail);
    return detail;
  }

  const detail = await draw();
  const first = await ctx.api.json(`${path}/events`, {signal: ctx.signal});
  timeline.replaceChildren(...first.events.map(line));
  if (!CLOSED.includes(detail.state)) {
    ctx.api.follow(id, first.next, (event) => {
      timeline.append(line(event));
      if (REDRAW_ON.includes(event.type)) draw().catch((error) => report(actions, error));
    }, ctx.signal).catch((error) => report(actions, error));
  }
}

/** @param {any} event */
function line(event) {
  const {tone, text: what} = describe(event);
  return h("li", {class: tone}, h("time", {datetime: event.ts}, clock(event.ts)), what,
    event.cost?.usd ? ` · ${money(event.cost.usd)}` : "");
}

/**
 * @param {HTMLElement} element @param {import("../api.js").Context} ctx @param {any} detail
 * @param {() => void} again redraws the page's state after an action
 */
async function drawActions(element, ctx, detail, again) {
  /** @type {HTMLElement[]} */
  const parts = detail.questions.map((/** @type {any} */ request) => questionCard(request, ctx, again));
  if (CLOSED.includes(detail.state)) {
    const queue = await ctx.api.json("/ratings/queue", {signal: ctx.signal});
    const entry = queue.tasks.find((/** @type {any} */ e) => e.task === detail.task);
    if (entry) parts.push(ratingCard(entry, ctx, {compact: false, onDone: again}));
  } else {
    const status = h("span", {class: "status", role: "status"});
    parts.push(h("p", {}, h("button", {type: "button", class: "danger", onclick: async () => {
      if (!confirm(t("task.cancelConfirm"))) return;
      try {
        await ctx.api.json(`/tasks/${encodeURIComponent(detail.task)}/cancel`, {method: "POST", body: {}});
        status.textContent = t("task.cancelled");
      } catch (error) {
        report(status, error);
      }
    }}, t("task.cancel")), " ", status));
  }
  element.replaceChildren(...parts);
}

/** @param {HTMLElement} element @param {import("../api.js").Context} ctx @param {any} detail */
function drawResult(element, ctx, detail) {
  const documents = detail.artifacts.filter((/** @type {any} */ a) => a.type !== "attachment");
  const attachments = detail.artifacts.filter((/** @type {any} */ a) => a.type === "attachment");
  /** @type {HTMLElement[]} */
  const parts = [];
  if (detail.result) parts.push(h("p", {}, text(detail.result.summary)));
  if (documents.length) parts.push(...viewer(ctx, documents));
  if (attachments.length) {
    parts.push(h("p", {}, t("task.attachments"), ...attachments.map((/** @type {any} */ a) => h("span", {}, " ",
      h("button", {type: "button", class: "link", disabled: !a.readable, onclick: () =>
        download(ctx, a).catch((error) => report(element, error))},
      `${a.name ?? a.ref}${a.untrusted ? ` (${t("task.untrusted")})` : ""}`)))));
  }
  element.replaceChildren(...parts);
}

/** @param {import("../api.js").Context} ctx @param {any[]} documents oldest first */
function viewer(ctx, documents) {
  const view = h("div", {class: "viewer"});
  const select = h("select", {"aria-label": t("task.document")},
    ...documents.map((a, i) => h("option", {value: a.ref}, t("task.version", {n: i + 1}))));
  select.value = documents[documents.length - 1].ref;
  /** @type {[string, string][]} */
  const modes = [["markdown", t("task.markdown")], ["source", t("task.source")], ["diff", t("task.diff")]];
  let mode = "markdown";
  const buttons = modes.map(([name, label]) => h("button", {type: "button", onclick: () => {
    mode = name;
    show().catch((error) => report(view, error));
  }}, label));

  async function show() {
    buttons.forEach((button, i) => button.classList.toggle("active", modes[i][0] === mode));
    const index = documents.findIndex((a) => a.ref === select.value);
    if (mode === "diff") {
      if (index === 0) return view.replaceChildren(h("p", {class: "muted"}, t("task.noEarlier")));
      const diff = await fetchText(ctx, `/artifacts/${encodeURIComponent(select.value)}/diff?against=${
        encodeURIComponent(documents[index - 1].ref)}`);
      return view.replaceChildren(diff === null ? h("p", {class: "muted"}, t("common.redacted")) : diffView(diff));
    }
    const body = await fetchText(ctx, `/artifacts/${encodeURIComponent(select.value)}`);
    if (body === null) view.replaceChildren(h("p", {class: "muted"}, t("common.redacted")));
    else if (mode === "markdown") showMarkdown(view, body);
    else view.replaceChildren(sourceView(body));
  }

  select.addEventListener("change", () => show().catch((error) => report(view, error)));
  show().catch((error) => report(view, error));
  return [h("div", {class: "actions"}, select, ...buttons), view];
}

/**
 * Text of an artifact or a diff; null for a redaction stub (above the reader's data class).
 * @param {import("../api.js").Context} ctx @param {string} path
 */
async function fetchText(ctx, path) {
  const response = await ctx.api.raw(path, ctx.signal);
  const kind = response.headers.get("content-type") ?? "";
  if (kind.startsWith("application/json")) return null;
  if (!kind.startsWith("text/")) return t("task.binary");
  return response.text();
}

/** @param {string} body */
function sourceView(body) {
  return h("pre", {class: "source"}, ...body.split("\n").map((row, i) =>
    h("span", {}, h("span", {class: "ln"}, String(i + 1)), `${row}\n`)));
}

/** @param {string} diff */
function diffView(diff) {
  return h("pre", {class: "diff"}, ...diff.split("\n").map((row) => h("span", {
    class: row.startsWith("@@") ? "hunk" : row.startsWith("+") ? "add" : row.startsWith("-") ? "del" : undefined,
  }, `${row}\n`)));
}

/**
 * Saves an artifact through fetch and a short-lived object URL: a plain link cannot carry the session key.
 * @param {import("../api.js").Context} ctx @param {any} artifact
 */
async function download(ctx, artifact) {
  const response = await ctx.api.raw(`/artifacts/${encodeURIComponent(artifact.ref)}`, ctx.signal);
  const url = URL.createObjectURL(await response.blob());
  h("a", {href: url, download: artifact.name ?? artifact.ref}).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

In `core/src/ooat_core/web/app/app.js`, replace:

```javascript
import { inbox } from "./views/inbox.js";
```

with:

```javascript
import { inbox } from "./views/inbox.js";
import { taskPage } from "./views/task.js";
```

and replace:

```javascript
  [/^\/$/, (root, ctx) => inbox(root, ctx)],
];
```

with:

```javascript
  [/^\/$/, (root, ctx) => inbox(root, ctx)],
  [/^\/tasks\/([A-Za-z0-9_]+)$/, (root, ctx, match) => taskPage(root, ctx, match[1])],
];
```

- [ ] **Step 3: Run the tests and the type check**

Run (from `core/`): `npm test` and then `npm run check`
Expected: PASS; `tsc` prints nothing.

Run: `python -m pytest core/tests/test_web.py -q`
Expected: PASS (the guard tests now cover `task.js`: no `innerHTML` outside `markdown.js`).

- [ ] **Step 4: Commit**

```bash
git add core/src/ooat_core/web/app/timeline.js core/src/ooat_core/web/app/views/task.js \
  core/src/ooat_core/web/app/app.js core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js \
  core/web-tests/timeline.test.mjs
git commit -m "feat(web): the task page with the live timeline, the document viewer and diff, cancel and rating (plan 05b)"
```

---

### Task 5: The Usage screen

**Files:**
- Create: `core/src/ooat_core/web/app/views/usage.js`
- Modify: `core/src/ooat_core/web/app/format.js` (`percent`), `core/web-tests/format.test.mjs`,
  `core/src/ooat_core/web/app/app.js`, `core/src/ooat_core/web/app/i18n/{en,cs}.js`

**Interfaces:**
- Consumes: `GET /stats?period=&project=&group=` (05a `stats.usage`: `spend`, `groups[{key, calls, tokens_in, tokens_out, metered_usd, shadow_usd}]`, `tasks`, `hil`).
- Produces: `format.js` `percent(fraction)`; `views/usage.js` `usage(root, ctx)`.

- [ ] **Step 1: Write the failing test**

Append to `core/web-tests/format.test.mjs`:

```javascript
import { percent } from "../src/ooat_core/web/app/format.js";

test("a fraction reads as a signed percentage", () => {
  assert.deepEqual([percent(0.08), percent(-0.125), percent(0), percent(null)], ["+8 %", "-13 %", "0 %", "—"]);
});
```

Run (from `core/`): `npm test`
Expected: FAIL. `format.test.mjs` fails with `does not provide an export named 'percent'`.

- [ ] **Step 2: Implement**

Append to `core/src/ooat_core/web/app/format.js`:

```javascript
/** Estimate vs actual and the like: 0.08 → "+8 %". @param {number | null | undefined} fraction */
export function percent(fraction) {
  if (fraction === null || fraction === undefined) return "—";
  // Halves round away from zero (Math.round(-12.5) is -12); `|| 0` turns -0 into 0.
  const rounded = Math.sign(fraction) * Math.round(Math.abs(fraction) * 100) || 0;
  return `${rounded > 0 ? "+" : ""}${rounded} %`;
}
```

Add these keys to `en.js`:

```javascript
  "nav.usage": "Usage",
  "usage.title": "Usage",
  "usage.period": "Period",
  "usage.p1d": "1 day",
  "usage.p7d": "7 days",
  "usage.p30d": "30 days",
  "usage.p90d": "90 days",
  "usage.pall": "all time",
  "usage.project": "Project",
  "usage.allProjects": "all projects",
  "usage.spend": "Spend {total} (metered {metered} · subscription shadow {shadow})",
  "usage.byRole": "By role",
  "usage.byConnector": "By connector",
  "usage.calls": "Calls",
  "usage.tokens": "Tokens in / out",
  "usage.metered": "Metered",
  "usage.shadow": "Shadow",
  "usage.tasks": "Tasks closed {closed} · accepted {accepted} of {rated} rated · cost per accepted task {per} · estimate vs actual {delta}",
  "usage.hil": "Questions {questions} · answered {answered} · median wait {wait} · defaults applied {defaults}",
```

and to `cs.js`:

```javascript
  "nav.usage": "Spotřeba",
  "usage.title": "Spotřeba",
  "usage.period": "Období",
  "usage.p1d": "1 den",
  "usage.p7d": "7 dní",
  "usage.p30d": "30 dní",
  "usage.p90d": "90 dní",
  "usage.pall": "celkem",
  "usage.project": "Projekt",
  "usage.allProjects": "všechny projekty",
  "usage.spend": "Útrata {total} (účtováno {metered} · stínová hodnota předplatného {shadow})",
  "usage.byRole": "Podle role",
  "usage.byConnector": "Podle konektoru",
  "usage.calls": "Volání",
  "usage.tokens": "Tokeny vstup / výstup",
  "usage.metered": "Účtováno",
  "usage.shadow": "Stínově",
  "usage.tasks": "Uzavřené úlohy {closed} · přijato {accepted} z {rated} hodnocených · cena za přijatou úlohu {per} · odhad vs skutečnost {delta}",
  "usage.hil": "Dotazy {questions} · zodpovězeno {answered} · medián čekání {wait} · výchozí volba použita {defaults}",
```

Create `core/src/ooat_core/web/app/views/usage.js`:

```javascript
// Usage (design 05 §4, §8): spend, calls and tokens by role and by connector, tasks by outcome, waiting for answers.
import { h, report } from "../dom.js";
import { count, money, percent } from "../format.js";
import { t } from "../i18n.js";

/** @type {[string, () => string][]} */
const PERIODS = [["1d", () => t("usage.p1d")], ["7d", () => t("usage.p7d")], ["30d", () => t("usage.p30d")],
  ["90d", () => t("usage.p90d")], ["all", () => t("usage.pall")]];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function usage(root, ctx) {
  const period = h("select", {"aria-label": t("usage.period")},
    ...PERIODS.map(([value, label]) => h("option", {value}, label())));
  period.value = "7d";
  const project = h("select", {"aria-label": t("usage.project")}, h("option", {value: ""}, t("usage.allProjects")));
  const tasks = await ctx.api.json("/tasks?limit=200", {signal: ctx.signal});
  const names = [...new Set(tasks.tasks.map((/** @type {any} */ task) => task.project).filter(Boolean))];
  for (const name of names.sort()) project.append(h("option", {value: name}, name));
  const body = h("div");
  root.replaceChildren(h("h1", {}, t("usage.title")), h("div", {class: "row"}, period, project), body);

  async function draw() {
    const query = (/** @type {string} */ group) => `/stats?period=${period.value}&group=${group}${
      project.value ? `&project=${encodeURIComponent(project.value)}` : ""}`;
    const [byRole, byConnector] = await Promise.all([ctx.api.json(query("role"), {signal: ctx.signal}),
      ctx.api.json(query("connector"), {signal: ctx.signal})]);
    const {spend, tasks: closed, hil} = byRole;
    body.replaceChildren(
      h("p", {}, t("usage.spend", {total: money(spend.metered_usd + spend.shadow_usd),
        metered: money(spend.metered_usd), shadow: money(spend.shadow_usd)})),
      h("div", {class: "columns"}, groups(t("usage.byRole"), byRole.groups),
        groups(t("usage.byConnector"), byConnector.groups)),
      h("p", {}, t("usage.tasks", {closed: closed.closed, accepted: closed.accepted, rated: closed.rated,
        per: money(closed.cost_per_accepted_usd), delta: percent(closed.estimate_vs_actual)})),
      h("p", {}, t("usage.hil", {questions: hil.questions, answered: hil.answered, defaults: hil.defaults_applied,
        wait: hil.median_wait_minutes === null ? "—" : t("time.minutes", {n: Math.round(hil.median_wait_minutes)})})));
  }

  const again = () => { draw().catch((error) => report(body, error)); };
  period.addEventListener("change", again);
  project.addEventListener("change", again);
  await draw();
}

/** @param {string} heading @param {any[]} rows */
function groups(heading, rows) {
  const number = (/** @type {string} */ value) => h("td", {class: "number"}, value);
  return h("section", {}, h("h2", {}, heading), h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, ""), ...[t("usage.calls"), t("usage.tokens"), t("usage.metered"),
      t("usage.shadow")].map((name) => h("th", {class: "number"}, name)))),
    h("tbody", {}, ...rows.map((row) => h("tr", {}, h("td", {}, row.key), number(String(row.calls)),
      number(`${count(row.tokens_in)} / ${count(row.tokens_out)}`), number(money(row.metered_usd)),
      number(money(row.shadow_usd)))))));
}
```

In `core/src/ooat_core/web/app/app.js`, replace:

```javascript
import { taskPage } from "./views/task.js";
```

with:

```javascript
import { taskPage } from "./views/task.js";
import { usage } from "./views/usage.js";
```

replace:

```javascript
  [/^\/tasks\/([A-Za-z0-9_]+)$/, (root, ctx, match) => taskPage(root, ctx, match[1])],
];
```

with:

```javascript
  [/^\/tasks\/([A-Za-z0-9_]+)$/, (root, ctx, match) => taskPage(root, ctx, match[1])],
  [/^\/usage$/, (root, ctx) => usage(root, ctx)],
];
```

and replace:

```javascript
  ["/", () => t("nav.inbox")],
];
```

with:

```javascript
  ["/", () => t("nav.inbox")],
  ["/usage", () => t("nav.usage")],
];
```

- [ ] **Step 3: Run the tests and the type check**

Run (from `core/`): `npm test` and then `npm run check`
Expected: PASS; `tsc` prints nothing.

- [ ] **Step 4: Commit**

```bash
git add core/src/ooat_core/web/app/views/usage.js core/src/ooat_core/web/app/format.js \
  core/src/ooat_core/web/app/app.js core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js \
  core/web-tests/format.test.mjs
git commit -m "feat(web): the Usage screen by role and connector, tasks and questions (plan 05b)"
```

---

### Task 6: The Connectors screen

**Files:**
- Create: `core/src/ooat_core/web/app/views/connectors.js`
- Modify: `core/src/ooat_core/web/app/app.js`, `core/src/ooat_core/web/app/i18n/{en,cs}.js`

**Interfaces:**
- Consumes the 05a endpoints:
  - `GET /connectors` → `{connectors: [{id, state, detail, tiers, automation, stale, unattended, responsibility_until, blocked}]}`;
  - `GET /connectors/{id}/card` → `{connector, card}`, where `card` is the plain text the CLI prints;
  - `POST /connectors/{id}/enable` with `{classes, automation, confirm, responsibility?: {processing_regions?, no_training?}}`;
  - `POST /connectors/{id}/disable` with `{reason}`;
  - `GET /connectors/{id}/hooks` → `{hooks: [{path, sha256, text}]}`;
  - `POST /connectors/{id}/approve-hooks` with `{confirm, hooks: [{path, sha256}]}`.
- Produces: `views/connectors.js` `connectors(root, ctx)`.

There is no Node test in this task: the screen holds no logic beyond building request bodies from form fields.
The server-side rules (typed confirmation, responsibility, hooks changed) are tested in 05a. `tsc` and the Task 7
smoke check cover it.

- [ ] **Step 1: Implement**

Add these keys to `en.js`:

```javascript
  "nav.connectors": "Connectors",
  "connectors.title": "Connectors",
  "connectors.card": "Card",
  "connectors.disable": "Disable",
  "connectors.hooks": "Hooks",
  "connectors.allow": "Allow these data classes:",
  "connectors.automation": "Unattended use: the provider's terms permit it, and I confirm it",
  "connectors.responsibility": "Client or personal data is your responsibility (ADR 0012)",
  "connectors.regions": "Processing regions you checked, separated by commas",
  "connectors.noTraining": "The provider does not train on these inputs",
  "connectors.confirm": "Type the connector id to confirm",
  "connectors.enable": "Enable",
  "connectors.enabled": "Enabled.",
  "connectors.reason": "Why disable it?",
  "connectors.disabled": "Disabled.",
  "connectors.noHooks": "This connector has no hooks.",
  "connectors.hooksOf": "Hooks of {id}",
  "connectors.approve": "Approve these hooks",
  "connectors.approved": "Hooks approved.",
```

and to `cs.js`:

```javascript
  "nav.connectors": "Konektory",
  "connectors.title": "Konektory",
  "connectors.card": "Karta",
  "connectors.disable": "Vypnout",
  "connectors.hooks": "Hooky",
  "connectors.allow": "Povolit tyto datové třídy:",
  "connectors.automation": "Bezobslužné použití: podmínky poskytovatele ho dovolují a já to potvrzuji",
  "connectors.responsibility": "Za klientská nebo osobní data odpovídáte vy (ADR 0012)",
  "connectors.regions": "Ověřené regiony zpracování, oddělené čárkou",
  "connectors.noTraining": "Poskytovatel se na těchto vstupech neučí",
  "connectors.confirm": "Pro potvrzení napište id konektoru",
  "connectors.enable": "Zapnout",
  "connectors.enabled": "Zapnuto.",
  "connectors.reason": "Proč ho vypínáte?",
  "connectors.disabled": "Vypnuto.",
  "connectors.noHooks": "Tento konektor nemá hooky.",
  "connectors.hooksOf": "Hooky konektoru {id}",
  "connectors.approve": "Schválit tyto hooky",
  "connectors.approved": "Hooky schváleny.",
```

Create `core/src/ooat_core/web/app/views/connectors.js`:

```javascript
// Connectors (design 05 §4; spec §9 rule 1; ADR 0012, 0015): the consequences card, the classes to allow, the
// operator's responsibility for client or personal data, a typed confirmation; hooks are read before approval. The
// operator is the session's, never a form field.
import { h, report } from "../dom.js";
import { t } from "../i18n.js";

const CLASSES = ["public", "internal", "client_confidential", "personal"];
const RESPONSIBLE = ["client_confidential", "personal"];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function connectors(root, ctx) {
  const list = h("div");
  const panel = h("section");
  root.replaceChildren(h("h1", {}, t("connectors.title")), list, panel);
  /** @param {string} id */
  const base = (id) => `/connectors/${encodeURIComponent(id)}`;

  async function draw() {
    const found = await ctx.api.json("/connectors", {signal: ctx.signal});
    list.replaceChildren(h("table", {}, h("tbody", {}, ...found.connectors.map((/** @type {any} */ c) => h("tr", {},
      h("td", {}, c.id), h("td", {}, `${c.state === "enabled" ? "●" : "○"} ${c.state}`),
      h("td", {class: "muted"}, c.blocked ?? c.detail),
      h("td", {}, h("button", {type: "button", onclick: () => card(c.id).catch((e) => report(panel, e))},
        t("connectors.card")), " ",
      c.state === "enabled" ? h("button", {type: "button", onclick: () => disable(c.id).catch((e) => report(panel, e))},
        t("connectors.disable")) : null, " ",
      h("button", {type: "button", onclick: () => hooks(c.id).catch((e) => report(panel, e))},
        t("connectors.hooks"))))))));
  }

  /** @param {string} id */
  async function card(id) {
    const found = await ctx.api.json(`${base(id)}/card`, {signal: ctx.signal});
    const boxes = CLASSES.map((name) => h("input", {type: "checkbox", value: name}));
    const automation = h("input", {type: "checkbox"});
    const regions = h("input", {type: "text", "aria-label": t("connectors.regions")});
    const noTraining = h("input", {type: "checkbox"});
    const responsibility = h("fieldset", {hidden: true}, h("legend", {}, t("connectors.responsibility")),
      h("label", {}, t("connectors.regions"), " ", regions), h("br"), h("label", {}, noTraining,
        t("connectors.noTraining")));
    const responsible = () => boxes.some((box) => box.checked && RESPONSIBLE.includes(box.value));
    for (const box of boxes) box.addEventListener("change", () => { responsibility.hidden = !responsible(); });
    const confirm = h("input", {type: "text", autocomplete: "off", placeholder: id, "aria-label": t("connectors.confirm")});
    const status = h("p", {class: "status", role: "status"});
    panel.replaceChildren(h("h2", {}, id), h("pre", {class: "card"}, found.card), h("form", {onsubmit: async (event) => {
      event.preventDefault();
      const listed = regions.value.split(",").map((region) => region.trim()).filter(Boolean);
      const body = {classes: boxes.filter((box) => box.checked).map((box) => box.value),
        automation: automation.checked, confirm: confirm.value.trim(),
        ...(responsible() ? {responsibility: {...(listed.length ? {processing_regions: listed} : {}),
          ...(noTraining.checked ? {no_training: true} : {})}} : {})};
      try {
        await ctx.api.json(`${base(id)}/enable`, {method: "POST", body});
        status.textContent = t("connectors.enabled");
        await draw();
      } catch (error) {
        report(status, error);
      }
    }}, h("p", {}, t("connectors.allow"), ...boxes.map((box) => h("label", {}, " ", box, box.value))),
    h("p", {}, h("label", {}, automation, t("connectors.automation"))), responsibility,
    h("p", {}, h("label", {}, t("connectors.confirm"), " ", confirm), " ",
      h("button", {type: "submit"}, t("connectors.enable"))), status));
  }

  /** @param {string} id */
  async function disable(id) {
    const reason = prompt(t("connectors.reason"))?.trim();
    if (!reason) return;
    await ctx.api.json(`${base(id)}/disable`, {method: "POST", body: {reason}});
    panel.replaceChildren(h("p", {class: "status"}, t("connectors.disabled")));
    await draw();
  }

  /** @param {string} id */
  async function hooks(id) {
    const found = await ctx.api.json(`${base(id)}/hooks`, {signal: ctx.signal});
    if (!found.hooks.length) {
      panel.replaceChildren(h("p", {class: "muted"}, t("connectors.noHooks")));
      return;
    }
    const confirm = h("input", {type: "text", autocomplete: "off", placeholder: id, "aria-label": t("connectors.confirm")});
    const status = h("p", {class: "status", role: "status"});
    panel.replaceChildren(h("h2", {}, t("connectors.hooksOf", {id})),
      ...found.hooks.map((/** @type {any} */ hook) => h("details", {},
        h("summary", {}, `${hook.path} · ${(hook.sha256 ?? "").slice(0, 12)}`), h("pre", {}, hook.text ?? ""))),
      h("form", {onsubmit: async (event) => {
        event.preventDefault();
        try {
          await ctx.api.json(`${base(id)}/approve-hooks`, {method: "POST", body: {confirm: confirm.value.trim(),
            hooks: found.hooks.map((/** @type {any} */ hook) => ({path: hook.path, sha256: hook.sha256}))}});
          status.textContent = t("connectors.approved");
          await draw();
        } catch (error) {
          report(status, error);
        }
      }}, h("p", {}, h("label", {}, t("connectors.confirm"), " ", confirm), " ",
        h("button", {type: "submit"}, t("connectors.approve")))), status);
  }

  await draw();
}
```

In `core/src/ooat_core/web/app/app.js`, replace:

```javascript
import { usage } from "./views/usage.js";
```

with:

```javascript
import { connectors } from "./views/connectors.js";
import { usage } from "./views/usage.js";
```

replace:

```javascript
  [/^\/usage$/, (root, ctx) => usage(root, ctx)],
];
```

with:

```javascript
  [/^\/usage$/, (root, ctx) => usage(root, ctx)],
  [/^\/connectors$/, (root, ctx) => connectors(root, ctx)],
];
```

and replace:

```javascript
  ["/usage", () => t("nav.usage")],
];
```

with:

```javascript
  ["/usage", () => t("nav.usage")],
  ["/connectors", () => t("nav.connectors")],
];
```

- [ ] **Step 2: Run the checks**

Run (from `core/`): `npm run check` and then `npm test`
Expected: `tsc` prints nothing; all Node tests PASS.

Run: `python -m pytest core/tests/test_web.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add core/src/ooat_core/web/app/views/connectors.js core/src/ooat_core/web/app/app.js \
  core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js
git commit -m "feat(web): the Connectors screen with the card, responsibility, typed confirmation and hooks (plan 05b)"
```

---

### Task 7: Documentation and the smoke check in a browser

**Files:**
- Modify: `core/description.md`, `docs/description.md`, `README.md`, `.claude/lessons.md`, `CONTRIBUTING.md`

**Interfaces:**
- Consumes: everything above. Produces: documentation of the current state; nothing in code.

- [ ] **Step 1: Smoke check (manual; nothing is committed from it)**

Write a script in the session's scratchpad (never in the repository) that builds the app as
`core/tests/api_fakes.py` `Served` does (a temporary file ledger, the scripted model and the fake Gate). It then
issues a sign-in code with `issue_login_code`, prints `http://127.0.0.1:8799/login#code=<code>`, and serves the
app with `uvicorn.run(app, host="127.0.0.1", port=8799)`. In `ServeSettings`, set `port=8799` so the Origin check
matches. Run it, open the link in a browser (the session's browser tool, or ask the owner), and check each of these:

- The sign-in link opens the inbox, signed in as `operator`. The address bar shows `/`, not the code.
- Submit a task with two "done when" lines and a small text attachment. The task page opens, and the timeline
  grows line by line while the fake runner works (the script must start the runner: `start_runner=True`).
- Double-click Submit on a second task: exactly one new task appears in the inbox.
- The result shows the document rendered as Markdown. Source shows line numbers. Diff shows the change from the
  attempt before, or "no earlier document". The attachment downloads under its file name.
- A question card answers with one click. While its note field has focus, the inbox does not wipe the typed text
  (wait 20 s).
- The compact rating card (`Accepted B`) removes the task from "Waiting for you". On another task, the full card
  saves with one decision marked Wrong.
- Usage shows the spend and both tables. Connectors shows the card, refuses a wrong typed id with its error, and
  enables with the right one.
- Switching to CS shows Czech everywhere and survives a reload. Sign out returns to the signed-out notice.
- In the developer console: no CSP violation except "inline style" notes for aligned Markdown tables, no
  uncaught error.
- With the cookie but `localStorage` cleared (developer tools → Application → Local storage → delete
  `ooat.session`), a reload shows the signed-out notice and no data.

Record anything that fails as a finding and fix it test-first in the task that owns the code. A "ruling" line
alone is not enough. If no browser is available in the session, say so in the ledger and in the final message,
and leave this step for the owner.

- [ ] **Step 2: Documentation**

In `core/description.md`, under "Key components", after the line for `api.py`, add:

```markdown
- `web/` — the web app (plan 05b): `index.html` and `app/` (ES modules with JSDoc types, checked by
  `tsc --noEmit --checkJs`, no build step; ADR 0016). `api.js` is the only door to the API: a web session is the
  HttpOnly cookie plus the session key in `localStorage["ooat.session"]`, sent as `X-CSRF-Token` on every
  request. The pure modules (`api`, `sse`, `format`, `i18n`, `markdown`, `rating`, `timeline`) are tested with
  `node --test` in `core/web-tests/`. The screens (`views/`) and the cards build elements with `dom.js` `h()`:
  never HTML from data, except Markdown rendered by the vendored markdown-it 15.0.2 with raw HTML off.
  `api.py` `app_routes()` serves the shell for `/`, `/tasks/{id}`, `/usage` and `/connectors`, and the app's
  files under `/app/`, without a session (code, no data).
```

In `docs/description.md`, in the section describing `ooat serve`, add a paragraph:

```markdown
`ooat serve` opens the web app: the inbox (new task, questions and ratings waiting, tasks paused by a provider
failure, all tasks), a task page (live timeline, the document of every attempt rendered, as source or as a diff,
attachments, cancel, the rating card), Usage (spend, calls and tokens by role and by connector) and Connectors (the
consequences card, enable with a typed confirmation, disable, hooks). English or Czech. The app is plain
JavaScript served from the `ooat-core` wheel; the operator needs no Node.
```

In `README.md`, where `ooat serve` is introduced, replace the sentence that says the web screens come with 05b (if
present) with: "`ooat serve` prints a sign-in link; it opens the web app in your browser."

In `CONTRIBUTING.md`, add a section:

```markdown
## The web app

The web app in `core/src/ooat_core/web/` is plain JavaScript with JSDoc types; there is no build step. To check it,
install Node 22 and run from `core/`: `npm ci`, `npm run check` (tsc) and `npm test` (node --test). UI strings go
in `app/i18n/en.js` and `app/i18n/cs.js`, which must have the same keys. Build the page with `h()` from `dom.js`;
`innerHTML` is allowed only in `markdown.js` (a test enforces it).
```

In `.claude/lessons.md`, add:

```markdown
- Web app (05b): a cookie is not bound to a port, so a web session needs its key (`X-CSRF-Token`, from
  `localStorage["ooat.session"]`) on every request, GETs too; `/me` never returns it. `EventSource` cannot send
  that header: the task page reads SSE through `fetch` (`api.js` `follow`). Downloads go through `fetch` and an
  object URL for the same reason.
- Web app checks run from `core/`: `npm run check` (tsc 6.0.3, `checkJs`, strict) and `npm test`
  (`node --test "web-tests/*.test.mjs"`). `core/package.json` has `"type": "module"`, so Node loads the app's
  `.js` files as ES modules. markdown-it is vendored (`app/vendor/`, SHA-256 pinned in `core/tests/test_web.py`)
  and typed through `markdown-it.esm.min.d.mts`, which re-exports the npm package's types.
```

- [ ] **Step 3: Run everything**

Run: `python -m pytest -q`
Expected: PASS (the count from Task 1 plus the Python tests of Tasks 2–3; 6 skipped).

Run (from `core/`): `npm run check` and then `npm test`
Expected: `tsc` prints nothing; all Node tests PASS.

- [ ] **Step 4: Commit**

```bash
git add core/description.md docs/description.md README.md CONTRIBUTING.md .claude/lessons.md
git commit -m "docs: the web app of ooat serve, its checks and its session key (plan 05b)"
```

---

## Self-review against the design

- §4 Inbox (new task, waiting, stuck, tasks, today/week spend, runner state): Task 3 (spend and runner in the header).
- §4 Task page (live timeline, document per attempt, Markdown / Source / Diff, attachments untrusted with download): Task 4.
- §4 Rating card (accepted, value, decisions Right/Wrong, unmarked stay unrated): Task 3 (`cards.js`, `rating.js`), on the task page in Task 4.
- §4 Connectors (card, classes, unattended use, typed confirmation, responsibility, hooks): Task 6.
- §4 Usage (period, project, by role and connector, tasks, HIL wait, defaults): Task 5.
- §2 No build step, JSDoc and tsc in CI, markdown-it with raw HTML off, `en`/`cs`: Tasks 2 and 7.
- §6:
  - every data call is authenticated (Task 1, Decision 1);
  - no secrets in the UI: the card shows names and states, the hooks text appears only in web sessions (05a);
  - CSP without inline script (Task 2 guard tests);
  - `javascript:` links refused (Task 2);
  - the operator comes from the session (Task 6 sends no name).
- §11 05b: everything above. 05c, 01c and the R3 binding are not here.
- 05a deferred minors handled here:
  - the port-blind cookie (Decision 1);
  - the shared web intake key (Decision 3: no change, with the reason);
  - the `/me` 500 (Decision 1).
  The other deferred minors stay deferred.
