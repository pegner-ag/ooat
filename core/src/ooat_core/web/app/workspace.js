// A task's work on its project's folders, as the task page shows it (design 07 §7): OOAT's own list of files, the
// report of a revert, and which artifacts are the documents (originals and diffs are not).
import { t } from "./i18n.js";

/** @param {{path: string, kind: string, added: number, removed: number}} file */
export function fileLine(file) {
  return file.kind === "created" ? t("task.fileCreated", {path: file.path, added: file.added})
    : t("task.fileChanged", {path: file.path, added: file.added, removed: file.removed});
}

/** @param {{restored: any[], skipped: {path: string, reason: string}[], kept: string[]}} result */
export function revertReport(result) {
  return [t("task.revertReport", {restored: result.restored.length, skipped: result.skipped.length,
    kept: result.kept.length}),
  ...result.skipped.map((s) => t("task.revertSkipped", {path: s.path, reason: s.reason}))];
}

/** @template {{type: string}} T @param {T[]} artifacts @returns {T[]} */
export function documents(artifacts) {
  return artifacts.filter((a) => a.type === "markdown_document");
}
