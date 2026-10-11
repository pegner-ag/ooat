// Documents may derive from untrusted attachments: never trusted markup (design 05 §6). Raw HTML is off, so tags
// show as text; markdown-it refuses javascript:, vbscript:, file: and non-image data: links.
import MarkdownIt from "./vendor/markdown-it.esm.min.mjs";

const md = new MarkdownIt({html: false, linkify: false, typographer: false});

/** @param {string} source @returns {string} HTML */
export function renderMarkdown(source) {
  return md.render(source);
}

/**
 * The app's only innerHTML: markdown-it's output, which escapes everything it does not produce itself.
 * @param {Element} element
 * @param {string} source
 */
export function showMarkdown(element, source) {
  element.innerHTML = renderMarkdown(source);
}
