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

  const viewing = {mode: "markdown", shown: ""};
  let stale = false;

  /** @param {boolean} [force] after the operator's own action: redraw the cards even with the focus inside */
  async function draw(force = false) {
    const detail = await ctx.api.json(path, {signal: ctx.signal});
    head.replaceChildren(h("h1", {}, title(detail.goal)), h("p", {class: "muted"}, [detail.state,
      detail.topology ?? "—", t("task.cost", {cost: money(detail.cost_usd), budget: money(detail.budget_usd),
        estimate: money(detail.estimate_usd)})].join(" · ")));
    // A half-typed answer or rating is never wiped: while the focus is in the cards, they wait for it to leave.
    stale = !force && actions.contains(document.activeElement);
    if (!stale) await drawActions(actions, ctx, detail, again);
    drawResult(result, ctx, detail, viewing);
  }

  /** @type {string | null} */
  let cursor = null;
  let following = false;

  /** After the operator's own action: redraw, and once the stream has ended show what the action recorded. */
  function again() {
    draw(true).then(async () => {
      if (following) return;
      const more = await ctx.api.json(`${path}/events${cursor ? `?after=${encodeURIComponent(cursor)}` : ""}`,
        {signal: ctx.signal});
      timeline.append(...more.events.map(line));
      cursor = more.next;
    }).catch((error) => report(actions, error));
  }

  actions.addEventListener("focusout", (event) => {
    if (stale && !actions.contains(/** @type {Node | null} */ (event.relatedTarget))) {
      draw().catch((error) => report(actions, error));
    }
  });

  // The timeline is read before the task's state: a task that closes in between still sends its TASK_CLOSED.
  const first = await ctx.api.json(`${path}/events`, {signal: ctx.signal});
  timeline.replaceChildren(...first.events.map(line));
  cursor = first.next;
  await draw();
  if (!first.events.some((/** @type {any} */ event) => event.type === "TASK_CLOSED")) {
    following = true;
    ctx.api.follow(id, cursor, (event) => {
      cursor = event.id;
      timeline.append(line(event));
      if (REDRAW_ON.includes(event.type)) draw().catch((error) => report(actions, error));
    }, ctx.signal).catch((error) => report(actions, error)).finally(() => { following = false; });
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

/**
 * @param {HTMLElement} element @param {import("../api.js").Context} ctx @param {any} detail
 * @param {{mode: string, shown: string}} viewing what the viewer shows, kept across redraws
 */
function drawResult(element, ctx, detail, viewing) {
  const shown = JSON.stringify([detail.result, detail.artifacts]);
  if (shown === viewing.shown) return;  // nothing new: keep the chosen document and mode, fetch nothing again
  viewing.shown = shown;
  const documents = detail.artifacts.filter((/** @type {any} */ a) => a.type !== "attachment");
  const attachments = detail.artifacts.filter((/** @type {any} */ a) => a.type === "attachment");
  /** @type {HTMLElement[]} */
  const parts = [];
  if (detail.result) parts.push(h("p", {}, text(detail.result.summary)));
  if (documents.length) parts.push(...viewer(ctx, documents, viewing));
  if (attachments.length) {
    parts.push(h("p", {}, t("task.attachments"), ...attachments.map((/** @type {any} */ a) => h("span", {}, " ",
      h("button", {type: "button", class: "link", disabled: !a.readable, onclick: () =>
        download(ctx, a).catch((error) => report(element, error))},
      `${a.name ?? a.ref}${a.untrusted ? ` (${t("task.untrusted")})` : ""}`)))));
  }
  element.replaceChildren(...parts);
}

/**
 * @param {import("../api.js").Context} ctx @param {any[]} documents oldest first
 * @param {{mode: string}} viewing the chosen mode, kept when a new attempt redraws the viewer
 */
function viewer(ctx, documents, viewing) {
  const view = h("div", {class: "viewer"});
  const select = h("select", {"aria-label": t("task.document")},
    ...documents.map((a, i) => h("option", {value: a.ref}, t("task.version", {n: i + 1}))));
  select.value = documents[documents.length - 1].ref;
  /** @type {[string, string][]} */
  const modes = [["markdown", t("task.markdown")], ["source", t("task.source")], ["diff", t("task.diff")]];
  const buttons = modes.map(([name, label]) => h("button", {type: "button", onclick: () => {
    viewing.mode = name;
    show().catch((error) => report(view, error));
  }}, label));

  async function show() {
    const mode = viewing.mode;
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
