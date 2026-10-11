// The UI in English or Czech (spec §10): the browser's language, or the operator's choice in the header.
import cs from "./i18n/cs.js";
import en from "./i18n/en.js";

/** @typedef {keyof typeof en} Key */

/** @type {"en" | "cs"} */
let language = "en";

/**
 * @param {string | null | undefined} preferred a stored choice or navigator.language
 * @returns {"en" | "cs"}
 */
export function setLanguage(preferred) {
  language = preferred?.toLowerCase().startsWith("cs") ? "cs" : "en";
  return language;
}

export function currentLanguage() {
  return language;
}

/**
 * The string for `key` in the current language, with `{name}` filled from `vars`.
 * @param {Key} key
 * @param {Record<string, string | number>} [vars]
 */
export function t(key, vars = {}) {
  const found = (language === "cs" ? cs : en)[key];
  return found.replace(/\{(\w+)\}/g, (whole, name) => (name in vars ? String(vars[name]) : whole));
}
