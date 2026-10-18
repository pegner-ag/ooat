import assert from "node:assert/strict";
import { test } from "node:test";
import { openOf, shown, tapLabel } from "../src/ooat_core/web/app/conversation.js";

/** @param {string} id @param {string} type @param {Record<string, unknown>} body */
const ev = (id, type, body) => ({id, ts: "2026-10-18T10:00:00Z", type, actor: {kind: "system", id: "x"}, refs: [],
  cost: null, body: {conversation: "cnv_1", project: "docs", data_class: "internal", ...body}});
const STUB = {redacted: "Above this session's data class", link: "/conversations/cnv_1"};

test("a message, its decision and a report are three turns; a replaced decision is left out", () => {
  const turns = shown([ev("e1", "CONVERSATION_MESSAGE", {text: "Změň titulek"}),
    ev("e2", "RECEPTION_DECIDED", {decision: "escalated", reply: "x", options: [], buttons: []}),
    ev("e3", "RECEPTION_DECIDED", {decision: "confirm", reply: "Mám začít?", options: ["A", "B"],
      buttons: ["yes", "differently"]}),
    ev("e4", "CONVERSATION_REPORTED", {task: "tsk_1", reply: "Hotovo.", options: ["Push"]}),
    ev("e5", "CONVERSATION_CLOSED", {reason: "operator"})]);
  assert.deepEqual(turns.map((turn) => [turn.who, turn.text]),
    [["you", "Změň titulek"], ["reception", "Mám začít?"], ["report", "Hotovo."], ["closed", "operator"]]);
  assert.deepEqual([turns[1].options, turns[1].buttons], [["A", "B"], ["yes", "differently"]]);
  assert.equal(turns[2].task, "tsk_1");
});

test("the same event twice (a tap's response, then the stream) is one turn", () => {
  const decided = ev("e3", "RECEPTION_DECIDED", {decision: "task", reply: "Spouštím.", task: "tsk_1", options: [],
    buttons: []});
  const seen = new Set();
  assert.equal(shown([decided], seen).length, 1);
  assert.equal(shown([decided], seen).length, 0);
});

test("a stubbed reply is redacted, without buttons or options", () => {
  const [turn] = shown([ev("e3", "RECEPTION_DECIDED", {decision: "ask", reply: STUB, options: STUB,
    buttons: ["yes"]})]);
  assert.deepEqual([turn.redacted, turn.text, turn.options, turn.buttons], [true, null, [], []]);
});

test("a tap is shown by its kind, with its correction; a stubbed message is redacted", () => {
  const turns = shown([ev("e1", "CONVERSATION_MESSAGE", {tap: "differently", tap_text: "Jen titulek"}),
    ev("e2", "CONVERSATION_MESSAGE", {tap: "forget:mem_01"}), ev("e3", "CONVERSATION_MESSAGE", {text: STUB})]);
  assert.deepEqual(turns.map((turn) => [turn.tap, turn.text, turn.redacted]),
    [["differently", "Jen titulek", false], ["forget", null, false], [null, null, true]]);
  assert.equal(tapLabel("forget:mem_01"), "conv.forget");
  assert.equal(tapLabel("whatever"), null);
  assert.equal(tapLabel("remember"), "conv.remember");
});

test("the open web conversation of the project, never a chat bridge's or a closed one", () => {
  const list = [{conversation: "cnv_3", project: "docs", channel: "token:t1", closed: null},
    {conversation: "cnv_2", project: "docs", channel: "web", closed: "2026-10-16T10:00:00Z"},
    {conversation: "cnv_1", project: "docs", channel: "web", closed: null}];
  assert.equal(openOf(list, "docs"), "cnv_1");
  assert.equal(openOf(list, "eshop"), null);
});
