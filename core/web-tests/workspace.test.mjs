import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";
import { documents, fileLine, hasWork, revertReport } from "../src/ooat_core/web/app/workspace.js";

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

test("a task with nothing to show about its files gets no section", () => {
  assert.equal(hasWork({files: [], refused: 0, limit: false, reverted: null}), false);
  assert.equal(hasWork({files: [], refused: 1, limit: false, reverted: null}), true);
  assert.equal(hasWork({files: [{path: "a"}], refused: 0, limit: false, reverted: null}), true);
});
