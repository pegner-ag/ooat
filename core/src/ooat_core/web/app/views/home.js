// Home (design 08 §9, plan 08b): one box like a search field with the project next to it, the conversation with the
// reception below it, the project's earlier conversations, then the inbox's lists and the folded exact-task form.
import { openOf } from "../conversation.js";
import { h, report } from "../dom.js";
import { ago } from "../format.js";
import { t } from "../i18n.js";
import { follow, thread } from "./conversation.js";
import { MAX_ATTACHMENT_BYTES, base64, taskForm, taskLists } from "./inbox.js";

export const PROJECT_STORAGE = "ooat.project";
const EARLIER = 5;

/** The project last chosen, if the browser keeps it. */
export function storedProject() {
  try {
    return localStorage.getItem(PROJECT_STORAGE);
  } catch {
    return null;
  }
}

/** @param {string} project */
function storeProject(project) {
  try {
    localStorage.setItem(PROJECT_STORAGE, project);
  } catch {
    // a private window: the picker falls back to the first project next time
  }
}

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function home(root, ctx) {
  const {projects} = await ctx.api.json("/projects", {signal: ctx.signal});
  const names = projects.map((/** @type {any} */ p) => p.project);
  const picker = h("select", {"aria-label": t("home.project")}, ...names.map((/** @type {string} */ name) =>
    h("option", {value: name}, name)));
  const stored = storedProject();
  picker.value = stored && names.includes(stored) ? stored : names[0] ?? "";
  const text = h("textarea", {rows: "2", required: true, maxlength: "20000", placeholder: t("home.placeholder"),
    "aria-label": t("home.placeholder")});
  const files = h("input", {type: "file", multiple: true, "aria-label": t("home.attach")});
  const send = h("button", {type: "submit", class: "recommended"}, t("home.send"));
  const status = h("p", {class: "status", role: "status"});
  const talk = h("section");
  const earlier = h("section");
  const form = taskForm(ctx);
  const box = h("form", {class: "card box", onsubmit: submit}, text,
    h("div", {class: "row"}, picker, files, send), status);
  root.replaceChildren(h("h1", {}, t("inbox.title")), box, talk, earlier, form.element);
  if (!names.length) {
    for (const control of [text, picker, files, send]) control.disabled = true;
    status.textContent = t("home.noProjects");
  }

  /** The conversation shown: its id (null until the next message starts one), its turns, its stream. */
  let current = {project: picker.value, conversation: /** @type {string | null} */ (null),
    turns: thread(ctx, {live: true}), stop: new AbortController()};
  ctx.signal.addEventListener("abort", () => current.stop.abort());  // leaving the screen ends the stream shown
  let key = crypto.randomUUID();  // one Idempotency-Key per typed message: a double Enter or a retry is one message

  /** @param {string} project */
  async function open(project) {
    current.stop.abort();  // the old project's replies never show under the new one
    const stop = new AbortController();
    const turns = thread(ctx, {live: true, onTurn: (turn) => {
      talk.querySelector(".empty")?.remove();
      if (turn.who !== "you") status.textContent = "";
    }});
    current = {project, conversation: null, turns, stop};
    if (project) storeProject(project);  // the header's Memory opens the project shown here
    talk.replaceChildren(turns.element);
    earlier.replaceChildren();
    if (!project) return;
    const query = `/conversations?project=${encodeURIComponent(project)}&limit=20`;
    const {conversations} = await ctx.api.json(query, {signal: stop.signal});
    if (current.stop !== stop) return;
    const id = openOf(conversations, project);
    const before = conversations.filter((/** @type {any} */ c) => c.conversation !== id).slice(0, EARLIER);
    if (before.length) {
      const now = new Date();
      earlier.append(h("h2", {}, t("home.earlier")), h("ul", {}, ...before.map((/** @type {any} */ c) => h("li", {},
        h("a", {href: `/conversations/${c.conversation}`, "data-route": ""},
          t("conv.started", {channel: c.channel, time: ago(c.last_message, now)}))))));
    }
    if (id === null) {
      talk.append(h("p", {class: "muted empty"}, t("home.empty")));
      return;
    }
    const first = await ctx.api.json(`/conversations/${encodeURIComponent(id)}/events`, {signal: stop.signal});
    if (current.stop !== stop) return;
    current.conversation = id;
    turns.add(first.events);
    listen(id, first.next);
  }

  /** @param {string} id @param {string | null} after */
  function listen(id, after) {
    const mine = current;
    follow(ctx, id, after, mine.turns, mine.stop.signal, status, () => {
      if (current === mine) current.conversation = null;  // closed: the next message starts a new conversation
    });
  }

  /** @param {Event} event */
  async function submit(event) {
    event.preventDefault();
    const said = text.value.trim();
    if (!said || send.disabled) return;
    const chosen = [...(files.files ?? [])];
    if (chosen.reduce((sum, file) => sum + file.size, 0) > MAX_ATTACHMENT_BYTES) {
      status.textContent = t("new.tooLarge");
      return;
    }
    send.disabled = true;
    status.textContent = "";
    const mine = current;
    try {
      const body = {project: mine.project, text: said,
        ...(mine.conversation ? {conversation: mine.conversation} : {}),
        attachments: await Promise.all(chosen.map(async (file) =>
          ({name: file.name, content_base64: await base64(file)})))};
      const sent = await ctx.api.json("/conversations/messages", {method: "POST", body,
        headers: {"Idempotency-Key": key}});
      key = crypto.randomUUID();
      text.value = "";
      files.value = "";
      if (current !== mine) return;
      // Shown at once; its id is then known, so the stream's copy of it is not shown again.
      mine.turns.add([{id: sent.message, ts: new Date().toISOString(), type: "CONVERSATION_MESSAGE",
        body: {conversation: sent.conversation, project: mine.project, text: said}}]);
      status.textContent = t("home.received");
      if (mine.conversation !== sent.conversation) {
        mine.conversation = sent.conversation;
        listen(sent.conversation, sent.message);
      }
    } catch (error) {
      report(status, error);
    } finally {
      send.disabled = false;
    }
  }

  text.addEventListener("keydown", (event) => {  // Enter sends, Shift+Enter is a new line
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      box.requestSubmit();
    }
  });
  picker.addEventListener("change", () => {
    open(picker.value).catch((error) => report(talk, error));
  });

  await open(picker.value);
  root.append(await taskLists(ctx, form));
}
