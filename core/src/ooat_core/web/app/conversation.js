// What a conversation with the reception shows (design 08 §4, §9): one turn per event, in order. A decision that a
// later call replaced (escalated, retried) is not shown, and an event seen twice (a tap's response and the stream)
// is one turn. Text above the session's data class arrives as the server's stub and is shown as redacted.

export const REPLACED = ["escalated", "retried"];

/**
 * @typedef {object} Turn
 * @property {string} id
 * @property {string} ts
 * @property {"you" | "reception" | "report" | "closed"} who
 * @property {string | null} text what was said, or the tap's label key with its text (`tap`)
 * @property {string | null} tap a tap's kind (yes, differently, …), for its label
 * @property {boolean} redacted
 * @property {string[]} options numbered next steps
 * @property {string[]} buttons the reception's taps: yes, differently, new_thing, make_task, todo, forget:<mem>, …
 * @property {string | null} task a task the decision started, or the report's task
 * @property {string} project
 * @property {string} conversation
 */

/** @param {unknown} value */
const said = (value) => (typeof value === "string" ? value : null);

/**
 * @param {any[]} events events of GET /conversations/{id}/events, oldest first
 * @param {Set<string>} [seen] ids already shown; kept up to date, so a later call skips them
 * @returns {Turn[]}
 */
export function shown(events, seen = new Set()) {
  /** @type {Turn[]} */
  const turns = [];
  for (const event of events) {
    if (seen.has(event.id)) continue;
    seen.add(event.id);
    const body = event.body ?? {};
    const base = {id: event.id, ts: event.ts, project: body.project ?? "", conversation: body.conversation ?? "",
      tap: null, redacted: false, options: [], buttons: [], task: null};
    if (event.type === "CONVERSATION_MESSAGE") {
      const tap = said(body.tap);
      const text = tap ? said(body.tap_text) : said(body.text);
      const redacted = (body.tap_text !== undefined || !tap) && text === null;
      turns.push({...base, who: "you", tap: tap ? tapKind(tap) : null, text, redacted});
    } else if (event.type === "RECEPTION_DECIDED" || event.type === "CONVERSATION_REPORTED") {
      if (REPLACED.includes(body.decision)) continue;
      const text = said(body.reply);
      const visible = text !== null;
      turns.push({...base, who: event.type === "RECEPTION_DECIDED" ? "reception" : "report", text,
        redacted: !visible, options: visible && Array.isArray(body.options) ? body.options.filter(said) : [],
        buttons: visible && Array.isArray(body.buttons) ? body.buttons.filter(said) : [], task: body.task ?? null});
    } else if (event.type === "CONVERSATION_CLOSED") {
      turns.push({...base, who: "closed", text: said(body.reason)});
    }
  }
  return turns;
}

/** The kind of a tap, without its memory id: "forget:mem_…" is "forget". @param {string} tap */
export function tapKind(tap) {
  return tap.split(":", 1)[0];
}

/** @type {Record<string, import("./i18n.js").Key>} */
const LABELS = {yes: "conv.yes", differently: "conv.differently", new_thing: "conv.newThing",
  make_task: "conv.makeTask", todo: "conv.todo", forget: "conv.forget", done: "conv.done"};

/**
 * The i18n key of a button or of a tap message's label; null for a tap this page does not know.
 * @param {string} tap
 * @returns {import("./i18n.js").Key | null}
 */
export function tapLabel(tap) {
  return LABELS[tapKind(tap)] ?? null;
}

/**
 * The conversation the home page continues: the newest open one of this project on the web. A conversation of a
 * chat bridge is its own channel's, never continued here.
 * @param {any[]} list conversations of GET /conversations, newest first
 * @param {string} project
 * @returns {string | null}
 */
export function openOf(list, project) {
  return list.find((c) => c.project === project && c.channel === "web" && !c.closed)?.conversation ?? null;
}
