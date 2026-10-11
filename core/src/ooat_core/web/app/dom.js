// The one way the app builds the page: elements and text nodes, never HTML from data (design 05 §6). Only
// markdown.js writes HTML, from markdown-it with raw HTML off; core/tests/test_web.py holds that rule.

/** @typedef {string | boolean | undefined | ((event: Event) => void)} Prop */
/** @typedef {Node | string | null | undefined | false} Child */

/**
 * An element with attributes, `on<event>` handlers and children.
 * @template {keyof HTMLElementTagNameMap} K
 * @param {K} tag
 * @param {Record<string, Prop>} [props]
 * @param {...Child} children
 * @returns {HTMLElementTagNameMap[K]}
 */
export function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (typeof value === "function") element.addEventListener(name.slice(2), value);
    else if (value === true) element.setAttribute(name, "");
    else if (typeof value === "string") element.setAttribute(name, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) element.append(child);
  }
  return element;
}

/**
 * A group of radio buttons; `value()` is the checked one, or null.
 * @param {string} name unique on the page
 * @param {[string, string][]} options value and label
 */
export function radios(name, options) {
  const inputs = options.map(([value]) => h("input", {type: "radio", name, value}));
  const element = h("span", {class: "radios"}, ...options.map(([, label], i) => h("label", {}, inputs[i], label)));
  return {element, value: () => inputs.find((input) => input.checked)?.value ?? null};
}

/**
 * Shows an error where the screen is. Not when the screen was left (an aborted request) or the session ended
 * (the sign-in notice is already shown).
 * @param {Element} element
 * @param {unknown} error
 */
export function report(element, error) {
  if (error instanceof DOMException && error.name === "AbortError") return;
  if (error instanceof Error && "signedOut" in error && error.signedOut) return;
  element.append(h("span", {class: "error", role: "alert"}, error instanceof Error ? error.message : String(error)));
}
