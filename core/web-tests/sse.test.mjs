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
