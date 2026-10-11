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
