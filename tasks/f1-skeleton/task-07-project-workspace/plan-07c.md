# Project Workspace in the Web App and the Chat Bridge (07c) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The operator sees what a task on a project's folders changed and can undo it from where they work:
- in the web app's task page: OOAT's list of changed files, the diff, and a revert button with a confirmation step;
- in the reference chat bridge (`ooat_client.Bridge`, which the Telegram bot uses): the diff as a file, a revert
  button that needs a second tap, the limit question with the agent's document and the diff, and a one-time notice
  when the chat's project has no folders.

**Architecture:**
- The API's task detail gains `workspace`, computed by `views.workspace_view()` from the task's `WORKSPACE_*` events:
  files, refusals, the latest diff, revert state, and whether a revert is possible.
- The web app reads it in a small pure module (`workspace.js`, tested with `node --test`) and draws it on the task
  page. The timeline gains lines for `WORKSPACE_USED` and `WORKSPACE_REVERTED`.
- The bridge reads the same detail and posts the diff with its result.
- Every revert, whether answering the limit question with `revert` or reverting a closed task, gets its second
  confirmation on the surface:
  - web: `confirm()`;
  - chat: a second button;
  - CLI: `ooat hil answer --choice revert` asks, as `ooat task revert` already does.

**Tech Stack:**
- Python 3.12+ (FastAPI views, `ooat-client` standard library only), pytest.
- Plain JavaScript with JSDoc types checked by `tsc --noEmit --checkJs` and tested by `node --test` (ADR 0016, no
  build step).

**Spec:** `tasks/f1-skeleton/task-07-project-workspace/design.md` (approved 2026-10-12; §7 "Result" and "Revert",
§8 the question's one-tap buttons, §12 the second confirmation: "web: a confirm step; chat: a second tap on 'Yes,
revert'"); ADR 0017; `docs/chat-bridge.md` (the bridge contract). Built on plan 07b as merged (PR #46).

## Global Constraints

- **No revert without a second confirmation on a surface** (owner, 2026-10-12 and 2026-10-13):
  - web: a `confirm()` step;
  - chat: a second button, "Yes, revert";
  - CLI: a typed `y`.
  The server's endpoints stay single-call; the confirmation belongs to the surface.
- **Above the reader's data class, nothing about the files is shown** (ADR 0016, design 05 §14): paths, counts and
  the diff become the stub. The chat bridge's token is capped at `internal`.
- The web app has no build step and no new dependency. Every string goes through `t()` with an English and a Czech
  entry; `tsc` checks that `cs.js` has exactly `en.js`'s keys.
- The bridge stays standard library only, and its button data stays at most 64 bytes (Telegram's callback-data
  limit).
- Only `ooat-core` writes the ledger. Surfaces call the existing endpoints: `POST /tasks/{id}/revert`,
  `POST /hil/{evt}/answer`.
- Code, comments, docs and commits are in English, with lines of at most 120 characters (wrap where this plan's code
  is longer; that needs no ruling).

**Decisions this plan takes where the design is silent** (for the owner's review; each is cheap to change):

1. **The limit question in the chat.** The question no longer quotes the agent's summary (07b final review: a
   data-class leak). So the bridge first posts the limited document and the diff, both within the token's class,
   then the question with its four buttons.
2. **Where the revert offer appears in the chat.** It sits in the result's footer, under the rating buttons, while
   a revert is possible. A rating that rejects the result therefore has revert in the same message (design §7).
3. **The notice for a project without folders.** The bridge says "this project has no folders in OOAT" once per
   bridge instance, after the first task whose submission has no `workspace`. A restarted bot says it again once.
4. **Which artifacts the web app's document viewer shows.** It shows only `markdown_document` artifacts. After
   07b, a task's artifacts also include `workspace_original` and `workspace_diff`, which would otherwise show up
   as extra "versions" of the document (a 07b bug this plan fixes).
5. **When a revert is possible.** `revertable` is true when the task is closed, its worker changed or created
   files, and nothing was reverted yet. A task that only created files can still be "reverted": nothing is written
   back, and the created files are listed as kept.

## Review Focus

- **A task above the reader's cap**: the API's `workspace` must be the stub. The web app shows no paths and the
  bridge posts no diff, only the notice. Tests in Tasks 1 and 4.
- **The second confirmation is really needed**: one tap on the chat's revert button, or one click without the
  confirm step, must write nothing. Tests in Tasks 2 and 4. The web's `confirm()` is checked by reading the code.
- **A revert that skips files** (changed since, someone else's edit, locked): the surfaces show the skipped files
  with their reason, never "done". Tests in Tasks 3 and 4.
- **A task that changed nothing, or only read**: no revert button, no diff file, no empty "Files changed" section.
  Tests in Tasks 1 and 4.
- **The web viewer after 07b**: the version picker lists only the documents, never an original or a diff. Test in
  Task 1 (the detail's artifact types) and a check in Task 3.

## File Structure

| File | Responsibility |
|---|---|
| `core/src/ooat_core/views.py` (modify) | `workspace_view(events, visible)`; `task_detail` gains `workspace` |
| `core/src/ooat_core/task_cli.py` (modify) | `ooat hil answer --choice revert` asks to confirm |
| `core/src/ooat_core/web/app/workspace.js` (create) | pure helpers: a file's line, the revert report |
| `core/src/ooat_core/web/app/timeline.js` (modify) | lines for `WORKSPACE_USED` and `WORKSPACE_REVERTED` |
| `core/src/ooat_core/web/app/views/task.js` (modify) | documents only in the viewer; the "Files changed" section with the diff and revert |
| `core/src/ooat_core/web/app/cards.js` (modify) | the question card confirms a `revert` answer |
| `core/src/ooat_core/web/app/i18n/en.js`, `cs.js` (modify) | the new strings |
| `sdk/python/src/ooat_client/bridge.py`, `texts.py` (modify) | diff file, revert buttons with a second tap, the limit question's document, the text-only notice |
| Tests | `core/tests/test_views.py`, `test_api.py`, `test_task_cli.py`, `test_bridge.py`, `core/web-tests/timeline.test.mjs`, `core/web-tests/workspace.test.mjs` (new) |
| Docs | `docs/chat-bridge.md`, `docs/description.md`, `core/description.md`, `sdk/python/README.md` |

---

### Task 1: The task detail shows the workspace

**Files:**
- Modify: `core/src/ooat_core/views.py`
- Test: `core/tests/test_views.py`, `core/tests/test_api.py`

**Interfaces:**
- Produces: `views.workspace_view(events: list[dict], visible: bool) -> dict | None`, which returns
  - `None` for a text-only task (no `body.workspace` on `TASK_SUBMITTED`);
  - the stub when the task is above the reader's cap;
  - otherwise:

  ```
  {"write": bool, "folders": [str],
   "files": [{"path", "kind": "changed" | "created", "added", "removed"}],
   "refused": int, "limit": bool, "diff": artifact ref | None,
   "reverted": {"restored", "skipped", "kept", "by", "ts"} | None,
   "revertable": bool}
  ```

  `task_detail(...)["workspace"]` is this value.

- [ ] **Step 1: Write the failing tests**

Append to `core/tests/test_views.py`:

```python
from test_runtime_workspace import EDIT, Setup as ProjectSetup

from ooat_core.views import workspace_view


def test_the_workspace_view_lists_what_the_worker_changed_and_whether_it_can_be_reverted(tmp_path):
    setup = ProjectSetup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    events = setup.ledger.events(task=task)
    view = workspace_view(events, visible=True)
    assert view["write"] is True and view["folders"] == ["Bots"]
    assert view["files"] == [{"path": "Bots/src/bot.py", "kind": "changed", "added": 1, "removed": 1}]
    assert view["diff"] and view["revertable"] is True and view["reverted"] is None and view["limit"] is False
    setup.runtime.revert(task, operator="Martin", channel="web")
    view = workspace_view(setup.ledger.events(task=task), visible=True)
    assert view["revertable"] is False and view["reverted"]["restored"] == ["Bots/src/bot.py"]
    assert view["reverted"]["by"] == "Martin"


def test_a_workspace_above_the_cap_is_a_stub_and_a_text_task_has_none(tmp_path):
    setup = ProjectSetup(tmp_path)
    task = setup.submit()
    setup.runtime.run(task)
    assert workspace_view(setup.ledger.events(task=task), visible=False) == stub(task)
    text_task = setup.runtime.submit(operator="Martin", goal="Shrň smlouvu.", acceptance=["Má 3 věty."], project="docs")
    assert workspace_view(setup.ledger.events(task=text_task), visible=True) is None


def test_an_open_task_or_one_that_only_read_cannot_be_reverted(tmp_path):
    setup = ProjectSetup(tmp_path, model=WorkspaceModel([[("read_file", {"path": "Bots/src/bot.py"})]]))
    task = setup.submit()
    setup.runtime.run(task)
    view = workspace_view(setup.ledger.events(task=task), visible=True)
    assert view["files"] == [] and view["diff"] is None and view["revertable"] is False
```

with `stub` added to the `ooat_core.views` import and `WorkspaceModel` to the `runtime_fakes` import.

Append to `core/tests/test_api.py` (after its 07b tests, which define `on_project`):

```python
def test_the_task_detail_carries_the_workspace_and_the_viewer_sees_documents_by_type(tmp_path):
    root, served = on_project(tmp_path)
    bot = served.token()
    task = served.submit(bot, project="bots", acceptance=CRITERIA)["task"]
    served.run()
    detail = get(served, f"/api/v1/tasks/{task}", bot)
    assert detail["workspace"]["files"][0]["path"] == "Bots/src/bot.py" and detail["workspace"]["revertable"]
    types = {a["type"] for a in detail["artifacts"]}
    assert {"markdown_document", "workspace_original", "workspace_diff"} <= types
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest core/tests/test_views.py core/tests/test_api.py -q`
Expected: FAIL with `ImportError: cannot import name 'workspace_view'`, and `KeyError: 'workspace'` in the API test.

- [ ] **Step 3: Implement** (`core/src/ooat_core/views.py`)

```python
def workspace_view(events: list[dict], visible: bool) -> dict | None:
    """What a task on a project's folders did there, for the web app and the chat bridge (design 07 §7): None for a
    text-only task, the stub above the reader's class (paths and the diff are the project's content)."""
    submitted = next(e for e in events if e["type"] == "TASK_SUBMITTED")
    workspace = submitted["body"].get("workspace")
    if workspace is None:
        return None
    if not visible:
        return stub(submitted["task"])
    used = [e["body"] for e in events if e["type"] == "WORKSPACE_USED" and e["body"]["by"] == "worker"]
    files: dict[str, dict] = {}
    for body in used:
        for item in body["created"]:
            entry = files.setdefault(item["path"], {"path": item["path"], "kind": "created", "added": 0, "removed": 0})
            entry["added"] += item["added"]
        for item in body["changed"]:
            entry = files.setdefault(item["path"], {"path": item["path"], "kind": "changed", "added": 0, "removed": 0})
            entry["added"], entry["removed"] = entry["added"] + item["added"], entry["removed"] + item["removed"]
    diffs = [body["diff"] for body in used if body.get("diff")]
    reverted = _latest(events, "WORKSPACE_REVERTED")
    return {"write": workspace["write"], "folders": workspace["folders"], "files": list(files.values()),
            "refused": sum(len(body["refused"]) for body in used),
            "limit": any(body["limit"] is not None for body in used), "diff": diffs[-1] if diffs else None,
            "reverted": None if reverted is None else {
                "restored": [i["path"] for i in reverted["body"]["restored"]],
                "skipped": reverted["body"]["skipped"], "kept": reverted["body"]["kept"],
                "by": reverted["actor"]["id"], "ts": reverted["ts"]},
            "revertable": task_state(events) in CLOSED and bool(files) and reverted is None}
```

In `task_detail`, add `"workspace": workspace_view(events, visible)` to the `detail |= {...}` block.

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python -m pytest core/tests -q -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/views.py core/tests/test_views.py core/tests/test_api.py
git commit -m "feat(core): the task detail shows a task's workspace - files changed, the diff, revert state (plan 07c)"
```

---

### Task 2: The CLI confirms a `revert` answer

**Files:**
- Modify: `core/src/ooat_core/task_cli.py`
- Test: `core/tests/test_task_cli.py`

**Interfaces:**
- Consumes: the limit question of 07b (an option `revert` next to `raise_limit`).
- Produces: `ooat hil answer <evt> --choice revert` asks the same question as `ooat task revert`. Anything but
  `y` / `yes` (or an ended input) records nothing and exits with `REFUSED` and "Nothing was answered.".

- [ ] **Step 1: Write the failing test** (append to `core/tests/test_task_cli.py`)

```python
def test_answering_revert_asks_first(tmp_path):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_bytes(b"def main():\n    return 1\n")
    (tmp_path / "ooat.toml").write_text(
        f'[ledger]\nurl = "sqlite:///ledger.sqlite"\n\n[projects.bots]\nfolders = ["{root.as_posix()}"]\n'
        'write = true\nmax_operations = 2\n', encoding="utf-8")
    edit = ("edit_file", {"path": "Bots/src/bot.py", "old": "1", "new": "2"})
    read = ("read_file", {"path": "Bots/src/bot.py"})
    model, jev = WorkspaceModel([[read, edit, read]]), decisions()
    ledger = Ledger.open(f"sqlite:///{(tmp_path / 'ledger.sqlite').as_posix()}")
    for connector in (model, jev):
        acknowledge(ledger, connector)
    ledger.close()
    env = {"config": tmp_path / "ooat.toml", "registry": Registry([model, jev])}
    code, out = ooat(env, "task", "submit", "--operator", "Martin", "--goal", "Oprav bot.", "--project", "bots",
                     "--acceptance", "main vrací 2")
    request = out.split("Question ", 1)[1].split(" ", 1)[0]
    code, out = ooat(env, "hil", "answer", request, "--operator", "Martin", "--choice", "revert", answers="n\n")
    assert code == 1 and "Nothing was answered." in out
    assert (root / "src" / "bot.py").read_text(encoding="utf-8").endswith("return 2\n")
    code, out = ooat(env, "hil", "answer", request, "--operator", "Martin", "--choice", "revert", answers="y\n")
    assert code == 0 and (root / "src" / "bot.py").read_text(encoding="utf-8").endswith("return 1\n")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest core/tests/test_task_cli.py -q -k answering_revert`
Expected: FAIL: the first answer reverts at once (exit 0, the file back to `return 1`).

- [ ] **Step 3: Implement** (`core/src/ooat_core/task_cli.py`, in `_hil_answer` before `hil.answer(...)`)

```python
    if args.choice == "revert":  # writing the originals back takes a second confirmation (design 07 §12)
        question = ("Revert the project files this task changed? A file changed since is skipped; created files "
                    "stay. [y/N] ")
        if (ask(question, stdin, stdout) or "").strip().lower() not in ("y", "yes"):
            stdout.write("Nothing was answered.\n")
            return REFUSED
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/Scripts/python -m pytest core/tests/test_task_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/task_cli.py core/tests/test_task_cli.py
git commit -m "feat(core): ooat hil answer asks before a revert answer writes files (plan 07c)"
```

---

### Task 3: The web app's task page

**Files:**
- Create: `core/src/ooat_core/web/app/workspace.js`, `core/web-tests/workspace.test.mjs`
- Modify: `core/src/ooat_core/web/app/timeline.js`, `core/src/ooat_core/web/app/views/task.js`, `core/src/ooat_core/web/app/cards.js`, `core/src/ooat_core/web/app/i18n/en.js`, `core/src/ooat_core/web/app/i18n/cs.js`
- Test: `core/web-tests/timeline.test.mjs`, `core/web-tests/workspace.test.mjs`

**Interfaces:**
- Consumes: `detail.workspace` (Task 1); `POST /tasks/{id}/revert` → `{task, restored, skipped, kept}`.
- Produces:
  - `workspace.js`: `fileLine(file) -> string`, `revertReport(result) -> string[]` (one line for the counts, then one
    per skipped file with its reason) and `documents(artifacts) -> artifacts` (only `markdown_document`).
  - `describe()` handles `WORKSPACE_USED` and `WORKSPACE_REVERTED`.

- [ ] **Step 1: Write the failing tests**

`core/web-tests/workspace.test.mjs`:

```js
import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";
import { documents, fileLine, revertReport } from "../src/ooat_core/web/app/workspace.js";

test("a file's line says what OOAT saw happen to it", () => {
  setLanguage("en");
  assert.equal(fileLine({path: "Bots/src/bot.py", kind: "changed", added: 1, removed: 1}),
    "Bots/src/bot.py: changed, +1 −1");
  assert.equal(fileLine({path: "Bots/new.md", kind: "created", added: 2, removed: 0}), "Bots/new.md: created, +2");
});

test("a revert report names every skipped file and why", () => {
  setLanguage("en");
  assert.deepEqual(revertReport({restored: [{path: "Bots/a.py"}], kept: ["Bots/b.py"],
    skipped: [{path: "Bots/c.py", reason: "changed since the task"}]}),
  ["Restored 1, skipped 1, kept 1 created.", "Skipped Bots/c.py: changed since the task"]);
});

test("the document viewer gets documents only, never an original or a diff", () => {
  const found = documents([{type: "markdown_document", ref: "art_1"}, {type: "workspace_original", ref: "art_2"},
    {type: "workspace_diff", ref: "art_3"}, {type: "attachment", ref: "art_4"}]);
  assert.deepEqual(found.map((a) => a.ref), ["art_1"]);
});
```

Append to `core/web-tests/timeline.test.mjs`:

```js
test("a workspace call and a revert read as what happened to the files", () => {
  setLanguage("en");
  assert.deepEqual(describe(event("WORKSPACE_USED", {by: "worker", read: [{path: "a", times: 2}],
    changed: [{path: "a"}], created: [], refused: [{path: ".env"}], limit: null}, "ooat-runtime")),
  {tone: "info", text: "Files (worker): 1 changed, 0 created, 1 read, 1 refused"});
  assert.deepEqual(describe(event("WORKSPACE_USED", {by: "worker", read: [], changed: [], created: [],
    refused: [], limit: {kind: "operations"}}, "ooat-runtime")).tone, "ask");
  assert.deepEqual(describe(event("WORKSPACE_REVERTED", {restored: [{path: "a"}], skipped: [], kept: ["b"]})),
    {tone: "info", text: "Reverted by operator: 1 restored, 0 skipped, 1 created kept"});
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd core && npm test`
Expected: FAIL. `workspace.js` does not exist, and the workspace events read as their bare type.

- [ ] **Step 3: Implement**

`core/src/ooat_core/web/app/i18n/en.js`: add the keys below. `cs.js` gets the same keys, in Czech (the
translations are in brackets).

```js
  "task.files": "Files changed (recorded by OOAT)",          // Změněné soubory (zaznamenal OOAT)
  "task.fileChanged": "{path}: changed, +{added} −{removed}", // {path}: změněn, +{added} −{removed}
  "task.fileCreated": "{path}: created, +{added}",           // {path}: vytvořen, +{added}
  "task.refusedOps": "{n} operations refused by OOAT's path guard.", // {n} operací odmítla ochrana cest OOAT.
  "task.limitReached": "The task reached its workspace limit.", // Úloha narazila na limit práce se soubory.
  "task.readOnly": "The project's folders are read only for this task.", // Složky projektu jsou pro tuto úlohu jen pro čtení.
  "task.revert": "Revert the changes",                       // Vrátit změny
  "task.revertConfirm": "Revert the files this task changed? A file changed since is skipped; created files stay.",
      // Vrátit soubory, které tato úloha změnila? Soubor změněný mezitím se přeskočí; vytvořené soubory zůstanou.
  "task.revertReport": "Restored {restored}, skipped {skipped}, kept {kept} created.",
      // Vráceno {restored}, přeskočeno {skipped}, ponecháno {kept} vytvořených.
  "task.revertSkipped": "Skipped {path}: {reason}",          // Přeskočeno {path}: {reason}
  "task.revertedBy": "Reverted by {by}, {time}.",            // Vrátil(a) {by}, {time}.
  "hil.revertConfirm": "Revert the changes now? A file changed since is skipped; created files stay.",
      // Vrátit změny hned? Soubor změněný mezitím se přeskočí; vytvořené soubory zůstanou.
  "timeline.workspace": "Files ({by}): {changed} changed, {created} created, {read} read, {refused} refused",
      // Soubory ({by}): {changed} změněno, {created} vytvořeno, {read} přečteno, {refused} odmítnuto
  "timeline.reverted": "Reverted by {who}: {restored} restored, {skipped} skipped, {kept} created kept",
      // Vrátil(a) {who}: {restored} vráceno, {skipped} přeskočeno, {kept} vytvořených ponecháno
```

Write the Czech strings in `cs.js` as values, not comments.

`core/src/ooat_core/web/app/workspace.js`:

```js
// A task's work on its project's folders, as the task page shows it (design 07 §7): OOAT's own list of files, the
// report of a revert, and which artifacts are the documents (originals and diffs are not).
import { t } from "./i18n.js";

/** @param {{path: string, kind: string, added: number, removed: number}} file */
export function fileLine(file) {
  return file.kind === "created" ? t("task.fileCreated", {path: file.path, added: file.added})
    : t("task.fileChanged", {path: file.path, added: file.added, removed: file.removed});
}

/** @param {{restored: any[], skipped: {path: string, reason: string}[], kept: string[]}} result */
export function revertReport(result) {
  return [t("task.revertReport", {restored: result.restored.length, skipped: result.skipped.length,
    kept: result.kept.length}), ...result.skipped.map((s) => t("task.revertSkipped", {path: s.path, reason: s.reason}))];
}

/** @template {{type: string}} T @param {T[]} artifacts @returns {T[]} */
export function documents(artifacts) {
  return artifacts.filter((a) => a.type === "markdown_document");
}
```

`timeline.js`, two cases before `default`:

```js
    case "WORKSPACE_USED":
      return {tone: body.limit ? "ask" : "info", text: t("timeline.workspace", {by: body.by,
        changed: body.changed.length, created: body.created.length, read: body.read.length,
        refused: body.refused.length})};
    case "WORKSPACE_REVERTED":
      return {tone: "info", text: t("timeline.reverted", {who, restored: body.restored.length,
        skipped: body.skipped.length, kept: body.kept.length})};
```

`cards.js`: the revert option of a question asks first. In the option button's `onclick`:

```js
    onclick: () => {
      if (option.id === "revert" && !confirm(t("hil.revertConfirm"))) return;  // the second confirmation
      answer(option.id);
    },
```

`views/task.js`:
- `import { documents, fileLine, revertReport } from "../workspace.js";`
- In `drawResult`, use `const docs = documents(detail.artifacts);` in place of the
  `type !== "attachment"` filter, and pass `docs` to `viewer`. The attachments filter stays.
- After the viewer and attachments parts, append `...workspaceParts(ctx, detail, element)` when `detail.workspace`
  is set and is not a stub (`!detail.workspace.redacted`):

```js
/**
 * The files a task changed, its diff and revert (design 07 §7): drawn from OOAT's records, never the agent's words.
 * @param {import("../api.js").Context} ctx @param {any} detail @param {HTMLElement} element to redraw after a revert
 */
function workspaceParts(ctx, detail, element) {
  const ws = detail.workspace;
  /** @type {HTMLElement[]} */
  const parts = [h("h3", {}, t("task.files"))];
  if (!ws.write) parts.push(h("p", {class: "muted"}, t("task.readOnly")));
  if (ws.files.length) parts.push(h("ul", {}, ...ws.files.map((/** @type {any} */ f) => h("li", {}, fileLine(f)))));
  if (ws.refused) parts.push(h("p", {class: "muted"}, t("task.refusedOps", {n: ws.refused})));
  if (ws.limit) parts.push(h("p", {class: "warning"}, t("task.limitReached")));
  if (ws.diff) {
    const diff = h("div", {class: "viewer"});
    fetchText(ctx, `/artifacts/${encodeURIComponent(ws.diff)}`).then((body) => diff.replaceChildren(
      body === null ? h("p", {class: "muted"}, t("common.redacted")) : diffView(body)))
      .catch((error) => report(diff, error));
    parts.push(diff);
  }
  if (ws.reverted) {
    parts.push(h("p", {class: "muted"}, t("task.revertedBy", {by: ws.reverted.by, time: clock(ws.reverted.ts)})),
      ...revertReport({restored: ws.reverted.restored, skipped: ws.reverted.skipped, kept: ws.reverted.kept})
        .map((row) => h("p", {}, row)));
  }
  if (ws.revertable) {
    const status = h("span", {class: "status", role: "status"});
    parts.push(h("p", {}, h("button", {type: "button", class: "danger", onclick: async () => {
      if (!confirm(t("task.revertConfirm"))) return;  // the second confirmation (design 07 §12)
      try {
        const result = await ctx.api.json(`/tasks/${encodeURIComponent(detail.task)}/revert`,
          {method: "POST", body: {}});
        status.replaceChildren(...revertReport(result).map((row) => h("span", {}, row, h("br"))));
      } catch (error) {
        report(status, error);
      }
    }}, t("task.revert")), " ", status));
  }
  return parts;
}
```

`drawResult`'s cache key (`shown`) gains `detail.workspace`, so a revert that changed the record redraws the
section: `JSON.stringify([detail.result, detail.artifacts, detail.workspace])`. The `element` argument is kept for
a later redraw, and nothing needs it now; drop it if `tsc` flags it as unused, which needs no ruling.

- [ ] **Step 4: Run them to verify they pass**

Run: `cd core && npm run check && npm test`
Expected: PASS. `tsc` reports no errors (both locales have the same keys) and every web test passes.

- [ ] **Step 5: Commit**

```bash
git add core/src/ooat_core/web/app/workspace.js core/src/ooat_core/web/app/timeline.js \
        core/src/ooat_core/web/app/views/task.js core/src/ooat_core/web/app/cards.js \
        core/src/ooat_core/web/app/i18n/en.js core/src/ooat_core/web/app/i18n/cs.js \
        core/web-tests/workspace.test.mjs core/web-tests/timeline.test.mjs
git commit -m "feat(web): the task page shows the files a task changed, its diff, and revert with a confirm step (plan 07c)"
```

---

### Task 4: The chat bridge

**Files:**
- Modify: `sdk/python/src/ooat_client/bridge.py`, `sdk/python/src/ooat_client/texts.py`
- Test: `core/tests/test_bridge.py`

**Interfaces:**
- Consumes: `detail.workspace` (Task 1), `OoatClient.revert` (07b).
- Produces new button data, each at most 64 bytes:
  - `v:<task>` asks to revert a closed task; `V:<task>` is the confirmed revert;
  - `c:<request>` confirms a `revert` answer to a limit question; `a:<request>:revert` no longer answers, it asks.
- `_result` posts the diff as `<task>.diff` after the document when `workspace.diff` is readable. While
  `revertable`, it adds a third button row, `[Revert the changes]`.
- A limit question (its options include `raise_limit`) is preceded by the task's latest document and its diff.
- `on_message` sends the text-only notice once per bridge when the task's detail has no `workspace`.

- [ ] **Step 1: Write the failing tests** (append to `core/tests/test_bridge.py`)

```python
from runtime_fakes import WorkspaceModel

from ooat_core.config import parse_config

ORIGINAL = b"def main():\n    return 1\n"
EDIT = [("read_file", {"path": "Bots/src/bot.py"}),
        ("edit_file", {"path": "Bots/src/bot.py", "old": "return 1", "new": "return 2"})]


def project(tmp_path, tools, **settings):
    root = tmp_path / "Bots"
    (root / "src").mkdir(parents=True)
    (root / "src" / "bot.py").write_bytes(ORIGINAL)
    config = parse_config({"projects": {"bots": {"folders": [str(root)], "write": True, **settings}}})
    return root, Served(tmp_path, model=WorkspaceModel(tools), config=config, runner=True)


def test_a_result_brings_the_diff_and_a_revert_that_needs_a_second_tap(tmp_path):
    root, served = project(tmp_path, [EDIT])
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(f"Oprav bot.\nDone when:\n{CRITERIA[0]}", "1")
        assert finished(watching(bridge, task))
        (diff,) = [m for m in chat.sent if m.get("file") == f"{task}.diff"]
        assert b"+    return 2" in diff["content"]
        footer = chat.find("v:")
        ask = bridge.on_button(button(footer, "Revert").data)
        assert ask == "Confirm below." and root.joinpath("src", "bot.py").read_bytes() != ORIGINAL  # one tap: nothing
        confirm = chat.find("V:")
        assert bridge.on_button(button(confirm, "Yes, revert").data).startswith("Restored 1, skipped 0")
        assert root.joinpath("src", "bot.py").read_bytes() == ORIGINAL


def test_the_limit_question_comes_with_the_document_and_its_revert_asks_again(tmp_path):
    root, served = project(tmp_path, [EDIT + [("read_file", {"path": "Bots/src/bot.py"})]], max_operations=2)
    chat = FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        task = bridge.on_message(f"Oprav bot.\nDone when:\n{CRITERIA[0]}", "1")
        watcher = watching(bridge, task)
        question = wait_for(lambda: chat.find("a:"))
        texts = [m["text"] for m in chat.sent]
        assert any("Files changed (recorded by OOAT)" in t for t in texts)  # the limited document came first
        assert [m for m in chat.sent if m.get("file") == f"{task}.diff"]
        assert len(question["buttons"]) == 4
        assert bridge.on_button(button(question, "Revert").data) == "Confirm below."
        assert root.joinpath("src", "bot.py").read_bytes() != ORIGINAL
        assert bridge.on_button(button(chat.find("c:"), "Yes, revert").data) == "Answer recorded."
        assert finished(watcher)
        assert root.joinpath("src", "bot.py").read_bytes() == ORIGINAL


def test_a_project_without_folders_is_told_once(tmp_path):
    served, chat = Served(tmp_path, runner=True), FakeChat()
    with listening(served) as url:
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "docs")
        bridge.on_message(f"{GOAL}\nDone when:\n{CRITERIA[0]}", "1")
        bridge.on_message(f"{GOAL}\nDone when:\n{CRITERIA[0]}", "2")
    notices = [m for m in chat.sent if "no folders in OOAT" in m["text"]]
    assert len(notices) == 1


def test_a_workspace_above_the_tokens_class_posts_no_diff(tmp_path):
    root, served = project(tmp_path, [EDIT], data_class="client_confidential")
    chat = FakeChat()
    with listening(served) as url:  # the web session submits it; the chat only watches
        session = served.login()
        task = served.submit(session, project="bots", acceptance=CRITERIA)["task"]
        bridge = Bridge(OoatClient(url, secret(served.token())), chat, "bots")
        assert finished(watching(bridge, task))
    assert not [m for m in chat.sent if m.get("file", "").endswith(".diff")] and not chat.find("v:")
```

`served.submit` with a web session works because the web session has no cap. If the fake model is not
acknowledged for `client_confidential`, pass `classes=("public", "internal", "client_confidential")` to `Served`
in this test's `project(...)` call (add a `classes` parameter to `project`); that needs no ruling.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python -m pytest core/tests/test_bridge.py -q`
Expected: FAIL. No `.diff` file is posted, there is no `v:` button, the limit question's `revert` answers on the
first tap, and the notice is missing.

- [ ] **Step 3: Implement**

`texts.py`, new keys in both languages (Czech in brackets):

```
"revert": "Revert the changes"                                         [Vrátit změny]
"revert_confirm": "Revert the files this task changed? A file changed since is skipped; created files stay."
                  [Vrátit soubory, které tato úloha změnila? Soubor změněný mezitím se přeskočí; vytvořené soubory zůstanou.]
"revert_yes": "Yes, revert"                                            [Ano, vrátit]
"confirm_below": "Confirm below."                                      [Potvrďte níže.]
"reverted": "Restored {restored}, skipped {skipped}, kept {kept} created." [Vráceno {restored}, přeskočeno {skipped}, ponecháno {kept} vytvořených.]
"skipped": "Skipped {path}: {reason}"                                  [Přeskočeno {path}: {reason}]
"diff": "The changes in the project's files."                          [Změny v souborech projektu.]
"no_folders": "Project {project} has no folders in OOAT: its tasks work with text only." [Projekt {project} nemá v OOAT složky: jeho úlohy pracují jen s textem.]
```

`bridge.py`:
- `__init__`: `self._told_text_only = False`.
- `on_message`, after `submit` returns `task`:

```python
        if not self._told_text_only:
            try:
                plain = self.client.task(task).get("workspace") is None
            except OoatError:
                plain = False  # say nothing rather than something wrong
            if plain:
                self._told_text_only = True
                self._send(self._t("no_folders", project=self.project))
        return task
```

- `on_button`: before the `kind == "a"` branch:

```python
            if kind == "a" and rest.endswith(":revert"):  # the limit question's revert: a second tap (design 07 §12)
                request = rest.rsplit(":", 1)[0]
                self._send(self._t("revert_confirm"), [[Button(self._t("revert_yes"), f"c:{request}")]])
                return self._t("confirm_below")
            if kind == "c":
                self.client.answer(rest, choice="revert")
                return self._t("recorded")
            if kind == "v":
                self._send(self._t("revert_confirm"), [[Button(self._t("revert_yes"), f"V:{rest}")]])
                return self._t("confirm_below")
            if kind == "V":
                result = self.client.revert(rest)
                return "\n".join([self._t("reverted", restored=len(result["restored"]), skipped=len(result["skipped"]),
                                          kept=len(result["kept"]))]
                                 + [self._t("skipped", path=s["path"], reason=s["reason"]) for s in result["skipped"]])
```

- `_question`: before posting, when the request offers `raise_limit`, post the latest document and the diff:

```python
        if any(o["id"] == "raise_limit" for o in request["options"]):
            self._limited_work(request["task"])
```

```python
    def _limited_work(self, task: str) -> None:
        """What the agent did before its limit, as OOAT recorded it: the question itself quotes none of it."""
        detail = self.client.task(task)
        docs = [a for a in detail["artifacts"] if a["type"] == "markdown_document"]
        if docs:
            document = self.client.artifact(docs[-1]["ref"])
            self._document(task, document.content) if document.content is not None else self._send(self._t("redacted"))
        self._diff(task, detail)

    def _diff(self, task: str, detail: dict) -> None:
        workspace = detail.get("workspace")
        if not isinstance(workspace, dict) or "redacted" in workspace or not workspace.get("diff"):
            return
        diff = self.client.artifact(workspace["diff"])
        if diff.content is not None:
            self._send_file(f"{task}.diff", diff.content, self._t("diff"))
```

- `_result`: after the document is posted, call `self._diff(task, detail)`. Then the footer's buttons gain a third
  row when the workspace can be reverted:

```python
        rows = [[Button(self._t("accepted", value=v), f"r:{task}:{v}:y") for v in VALUES],
                [Button(self._t("rejected", value=v), f"r:{task}:{v}:n") for v in VALUES]]
        workspace = detail.get("workspace")
        if isinstance(workspace, dict) and workspace.get("revertable"):
            rows.append([Button(self._t("revert"), f"v:{task}")])
        self._send(footer, rows)
```

`OoatError` from `client.answer` or `client.revert` in these branches is caught by `on_button`'s existing
`except OoatError` and returned as the server's message. The skipped files reach the person through the `V:`
reply above.

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/Scripts/python -m pytest core/tests/test_bridge.py core/tests/test_client.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sdk/python/src/ooat_client/bridge.py sdk/python/src/ooat_client/texts.py core/tests/test_bridge.py
git commit -m "feat(sdk): the chat bridge posts a task's diff, reverts with a second tap, shows the limit question's work (plan 07c)"
```

---

### Task 5: Docs

**Files:**
- Modify: `docs/chat-bridge.md`, `docs/description.md`, `core/description.md`, `sdk/python/README.md`

- [ ] **Step 1: Write the text**

`docs/chat-bridge.md`:
- In the contract table, a new row after "Result":

  | Project files | posted by `watch` | the diff as `<task>.diff` after the document; a "Revert the changes" row in the footer while a revert is possible; a tap asks "Yes, revert", and only that second tap calls `POST /tasks/{id}/revert`. The skipped files are listed with their reason |

- A note under the "A question" row: a limit question is preceded by the task's latest document and its diff, and
  its `revert` button asks for a second tap.
- Button data gains `v:<task>`, `V:<task>` and `c:<request>`.
- In "What changes for a bot that ran a coding CLI", replace "It has no tools (no file edits, no commands)" with:
  for a project mapped in `ooat.toml`, a task reads and edits the project's files through OOAT's own tools
  (ADR 0017); commands still run nowhere. A project without folders gets the text-only notice once.

`docs/description.md`: the web app paragraph gains:
- the task page's "Files changed" section, with the diff and revert behind a confirm step;
- the question card's confirm step for `revert`;
- the timeline lines for the workspace.

`core/description.md`:
- `views.py`: `workspace_view()`;
- `task_cli.py`: `hil answer --choice revert` asks.

`sdk/python/README.md`: the bridge shows a task's diff and offers revert with a second tap.

- [ ] **Step 2: Check**

Run: `.venv/Scripts/python -m pytest -q` and `cd core && npm run check && npm test`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add docs/chat-bridge.md docs/description.md core/description.md sdk/python/README.md
git commit -m "docs: the workspace in the web app and the chat bridge (plan 07c)"
```

---

## Coverage of the design

| Design | Where |
|---|---|
| §7 Result: the changed files with counts, the diff as an artifact; Telegram: summary, diff file, Revert button; Web: the same in the task view | Tasks 1, 3, 4 |
| §7 a rating that rejects the result offers revert in the same screen or message | Task 3 (the task page's section next to the rating card), Task 4 (the footer's row) |
| §8 the question reaches the web and the chat bridge with one-tap buttons | existing HIL flow; Task 4 adds the document and the diff before it |
| §12 revert asks for a second confirmation (web confirm, chat second tap) | Tasks 2, 3, 4 |
| §3 the chat bridge says once that a project has no `[projects]` entry | Task 4 |

**Not in this plan:**
- The Telegram bot in its own repository (`telegram-claude-bot`, PR #1). It uses `ooat_client.Bridge` and
  updates its plan after this one. It needs a token, a chat → project mapping, and the bridge's new buttons.
- The 07b minors deferred to later, and the PR #46 review's points 2–4: a revert interrupted before its close; the
  originals' class taken from the task, not the project's current `data_class`; cut or hidden paths as revert keys.
