import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderMarkdown } from "../src/ooat_core/web/app/markdown.js";

test("markdown renders headings and safe links", () => {
  assert.match(renderMarkdown("# Release notes"), /<h1>Release notes<\/h1>/);
  assert.match(renderMarkdown("[docs](https://example.org)"), /<a href="https:\/\/example.org">docs<\/a>/);
});

test("markdown never passes raw HTML or a javascript: link", () => {
  const html = renderMarkdown("<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[x](javascript:alert(1))");
  assert.doesNotMatch(html, /<script|<img|href="javascript:/i);  // the refused link stays as plain text
  assert.match(html, /&lt;script&gt;/);
});

test("the vendored renderer is the pinned package's file", () => {
  const vendored = readFileSync(new URL("../src/ooat_core/web/app/vendor/markdown-it.esm.min.mjs", import.meta.url));
  const pinned = readFileSync(new URL("../node_modules/markdown-it/dist/browser/markdown-it.esm.min.mjs",
    import.meta.url));
  assert.ok(vendored.equals(pinned));
});
