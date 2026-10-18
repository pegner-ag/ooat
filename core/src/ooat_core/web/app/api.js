// The page's one door to `ooat serve` (design 05 §5, §6). A web session has two halves: the HttpOnly cookie and the
// session key, kept in this origin's storage and sent as X-CSRF-Token on every request. A cookie is not bound to a
// port, so another service on 127.0.0.1 may receive it; the storage is bound to the origin, port included.
import { parseSse } from "./sse.js";

export const KEY_STORAGE = "ooat.session";
const RECONNECT_MS = 1000;
const MAX_RECONNECT_MS = 30_000;

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
   * Follows a task's timeline until its TASK_CLOSED, or until `signal` aborts.
   * @param {string} task
   * @param {string | null} after the last event already shown
   * @param {(event: any) => void} onEvent
   * @param {AbortSignal} signal
   */
  function follow(task, after, onEvent, signal) {
    return stream(`/tasks/${encodeURIComponent(task)}/events`, "TASK_CLOSED", after, onEvent, signal);
  }

  /**
   * Follows a conversation with the reception until its CONVERSATION_CLOSED, or until `signal` aborts.
   * @param {string} conversation
   * @param {string | null} after the last event already shown
   * @param {(event: any) => void} onEvent
   * @param {AbortSignal} signal
   */
  function followConversation(conversation, after, onEvent, signal) {
    return stream(`/conversations/${encodeURIComponent(conversation)}/events`, "CONVERSATION_CLOSED", after, onEvent,
      signal);
  }

  /**
   * The events of a stream until the event `end`. The server ends a stream after 15 minutes, and a network can drop
   * one; the next starts after the last event seen, so nothing is shown twice or missed. A dropped connection is
   * tried again after 1 s, then twice as long per further drop, at most 30 s.
   * @param {string} path below /api/v1
   * @param {string} end the event type that ends it
   * @param {string | null} after
   * @param {(event: any) => void} onEvent
   * @param {AbortSignal} signal
   */
  async function stream(path, end, after, onEvent, signal) {
    let cursor = after;
    let wait = RECONNECT_MS;
    while (!signal.aborted) {
      try {
        const response = await env.fetch(`/api/v1${path}`, {
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
            wait = RECONNECT_MS;
            onEvent(event);
            if (event.type === end) return;
          }
        }
      } catch (error) {
        // The server's refusal and leaving the screen end the timeline; a network drop or a busy server does not.
        if ((error instanceof ApiError && error.status < 500) || signal.aborted) throw error;
        await sleep(wait);
        wait = Math.min(wait * 2, MAX_RECONNECT_MS);
        continue;
      }
      await sleep(RECONNECT_MS);  // the server ended the stream (after 15 minutes): go on
    }
  }

  return {json, raw, follow, followConversation};
}

/** @typedef {ReturnType<typeof createApi>} Api */

/**
 * What every screen gets: the API, in-app navigation, and a signal that aborts when the screen is left.
 * @typedef {object} Context
 * @property {Api} api
 * @property {(path: string) => void} navigate
 * @property {AbortSignal} signal
 */
