import assert from "node:assert/strict";
import { test } from "node:test";
import { setLanguage } from "../src/ooat_core/web/app/i18n.js";
import { corrections, decisionText, ratingBody } from "../src/ooat_core/web/app/rating.js";

const gate = {event: "evt_g", question: "a1.1", kind: "gate", answer: 0.93, confidence: 0.9, disputed: false,
  options: null};
const branch = {event: "evt_g", question: "a5", kind: "gate", answer: "one", confidence: 0.8, disputed: false,
  options: ["one", "two"]};
const check = {event: "evt_c", question: "c1", kind: "acceptance", answer: 0.41, confidence: 0.7, disputed: true,
  options: null};

test("marked decisions become verdicts; a wrong yes/no is corrected to the other answer", () => {
  assert.deepEqual(ratingBody({accepted: false, valueClass: "B", note: "  too short  ", marks: [
    {decision: gate, mark: "right"}, {decision: check, mark: "wrong"}, {decision: branch, mark: "wrong",
      option: "two"}]}), {
    accepted: false, value_class: "B", note: "too short", decisions: [
      {event: "evt_g", question: "a1.1", verdict: "confirmed"},
      {event: "evt_c", question: "c1", verdict: "corrected", value: 1},
      {event: "evt_g", question: "a5", verdict: "corrected", value: "two"}]});
});

test("a wrong choice can only be corrected to another option", () => {
  assert.deepEqual(corrections(branch), ["two"]);
  assert.deepEqual(corrections(gate), []);
});

test("no marks and no note: a one-click rating", () => {
  assert.deepEqual(ratingBody({accepted: true, valueClass: "A", note: "", marks: []}),
    {accepted: true, value_class: "A", decisions: []});
});

test("a decision reads as what was decided, and how sure", () => {
  setLanguage("en");
  assert.equal(decisionText(gate), "Gate A1.1: yes (0.93)");
  assert.equal(decisionText(branch), "Gate A5: one");
  assert.equal(decisionText(check), "Acceptance C1: no (0.41) · the critic disagreed");
});
