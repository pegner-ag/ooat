// What a rating sends (design 05 §4, ADR 0011): marked decisions become verdicts, unmarked ones stay unrated.
import { t } from "./i18n.js";

/**
 * A decision OOAT made alone, as GET /ratings/queue lists it.
 * @typedef {{event: string, question: string, kind: string, answer: number | string, confidence: number,
 *            disputed: boolean, options: string[] | null}} Decision
 */

/**
 * The body of POST /tasks/{id}/rating. "wrong" corrects a yes/no decision to the other answer and a choice to the
 * option picked.
 * @param {{accepted: boolean, valueClass: string, note: string,
 *          marks: {decision: Decision, mark: string, option?: string}[]}} input
 */
export function ratingBody(input) {
  const note = input.note.trim();
  return {
    accepted: input.accepted, value_class: input.valueClass, ...(note ? {note} : {}),
    decisions: input.marks.map(({decision, mark, option}) => ({
      event: decision.event, question: decision.question,
      ...(mark === "right" ? {verdict: "confirmed"} : {
        verdict: "corrected",
        value: typeof decision.answer === "number" ? (decision.answer >= 0.5 ? 0 : 1) : option,
      }),
    })),
  };
}

/** "Gate A1.1: yes (0.93)". @param {Decision} decision */
export function decisionText(decision) {
  const who = decision.kind === "gate" ? t("rating.gate") : t("rating.acceptance");
  const answer = typeof decision.answer === "number"
    ? `${decision.answer >= 0.5 ? t("common.yes") : t("common.no")} (${decision.answer.toFixed(2)})`
    : decision.answer;
  return `${who} ${decision.question.toUpperCase()}: ${answer}${decision.disputed ? ` · ${t("rating.disputed")}` : ""}`;
}
