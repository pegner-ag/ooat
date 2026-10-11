// Usage (design 05 §4, §8): spend, calls and tokens by role and by connector, tasks by outcome, waiting for answers.
import { h, report } from "../dom.js";
import { count, money, percent } from "../format.js";
import { t } from "../i18n.js";

/** @type {[string, () => string][]} */
const PERIODS = [["1d", () => t("usage.p1d")], ["7d", () => t("usage.p7d")], ["30d", () => t("usage.p30d")],
  ["90d", () => t("usage.p90d")], ["all", () => t("usage.pall")]];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function usage(root, ctx) {
  const period = h("select", {"aria-label": t("usage.period")},
    ...PERIODS.map(([value, label]) => h("option", {value}, label())));
  period.value = "7d";
  const project = h("select", {"aria-label": t("usage.project")}, h("option", {value: ""}, t("usage.allProjects")));
  const tasks = await ctx.api.json("/tasks?limit=200", {signal: ctx.signal});
  const names = [...new Set(tasks.tasks.map((/** @type {any} */ task) => task.project).filter(Boolean))];
  for (const name of names.sort()) project.append(h("option", {value: name}, name));
  const body = h("div");
  root.replaceChildren(h("h1", {}, t("usage.title")), h("div", {class: "row"}, period, project), body);

  async function draw() {
    const query = (/** @type {string} */ group) => `/stats?period=${period.value}&group=${group}${
      project.value ? `&project=${encodeURIComponent(project.value)}` : ""}`;
    const [byRole, byConnector] = await Promise.all([ctx.api.json(query("role"), {signal: ctx.signal}),
      ctx.api.json(query("connector"), {signal: ctx.signal})]);
    const {spend, tasks: closed, hil} = byRole;
    body.replaceChildren(
      h("p", {}, t("usage.spend", {total: money(spend.metered_usd + spend.shadow_usd),
        metered: money(spend.metered_usd), shadow: money(spend.shadow_usd)})),
      h("div", {class: "columns"}, groups(t("usage.byRole"), byRole.groups),
        groups(t("usage.byConnector"), byConnector.groups)),
      h("p", {}, t("usage.tasks", {closed: closed.closed, accepted: closed.accepted, rated: closed.rated,
        per: money(closed.cost_per_accepted_usd), delta: percent(closed.estimate_vs_actual)})),
      h("p", {}, t("usage.hil", {questions: hil.questions, answered: hil.answered, defaults: hil.defaults_applied,
        wait: hil.median_wait_minutes === null ? "—"
          : t("time.minutes", {n: Math.round(hil.median_wait_minutes)})})));
  }

  const again = () => { draw().catch((error) => report(body, error)); };
  period.addEventListener("change", again);
  project.addEventListener("change", again);
  await draw();
}

/** @param {string} heading @param {any[]} rows */
function groups(heading, rows) {
  const number = (/** @type {string} */ value) => h("td", {class: "number"}, value);
  return h("section", {}, h("h2", {}, heading), h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, ""), ...[t("usage.calls"), t("usage.tokens"), t("usage.metered"),
      t("usage.shadow")].map((name) => h("th", {class: "number"}, name)))),
    h("tbody", {}, ...rows.map((row) => h("tr", {}, h("td", {}, row.key), number(String(row.calls)),
      number(`${count(row.tokens_in)} / ${count(row.tokens_out)}`), number(money(row.metered_usd)),
      number(money(row.shadow_usd)))))));
}
