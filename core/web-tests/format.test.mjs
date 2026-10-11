import assert from "node:assert/strict";
import { test } from "node:test";
import { ago, count, money, text, title, until } from "../src/ooat_core/web/app/format.js";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";

const now = new Date("2026-10-11T10:00:00Z");

test("money shows cents, or the digits that matter below a cent", () => {
  assert.equal(money(0.42), "$0.42");
  assert.equal(money(3.1), "$3.10");
  assert.equal(money(0), "$0.00");
  assert.equal(money(0.002), "$0.002");
  assert.equal(money(0.00004), "<$0.0001");
  assert.equal(money(null), "—");
});

test("counts of tokens are short", () => {
  assert.deepEqual([count(950), count(410_000), count(2_400_000)], ["950", "410k", "2.4M"]);
});

test("times are relative, in the chosen language", () => {
  setLanguage("en");
  assert.equal(ago("2026-10-11T09:58:00Z", now), "2 min");
  assert.equal(until("2026-10-12T09:00:00Z", now), "in 23 h");
  assert.equal(until("2026-10-11T09:00:00Z", now), "overdue");
  setLanguage("cs-CZ");
  assert.equal(until("2026-10-11T10:05:00Z", now), "za 5 min");
  setLanguage("en");
});

test("a goal becomes a one-line title, and a redaction stub its notice", () => {
  assert.equal(title("Release notes 0.3\nwith details"), "Release notes 0.3");
  assert.equal(title("x".repeat(100)).length, 80);
  const stub = {redacted: "above this token's data class; open in the web app", link: "/tasks/tsk_1"};
  assert.equal(title(stub), "Above this session's data class: not shown.");
  assert.equal(text(stub), "Above this session's data class: not shown.");
  assert.equal(text("plain"), "plain");
});

import { percent } from "../src/ooat_core/web/app/format.js";

test("a fraction reads as a signed percentage", () => {
  assert.deepEqual([percent(0.08), percent(-0.125), percent(0), percent(null)], ["+8 %", "-13 %", "0 %", "—"]);
});
