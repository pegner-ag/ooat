// The cards the operator acts on, in the inbox and on the task page (design 05 §4): a question with one button per
// option (★ the recommended one; the default on silence and the deadline always printed), and the rating card.
import { h, radios } from "./dom.js";
import { money, text, title, until } from "./format.js";
import { t } from "./i18n.js";
import { decisionText, ratingBody } from "./rating.js";

/**
 * @param {any} request an entry of GET /hil
 * @param {import("./api.js").Context} ctx
 * @param {() => void} onDone after the answer is recorded
 */
export function questionCard(request, ctx, onDone) {
  const status = h("p", {class: "status", role: "status"});
  const label = (/** @type {any} */ option) => text(option.label);
  const fallback = request.options.find((/** @type {any} */ o) => o.id === request.default_on_silence);
  const footer = h("p", {class: "muted"}, t("hil.default", {
    option: fallback ? label(fallback) : request.default_on_silence, deadline: until(request.deadline, new Date())}));
  const question = h("p", {}, "? ", h("a", {href: `/tasks/${request.task}`, "data-route": ""}, text(request.question)));
  if (request.risk_class === "R3") {
    return h("article", {class: "card question"}, question, h("p", {class: "warning"}, t("hil.r3")), footer);
  }
  const note = h("input", {type: "text", maxlength: "20000", placeholder: t("hil.note"), "aria-label": t("hil.note")});
  const buttons = request.options.map((/** @type {any} */ option) => h("button", {
    type: "button", class: option.id === request.recommended ? "recommended" : undefined,
    onclick: () => answer(option.id),
  }, label(option) + (option.id === request.recommended ? " ★" : "")
    + (option.cost_usd ? ` · ${money(option.cost_usd)}` : "")));

  /** @param {string} choice */
  async function answer(choice) {
    for (const button of buttons) button.disabled = true;
    const typed = note.value.trim();
    try {
      await ctx.api.json(`/hil/${encodeURIComponent(request.request)}/answer`,
        {method: "POST", body: {choice, ...(typed ? {text: typed} : {})}});
      status.textContent = t("hil.answered");
      onDone();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
      for (const button of buttons) button.disabled = false;
    }
  }

  return h("article", {class: "card question"}, question, h("div", {class: "actions"}, ...buttons), note, footer,
    status);
}

/**
 * @param {any} entry an entry of GET /ratings/queue
 * @param {import("./api.js").Context} ctx
 * @param {{compact: boolean, onDone: () => void}} options compact: one-click buttons for the inbox
 */
export function ratingCard(entry, ctx, {compact, onDone}) {
  const status = h("p", {class: "status", role: "status"});
  const heading = h("p", {}, "★ ", h("a", {href: `/tasks/${entry.task}`, "data-route": ""}, title(entry.goal)),
    ` · ${entry.state} · ${money(entry.cost_usd)}`);

  /** @param {object} body */
  async function save(body) {
    try {
      await ctx.api.json(`/tasks/${encodeURIComponent(entry.task)}/rating`, {method: "POST", body});
      status.textContent = t("rating.saved");
      onDone();
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : String(error);
    }
  }

  if (compact) {
    return h("article", {class: "card rating"}, heading, h("div", {class: "actions"},
      ...["A", "B", "C"].map((value) => h("button", {type: "button", onclick: () =>
        save(ratingBody({accepted: true, valueClass: value, note: "", marks: []}))}, t("rating.acceptedAs", {value}))),
      h("a", {href: `/tasks/${entry.task}`, "data-route": "", class: "button"}, t("rating.notAccepted"))), status);
  }

  const accepted = radios(`accepted-${entry.task}`, [["yes", t("common.yes")], ["no", t("common.no")]]);
  const value = radios(`value-${entry.task}`, [["A", "A"], ["B", "B"], ["C", "C"]]);
  const note = h("input", {type: "text", maxlength: "5000", placeholder: t("rating.note"), "aria-label": t("rating.note")});
  const decisions = /** @type {import("./rating.js").Decision[]} */ (entry.decisions);
  const marks = decisions.map((decision, i) => {
    const mark = radios(`decision-${entry.task}-${i}`, [["right", t("rating.right")], ["wrong", t("rating.wrong")]]);
    const option = decision.options ? h("select", {"aria-label": t("rating.correct")},
      ...decision.options.map((o) => h("option", {value: o}, o))) : null;
    return {decision, mark, option, element: h("li", {}, decisionText(decision), " ", mark.element, " ", option)};
  });
  return h("form", {class: "card rating", onsubmit: (event) => {
    event.preventDefault();
    const yes = accepted.value();
    const valueClass = value.value();
    if (yes === null || valueClass === null) {
      status.textContent = t("rating.incomplete");
      return;
    }
    save(ratingBody({accepted: yes === "yes", valueClass, note: note.value,
      marks: marks.filter((m) => m.mark.value() !== null)
        .map((m) => ({decision: m.decision, mark: m.mark.value() ?? "", option: m.option?.value}))}));
  }}, heading,
  h("p", {}, t("rating.accepted"), " ", accepted.element, "  ", t("rating.value"), " ", value.element), note,
  marks.length ? h("p", {class: "muted"}, t("rating.decisions")) : null,
  marks.length ? h("ul", {}, ...marks.map((m) => m.element)) : null,
  h("button", {type: "submit"}, t("rating.save")), status);
}
