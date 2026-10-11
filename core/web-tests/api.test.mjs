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

test("follow survives a dropped connection and goes on after the last event it saw", async () => {
  /** @type {(string | null)[]} */
  const cursors = [];
  /** @type {number[]} */
  const waits = [];
  let reads = 0;
  const broken = new Response(new ReadableStream({
    pull(controller) {
      reads += 1;
      if (reads === 1) controller.enqueue(new TextEncoder().encode(sse("evt_1", "RESULT")));
      else controller.error(new TypeError("network error"));
    },
  }));
  /** @type {(() => Response)[]} */
  const replies = [() => broken, () => { throw new TypeError("Failed to fetch"); },
    () => stream([sse("evt_2", "TASK_CLOSED")])];
  const api = createApi({storage, onSignedOut: () => assert.fail("signed out"),
    sleep: async (ms) => { waits.push(ms); },
    fetch: async (_url, init) => {
      cursors.push(/** @type {Record<string, string>} */ (init?.headers)["Last-Event-ID"] ?? null);
      return /** @type {() => Response} */ (replies.shift())();
    }});
  /** @type {string[]} */
  const seen = [];
  await api.follow("tsk_1", null, (event) => seen.push(event.id), new AbortController().signal);
  assert.deepEqual(seen, ["evt_1", "evt_2"]);
  assert.deepEqual(cursors, [null, "evt_1", "evt_1"]);
  assert.deepEqual(waits, [1000, 2000]);
});

test("follow waits out a busy ledger", async () => {
  /** @type {number[]} */
  const waits = [];
  /** @type {(() => Response)[]} */
  const replies = [() => reply({error: {code: "LEDGER_BUSY", message: "busy"}}, 503),
    () => stream([sse("evt_1", "TASK_CLOSED")])];
  const api = createApi({storage, onSignedOut: () => assert.fail("signed out"),
    sleep: async (ms) => { waits.push(ms); }, fetch: async () => /** @type {() => Response} */ (replies.shift())()});
  /** @type {string[]} */
  const seen = [];
  await api.follow("tsk_1", null, (event) => seen.push(event.id), new AbortController().signal);
  assert.deepEqual(seen, ["evt_1"]);
  assert.deepEqual(waits, [1000]);
});

test("follow stops on the server's refusal instead of trying again", async () => {
  const api = createApi({storage, onSignedOut: () => {}, sleep: async () => assert.fail("no retry"),
    fetch: async () => reply({error: {code: "NOT_FOUND", message: "no such task"}}, 404)});
  await assert.rejects(api.follow("tsk_1", null, () => {}, new AbortController().signal),
    (/** @type {ApiError} */ error) => error.code === "NOT_FOUND");
});
