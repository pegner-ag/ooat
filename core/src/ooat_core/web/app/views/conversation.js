// A conversation with the reception (design 08 §4, §9): its turns, the reception's buttons while it is open on the
// web, and one conversation's own page. The redaction notice of the server links to that page.
import { shown, tapKind, tapLabel } from "../conversation.js";
import { h, report } from "../dom.js";
import { ago, clock } from "../format.js";
import { t } from "../i18n.js";
import { showMarkdown } from "../markdown.js";

/** @typedef {import("../conversation.js").Turn} Turn */

/**
 * The turns of one conversation, appended as they come; never redrawn, so a half-typed correction stays.
 * @param {import("../api.js").Context} ctx
 * @param {{live: boolean, onTurn?: (turn: Turn) => void}} options live: the buttons work (an open web conversation)
 */
export function thread(ctx, options) {
  const element = h("div", {class: "thread", "aria-live": "polite"});
  /** @type {Set<string>} */
  const seen = new Set();
  /** @type {() => void} turns off the last reply's taps: a tap always answers the newest decision */
  let retire = () => {};

  /** @param {any[]} events */
  function add(events) {
    for (const turn of shown(events, seen)) {
      if (turn.who === "reception" || turn.who === "report") retire();
      element.append(turnElement(turn));
      options.onTurn?.(turn);
    }
  }

  /** @param {Turn} turn */
  function turnElement(turn) {
    if (turn.who === "closed") return h("p", {class: "muted"}, t("conv.closed", {reason: turn.text ?? ""}));
    if (turn.who === "you") {
      const label = turn.tap ? tapLabel(turn.tap) : null;
      const said = turn.redacted ? t("common.redacted") : [label ? t(label) : turn.tap, turn.text].filter(Boolean)
        .join(": ");
      return h("div", {class: "turn you"}, h("time", {datetime: turn.ts}, clock(turn.ts)), h("p", {}, said));
    }
    const body = h("div", {class: "said"});
    if (turn.redacted) {
      body.append(h("p", {class: "muted"}, t("common.redacted"), " ", h("a",
        {href: `/conversations/${turn.conversation}`, "data-route": ""}, t("conv.title", {project: turn.project}))));
    } else {
      showMarkdown(body, turn.text ?? "");
    }
    const status = h("p", {class: "status", role: "status"});
    return h("div", {class: `turn ${turn.who}`},
      h("time", {datetime: turn.ts},
        `${t(turn.who === "report" ? "conv.report" : "conv.reception")} · ${clock(turn.ts)}`),
      body,
      turn.options.length ? h("ol", {}, ...turn.options.map((option) => h("li", {}, option))) : null,
      turn.task ? h("p", {}, h("a", {href: `/tasks/${turn.task}`, "data-route": ""}, t("conv.openTask"))) : null,
      options.live && turn.buttons.length ? buttons(turn, status) : null, status);
  }

  /** @param {Turn} turn @param {HTMLElement} status */
  function buttons(turn, status) {
    const forgets = turn.buttons.filter((tap) => tapKind(tap) === "forget").length;
    let forget = 0;
    const correction = h("span", {class: "row", hidden: true});
    /** @type {HTMLButtonElement[]} the conversation's taps (Yes, Differently, …); Forget and Done stay on */
    const taps = [];
    retire = () => {
      for (const button of taps) button.disabled = true;
      correction.hidden = true;
    };

    /** @param {string} tap @param {HTMLButtonElement} pressed @param {string} [text] */
    async function press(tap, pressed, text) {
      const kind = tapKind(tap);
      const mem = tap.split(":", 2)[1];
      if (kind === "forget" && !confirm(t("conv.forgetConfirm"))) return;
      const group = kind === "forget" || kind === "done" ? [pressed] : taps;
      for (const button of group) button.disabled = true;
      status.textContent = "";
      try {
        if (kind === "forget") {
          await ctx.api.json(`/memory/${encodeURIComponent(turn.project)}/${encodeURIComponent(mem)}`,
            {method: "DELETE"});
          status.textContent = t("conv.forgotten");
        } else if (kind === "done") {
          await ctx.api.json(`/memory/${encodeURIComponent(turn.project)}/${encodeURIComponent(mem)}`,
            {method: "PATCH", body: {done: true}});
          status.textContent = t("conv.markedDone");
        } else {
          const tapped = await ctx.api.json(`/conversations/${encodeURIComponent(turn.conversation)}/taps`,
            {method: "POST", body: {tap, ...(text ? {text} : {})}});
          add(tapped.decision ? [tapped.decision] : []);  // the stream brings it too: shown once
          if (!tapped.decision) status.textContent = t("home.received");
        }
        correction.hidden = true;
      } catch (error) {
        report(status, error);
        for (const button of group) button.disabled = false;
      }
    }

    /** @type {HTMLButtonElement[]} */
    const all = [];
    for (const tap of turn.buttons) {
      const kind = tapKind(tap);
      const key = tapLabel(tap);
      if (key === null) continue;
      if (kind === "forget") forget += 1;
      const label = kind === "forget" && forgets > 1 ? t("conv.forgetN", {n: forget}) : t(key);
      const button = h("button", {type: "button", class: kind === "yes" ? "recommended" : undefined, onclick: () => {
        if (kind !== "differently") {
          press(tap, button);
          return;
        }
        correction.hidden = false;  // the correction goes with the tap; an empty one lets the reception ask
        correction.querySelector("input")?.focus();
      }}, label);
      all.push(button);
      if (kind !== "forget" && kind !== "done") taps.push(button);
    }
    if (turn.buttons.includes("differently")) {
      const typed = h("input", {type: "text", maxlength: "20000", placeholder: t("conv.correction"),
        "aria-label": t("conv.correction")});
      const send = h("button", {type: "button", onclick: () => press("differently", send, typed.value.trim())},
        t("home.send"));
      taps.push(send);
      correction.append(typed, send);
    }
    return h("div", {}, h("div", {class: "actions"}, ...all), correction);
  }

  return {element, add};
}

/**
 * Follows a conversation from `after`, adding each event to `shown`; ends at its close or when `signal` aborts.
 * @param {import("../api.js").Context} ctx @param {string} conversation @param {string | null} after
 * @param {{add: (events: any[]) => void}} into @param {AbortSignal} signal @param {Element} errors
 * @param {() => void} [onClosed]
 */
export function follow(ctx, conversation, after, into, signal, errors, onClosed) {
  ctx.api.followConversation(conversation, after, (event) => {
    into.add([event]);
    if (event.type === "CONVERSATION_CLOSED") onClosed?.();
  }, signal).catch((error) => report(errors, error));
}

/**
 * One conversation by its id, read only unless it is open on the web.
 * @param {HTMLElement} root @param {import("../api.js").Context} ctx @param {string} id
 */
export async function conversationPage(root, ctx, id) {
  const found = await ctx.api.json(`/conversations/${encodeURIComponent(id)}`, {signal: ctx.signal});
  const live = !found.closed && found.channel === "web";
  const turns = thread(ctx, {live});
  const errors = h("p", {class: "status", role: "status"});
  root.replaceChildren(h("h1", {}, t("conv.title", {project: found.project})),
    h("p", {class: "muted"}, t("conv.started", {channel: found.channel, time: ago(found.started, new Date())})),
    ...(live ? [] : [h("p", {class: "muted"}, t("conv.readOnly"))]), turns.element, errors);
  turns.add(found.events);
  if (live) {
    const last = found.events.length ? found.events[found.events.length - 1].id : null;
    follow(ctx, id, last, turns, ctx.signal, errors);
  }
}
