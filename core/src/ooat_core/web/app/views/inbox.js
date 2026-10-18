// The lists of the home page (design 05 §4): what waits for me, what is stuck, the tasks; and the form for a task
// with exact criteria, folded under the reception's box (design 08 §9, plan 08b).
import { questionCard, ratingCard } from "../cards.js";
import { h, report } from "../dom.js";
import { ago, clock, money, title } from "../format.js";
import { t } from "../i18n.js";

const REFRESH_MS = 15_000;
export const MAX_ATTACHMENT_BYTES = 14 * 1024 * 1024;  // a request carries at most 20 MB; base64 adds a third
const DATA_CLASSES = ["public", "internal", "client_confidential", "personal"];

/**
 * Waiting for you, stuck, and the tasks, refreshed every 15 s while the focus is outside them.
 * @param {import("../api.js").Context} ctx
 * @param {{known: (tasks: any[]) => void}} form told the listed tasks, for its project suggestions
 */
export async function taskLists(ctx, form) {
  const lists = h("div");

  async function draw() {
    const [tasks, questions, ratings] = await Promise.all([
      ctx.api.json("/tasks?limit=50", {signal: ctx.signal}), ctx.api.json("/hil", {signal: ctx.signal}),
      ctx.api.json("/ratings/queue", {signal: ctx.signal})]);
    form.known(tasks.tasks);
    const again = () => { draw().catch((error) => report(lists, error)); };
    const stuck = tasks.tasks.filter((/** @type {any} */ task) => task.resume_after);
    lists.replaceChildren(
      h("h2", {}, t("inbox.waiting", {n: questions.requests.length + ratings.tasks.length})),
      ...questions.requests.map((/** @type {any} */ request) => questionCard(request, ctx, again)),
      ...ratings.tasks.map((/** @type {any} */ entry) => ratingCard(entry, ctx, {compact: true, onDone: again})),
      h("h2", {}, t("inbox.stuck", {n: stuck.length})),
      ...stuck.map((/** @type {any} */ task) => h("p", {}, "⏸ ", link(task), " ",
        t("inbox.paused", {at: clock(task.resume_after)}))),
      h("h2", {}, t("inbox.tasks")), table(tasks.tasks));
  }

  await draw();
  const timer = setInterval(() => {
    if (!lists.contains(document.activeElement)) draw().catch((error) => report(lists, error));  // keep typed text
  }, REFRESH_MS);
  ctx.signal.addEventListener("abort", () => clearInterval(timer));
  return lists;
}

/** @param {any} task */
function link(task) {
  return h("a", {href: `/tasks/${task.task}`, "data-route": ""}, title(task.goal));
}

/** @param {any[]} tasks */
function table(tasks) {
  const now = new Date();
  const heads = [t("inbox.task"), t("inbox.state"), t("inbox.topology"), t("inbox.cost"), t("inbox.updated")];
  return h("table", {}, h("thead", {}, h("tr", {}, ...heads.map((head) => h("th", {}, head)))),
    h("tbody", {}, ...tasks.map((task) => h("tr", {}, h("td", {}, link(task)), h("td", {}, task.state),
      h("td", {}, task.topology ?? "—"), h("td", {}, `${money(task.cost_usd)} / ${money(task.budget_usd)}`),
      h("td", {}, ago(task.updated, now))))));
}

/**
 * A task with exact criteria, data class and budget, in a closed <details>.
 * @param {import("../api.js").Context} ctx
 */
export function taskForm(ctx) {
  const goal = h("textarea", {rows: "3", required: true, maxlength: "20000", placeholder: t("new.goal"),
    "aria-label": t("new.goal")});
  const acceptance = h("textarea", {rows: "2", placeholder: t("new.acceptance"), "aria-label": t("new.acceptance")});
  const project = h("input", {required: true, pattern: "[a-z0-9][a-z0-9_\\-]*", maxlength: "64",
    list: "ooat-projects", placeholder: t("new.project"), "aria-label": t("new.project")});
  const projects = h("datalist", {id: "ooat-projects"});
  const dataClass = h("select", {"aria-label": t("new.dataClass")},
    ...DATA_CLASSES.map((name) => h("option", {value: name}, name)));
  dataClass.value = "internal";
  const budget = h("input", {type: "number", min: "0.01", step: "0.01", placeholder: t("new.budget"),
    "aria-label": t("new.budget")});
  const attachments = h("input", {type: "file", multiple: true, "aria-label": t("new.attach")});
  const submit = h("button", {type: "submit"}, t("new.submit"));
  const status = h("p", {class: "status", role: "status"});
  let key = crypto.randomUUID();  // one Idempotency-Key per task typed in: a double click or a retry makes one task
  const sample = new URLSearchParams(location.search).has("sample");
  if (sample) {  // Setup's last step: filled in, sent only on Submit
    goal.value = t("sample.goal");
    acceptance.value = t("sample.acceptance");
    project.value = "sample";
    history.replaceState(null, "", "/");
  }

  /** @param {Event} event */
  async function send(event) {
    event.preventDefault();
    const chosen = [...(attachments.files ?? [])];
    if (chosen.reduce((sum, file) => sum + file.size, 0) > MAX_ATTACHMENT_BYTES) {
      status.textContent = t("new.tooLarge");
      return;
    }
    submit.disabled = true;
    status.textContent = "";
    try {
      const body = {
        project: project.value.trim(), goal: goal.value, data_class: dataClass.value,
        acceptance: acceptance.value.split("\n").map((line) => line.trim()).filter(Boolean),
        ...(budget.value ? {budget_usd: Number(budget.value)} : {}),
        attachments: await Promise.all(chosen.map(async (file) =>
          ({name: file.name, content_base64: await base64(file)}))),
      };
      const created = await ctx.api.json("/tasks", {method: "POST", body, headers: {"Idempotency-Key": key}});
      key = crypto.randomUUID();
      ctx.navigate(`/tasks/${created.task}`);
    } catch (error) {
      report(status, error);
    } finally {
      submit.disabled = false;
    }
  }

  const element = h("details", {open: sample}, h("summary", {}, t("home.exactTask")),
    h("form", {class: "card new-task", onsubmit: send}, goal, acceptance,
      h("div", {class: "row"}, project, projects, dataClass, budget, attachments, submit), status));
  return {
    element,
    /** The projects of the listed tasks, offered as you type; the newest is the default. @param {any[]} tasks */
    known(tasks) {
      const names = [...new Set(tasks.map((task) => task.project).filter(Boolean))];
      projects.replaceChildren(...names.sort().map((name) => h("option", {value: name})));
      if (!project.value && names.length) project.value = tasks.find((task) => task.project)?.project ?? "";
    },
  };
}

/** @param {File} file @returns {Promise<string>} */
export function base64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
