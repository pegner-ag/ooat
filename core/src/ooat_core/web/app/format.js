// Money, counts and times as the screens show them (design 05 §4).
import { currentLanguage, t } from "./i18n.js";

const MINUTE_MS = 60_000;

/** Dollars: cents, or the digits that matter below a cent ("$0.002"). @param {number | null | undefined} usd */
export function money(usd) {
  if (usd === null || usd === undefined) return "—";
  if (usd === 0 || Math.abs(usd) >= 0.01) return `$${usd.toFixed(2)}`;
  const small = usd.toFixed(4).replace(/0+$/, "");
  return small.endsWith(".") ? "<$0.0001" : `$${small}`;
}

/** 410000 → "410k". @param {number} n */
export function count(n) {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** How long ago: "now", "2 min", "3 h", or the date. @param {string} ts @param {Date} now */
export function ago(ts, now) {
  const minutes = Math.floor((now.getTime() - Date.parse(ts)) / MINUTE_MS);
  if (minutes < 1) return t("time.now");
  if (minutes < 60) return t("time.minutes", {n: minutes});
  if (minutes < 24 * 60) return t("time.hours", {n: Math.floor(minutes / 60)});
  return new Date(ts).toLocaleDateString(currentLanguage());
}

/** Until a deadline: "in 5 min", "in 23 h", or "overdue". @param {string} ts @param {Date} now */
export function until(ts, now) {
  const minutes = Math.ceil((Date.parse(ts) - now.getTime()) / MINUTE_MS);
  if (minutes <= 0) return t("time.overdue");
  if (minutes < 60) return t("time.inMinutes", {n: minutes});
  return t("time.inHours", {n: Math.floor(minutes / 60)});
}

/** "10:02" in the reader's time zone. @param {string} ts */
export function clock(ts) {
  return new Date(ts).toLocaleTimeString(currentLanguage(), {hour: "2-digit", minute: "2-digit"});
}

/**
 * A goal as a one-line title of at most 80 characters; a redaction stub as its notice.
 * @param {string | {redacted: string} | null | undefined} goal
 */
export function title(goal) {
  if (typeof goal !== "string") return t("common.redacted");
  const line = goal.split("\n", 1)[0].trim();
  return line.length > 80 ? `${line.slice(0, 79)}…` : line;
}

/** Text that may be a redaction stub. @param {string | {redacted: string} | null | undefined} value */
export function text(value) {
  if (typeof value === "string") return value;
  return value ? t("common.redacted") : "";
}
