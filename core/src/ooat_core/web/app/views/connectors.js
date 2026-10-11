// Connectors (design 05 §4; spec §9 rule 1; ADR 0012, 0015): the consequences card, the classes to allow, the
// operator's responsibility for client or personal data, a typed confirmation; hooks are read before approval. The
// operator is the session's, never a form field.
import { h, report } from "../dom.js";
import { t } from "../i18n.js";

const CLASSES = ["public", "internal", "client_confidential", "personal"];
const RESPONSIBLE = ["client_confidential", "personal"];

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function connectors(root, ctx) {
  const list = h("div");
  const panel = h("section");
  root.replaceChildren(h("h1", {}, t("connectors.title")), list, panel);
  /** @param {string} id */
  const base = (id) => `/connectors/${encodeURIComponent(id)}`;

  async function draw() {
    const found = await ctx.api.json("/connectors", {signal: ctx.signal});
    list.replaceChildren(h("table", {}, h("tbody", {}, ...found.connectors.map((/** @type {any} */ c) => h("tr", {},
      h("td", {}, c.id), h("td", {}, `${c.state === "enabled" ? "●" : "○"} ${c.state}`),
      h("td", {class: "muted"}, c.blocked ?? c.detail),
      h("td", {}, h("button", {type: "button", onclick: () => card(c.id).catch((e) => report(panel, e))},
        t("connectors.card")), " ",
      c.state === "enabled" ? h("button", {type: "button", onclick: () => disable(c.id).catch((e) => report(panel, e))},
        t("connectors.disable")) : null, " ",
      h("button", {type: "button", onclick: () => hooks(c.id).catch((e) => report(panel, e))},
        t("connectors.hooks"))))))));
  }

  /** @param {string} id */
  async function card(id) {
    const found = await ctx.api.json(`${base(id)}/card`, {signal: ctx.signal});
    const boxes = CLASSES.map((name) => h("input", {type: "checkbox", value: name}));
    const automation = h("input", {type: "checkbox"});
    const regions = h("input", {type: "text", placeholder: "eu, us-east", "aria-label": t("connectors.regions")});
    const noTraining = h("input", {type: "checkbox"});
    const responsibility = h("fieldset", {hidden: true}, h("legend", {}, t("connectors.responsibility")),
      h("label", {}, t("connectors.regions"), " ", regions), h("br"), h("label", {}, noTraining,
        t("connectors.noTraining")));
    const responsible = () => boxes.some((box) => box.checked && RESPONSIBLE.includes(box.value));
    for (const box of boxes) box.addEventListener("change", () => { responsibility.hidden = !responsible(); });
    const confirm = h("input", {type: "text", autocomplete: "off", placeholder: id, "aria-label": t("connectors.confirm")});
    const status = h("p", {class: "status", role: "status"});
    panel.replaceChildren(h("h2", {}, id), h("pre", {class: "card"}, found.card), h("form", {onsubmit: async (event) => {
      event.preventDefault();
      const listed = regions.value.split(",").map((region) => region.trim().toLowerCase()).filter(Boolean);
      const body = {classes: boxes.filter((box) => box.checked).map((box) => box.value),
        automation: automation.checked, confirm: confirm.value.trim(),
        ...(responsible() ? {responsibility: {...(listed.length ? {processing_regions: listed} : {}),
          ...(noTraining.checked ? {no_training: true} : {})}} : {})};
      try {
        await ctx.api.json(`${base(id)}/enable`, {method: "POST", body});
        status.textContent = t("connectors.enabled");
        await draw();
      } catch (error) {
        report(status, error);
      }
    }}, h("p", {}, t("connectors.allow"), ...boxes.map((box) => h("label", {}, " ", box, box.value))),
    h("p", {}, h("label", {}, automation, t("connectors.automation"))), responsibility,
    h("p", {}, h("label", {}, t("connectors.confirm"), " ", confirm), " ",
      h("button", {type: "submit"}, t("connectors.enable"))), status));
  }

  /** @param {string} id */
  async function disable(id) {
    const reason = prompt(t("connectors.reason"))?.trim();
    if (!reason) return;
    await ctx.api.json(`${base(id)}/disable`, {method: "POST", body: {reason}});
    panel.replaceChildren(h("p", {class: "status"}, t("connectors.disabled")));
    await draw();
  }

  /** @param {string} id */
  async function hooks(id) {
    const found = await ctx.api.json(`${base(id)}/hooks`, {signal: ctx.signal});
    if (!found.hooks.length) {
      panel.replaceChildren(h("p", {class: "muted"}, t("connectors.noHooks")));
      return;
    }
    const confirm = h("input", {type: "text", autocomplete: "off", placeholder: id, "aria-label": t("connectors.confirm")});
    const status = h("p", {class: "status", role: "status"});
    panel.replaceChildren(h("h2", {}, t("connectors.hooksOf", {id})),
      ...found.hooks.map((/** @type {any} */ hook) => h("details", {},
        h("summary", {}, `${hook.path} · ${(hook.sha256 ?? "").slice(0, 12)}`), h("pre", {}, hook.text ?? ""))),
      h("form", {onsubmit: async (event) => {
        event.preventDefault();
        try {
          await ctx.api.json(`${base(id)}/approve-hooks`, {method: "POST", body: {confirm: confirm.value.trim(),
            hooks: found.hooks.map((/** @type {any} */ hook) => ({path: hook.path, sha256: hook.sha256}))}});
          status.textContent = t("connectors.approved");
          await draw();
        } catch (error) {
          report(status, error);
        }
      }}, h("p", {}, h("label", {}, t("connectors.confirm"), " ", confirm), " ",
        h("button", {type: "submit"}, t("connectors.approve")))), status);
  }

  await draw();
}
