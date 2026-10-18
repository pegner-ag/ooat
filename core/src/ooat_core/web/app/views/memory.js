// Memory (design 08 §6, plan 08b): a project's items, or the operator's preferences (the scope `operator`), with
// add, edit, pin, done and forget. Texts live outside the ledger; forgetting deletes one for good (ADR 0018).
import { h, report } from "../dom.js";
import { ago } from "../format.js";
import { t } from "../i18n.js";
import { storedProject } from "./home.js";

const OPERATOR = "operator";
/** @type {[string, import("../i18n.js").Key][]} */
const GROUPS = [["fact", "memory.kind.fact"], ["glossary", "memory.kind.glossary"],
  ["preference", "memory.kind.preference"], ["todo", "memory.kind.todo"], ["summary", "memory.kind.summary"]];
const ADDABLE = ["fact", "glossary", "todo", "preference"];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx @param {string} scope */
export async function memoryPage(root, ctx, scope) {
  const preferences = scope === OPERATOR;
  const path = `/memory/${encodeURIComponent(scope)}`;
  const showDone = h("input", {type: "checkbox"});
  const list = h("div");
  const project = storedProject();
  const other = preferences
    ? project && h("a", {href: `/memory/${project}`, "data-route": ""}, t("memory.toProject", {project}))
    : h("a", {href: `/memory/${OPERATOR}`, "data-route": ""}, t("memory.toPreferences"));
  root.replaceChildren(h("h1", {}, preferences ? t("memory.preferences") : t("memory.title", {project: scope})),
    h("p", {}, other || null), addForm(), h("p", {}, h("label", {}, showDone, " ", t("memory.showDone"))), list,
    h("p", {class: "muted"}, t("memory.forgetNote")));

  async function draw() {
    const {items} = await ctx.api.json(`${path}${showDone.checked ? "?done=true" : ""}`, {signal: ctx.signal});
    if (!items.length) {
      list.replaceChildren(h("p", {class: "muted"}, t("memory.empty")));
      return;
    }
    const pinned = items.filter((/** @type {any} */ i) => i.pinned);
    /** @type {[import("../i18n.js").Key, any[]][]} */
    const groups = [["memory.kind.pinned", pinned], ...GROUPS.map(([kind, key]) => /** @type {[any, any[]]} */ (
      [key, items.filter((/** @type {any} */ i) => !i.pinned && i.kind === kind)]))];
    list.replaceChildren(...groups.filter(([, shown]) => shown.length).map(([key, shown]) =>
      h("section", {}, h("h2", {}, t(key)), ...shown.map(itemElement))));
  }

  const again = () => { draw().catch((error) => report(list, error)); };

  function addForm() {
    const kind = h("select", {"aria-label": t("memory.kind")}, ...(preferences ? ["preference"] : ADDABLE)
      .map((name) => h("option", {value: name}, t(/** @type {import("../i18n.js").Key} */ (`memory.kind.${name}`)))));
    const text = h("textarea", {rows: "2", required: true, maxlength: "2000", placeholder: t("memory.addText"),
      "aria-label": t("memory.addText")});
    const pin = h("input", {type: "checkbox"});
    const status = h("p", {class: "status", role: "status"});
    const add = h("button", {type: "submit"}, t("memory.add"));
    return h("form", {class: "card", onsubmit: async (/** @type {Event} */ event) => {
      event.preventDefault();
      add.disabled = true;
      status.textContent = "";
      try {
        await ctx.api.json(path, {method: "POST", body: {kind: kind.value, text: text.value, pinned: pin.checked}});
        text.value = "";  // kept on a refusal, so the operator can change it
        pin.checked = false;
        again();
      } catch (error) {
        report(status, error);
      } finally {
        add.disabled = false;
      }
    }}, text, h("div", {class: "row"}, kind, h("label", {}, pin, " ", t("memory.addPinned")), add), status);
  }

  /** @param {any} item */
  function itemElement(item) {
    const status = h("span", {class: "status", role: "status"});
    const text = h("span", {class: "text"}, item.text);
    const source = item.conversation
      ? h("a", {href: `/conversations/${item.conversation}`, "data-route": ""}, t("memory.source"))
      : t("memory.byHand");
    const meta = h("span", {class: "muted"}, `${item.data_class} · ${ago(item.noted, new Date())} · `, source,
      item.done ? ` · ${t("memory.isDone")}` : "");

    /** @param {string} method @param {object} [body] */
    async function change(method, body) {
      status.textContent = "";
      try {
        await ctx.api.json(`${path}/${encodeURIComponent(item.memory)}`, {method, body});
        again();
      } catch (error) {
        report(status, error);
      }
    }

    function edit() {
      const area = h("textarea", {rows: "3", maxlength: "2000", "aria-label": t("memory.edit")});
      area.value = item.text;
      const save = h("button", {type: "button", onclick: () => change("PATCH", {text: area.value})},
        t("memory.save"));
      const cancel = h("button", {type: "button", onclick: again}, t("memory.cancel"));
      text.replaceChildren(area, h("span", {class: "row"}, save, cancel));
      area.focus();
    }

    const actions = h("span", {class: "actions"},
      h("button", {type: "button", onclick: edit}, t("memory.edit")),
      h("button", {type: "button", onclick: () => change("PATCH", {pinned: !item.pinned})},
        item.pinned ? t("memory.unpin") : t("memory.pin")),
      item.kind === "todo" && !item.done
        ? h("button", {type: "button", onclick: () => change("PATCH", {done: true})}, t("memory.done")) : null,
      h("button", {type: "button", class: "danger", onclick: () => {
        if (confirm(t("memory.forgetConfirm"))) change("DELETE");
      }}, t("memory.forget")));
    return h("div", {class: "card memory-item"}, text, meta, actions, status);
  }

  showDone.addEventListener("change", again);
  await draw();
}
