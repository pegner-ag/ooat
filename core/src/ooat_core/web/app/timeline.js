// One line per ledger event on the task page (design 05 §4). "Live" is this timeline of typed events, not model
// tokens or agent conversation (spec §10).
import { text } from "./format.js";
import { t } from "./i18n.js";

/**
 * @param {any} event an event of GET /tasks/{id}/events
 * @returns {{tone: "info" | "ok" | "fail" | "ask", text: string}}
 */
export function describe(event) {
  const body = event.body ?? {};
  if (body.redacted) return {tone: "info", text: `${event.type} · ${t("common.redacted")}`};
  const who = event.actor.id;
  switch (event.type) {
    case "TASK_SUBMITTED":
      return {tone: "info", text: t("timeline.submitted", {who, channel: body.channel ?? "cli"})};
    case "TOPOLOGY_DECIDED":
      return {tone: "info", text: t("timeline.gate", {topology: body.topology})};
    case "CONTRACT_ISSUED":
      return {tone: "info", text: t("timeline.contract")};
    case "RESULT":
      return {tone: body.outcome === "FAILED" ? "fail" : "ok", text: t("timeline.result", {outcome: body.outcome})};
    case "GATE_PASSED":
      return {tone: "ok", text: t("timeline.passed")};
    case "GATE_FAILED":
      return {tone: "fail", text: t("timeline.failed")};
    case "DECISION":
      return {tone: "info", text: t("timeline.decision", {who, decision: body.decision})};
    case "HIL_REQUEST":
      return {tone: "ask", text: t("timeline.asked", {question: text(body.question)})};
    case "HIL_RESPONSE":
      return {tone: "info", text: body.default_applied ? t("timeline.defaulted", {choice: body.choice})
        : t("timeline.answered", {who, choice: body.choice ?? body.text ?? ""})};
    case "TASK_CLOSED":
      return {tone: body.state === "CLOSED_DONE" ? "ok" : "fail", text: t("timeline.closed", {state: body.state})};
    case "TASK_RATED":
      return {tone: "info", text: t("timeline.rated", {who, value: body.value_class,
        verdict: body.accepted ? t("common.yes") : t("common.no")})};
    case "WORKSPACE_USED":
      return {tone: body.limit ? "ask" : "info", text: t("timeline.workspace", {by: body.by,
        changed: body.changed.length, created: body.created.length, read: body.read.length,
        refused: body.refused.length})};
    case "WORKSPACE_REVERTED":
      return {tone: "info", text: t("timeline.reverted", {who, restored: body.restored.length,
        skipped: body.skipped.length, kept: body.kept.length})};
    default:
      return {tone: "info", text: event.type};
  }
}
