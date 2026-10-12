// Setup (design 05 §10, plan 01c): your data, who you are, the connectors found, an optional token for a chat
// bridge (shown once), then the inbox with a sample task. The steps of `ooat init` in the terminal. Variable names
// only: the server never sends a key's value.
import { h, report } from "../dom.js";
import { t } from "../i18n.js";

/** @param {HTMLElement} root @param {import("../api.js").Context} ctx */
export async function setup(root, ctx) {
  const state = await ctx.api.json("/setup", {signal: ctx.signal});
  const config = state.config ?? "ooat.toml";
  const name = h("input", {type: "text", value: "chat", required: true, maxlength: "32",
    "aria-label": t("setup.tokenName")});
  const made = h("div");
  const status = h("p", {class: "status", role: "status"});

  /** @param {Event} event */
  async function createToken(event) {
    event.preventDefault();
    status.textContent = "";
    try {
      const token = await ctx.api.json("/setup/token", {method: "POST", body: {name: name.value.trim()}});
      made.replaceChildren(h("p", {}, t("setup.tokenMade", {name: token.name, expires: token.expires})),
        h("pre", {class: "card"}, token.token), h("p", {class: "warning"}, t("setup.tokenOnce")));
    } catch (error) {
      report(status, error);
    }
  }

  root.replaceChildren(
    h("h1", {}, t("setup.title")),
    h("section", {}, h("h2", {}, t("setup.data")), h("p", {}, t("setup.dataText", {ledger: state.ledger, config}))),
    h("section", {}, h("h2", {}, t("setup.who")), h("p", {}, t("setup.you", {operator: state.operator})),
      h("p", {class: "muted"}, t("setup.rename", {config}))),
    h("section", {}, h("h2", {}, t("setup.connectors")),
      h("table", {}, h("tbody", {}, ...state.connectors.map((/** @type {any} */ c) => h("tr", {},
        h("td", {}, `${c.available ? "●" : "○"} ${c.id}`), h("td", {}, c.state),
        h("td", {class: "muted"}, c.detail), h("td", {class: "muted"}, keyText(c)))))),
      h("p", {}, h("a", {href: "/connectors", "data-route": ""}, t("setup.openConnectors")))),
    h("section", {}, h("h2", {}, t("setup.bridge")), h("p", {}, t("setup.bridgeText")),
      h("form", {onsubmit: createToken}, h("label", {}, t("setup.tokenName"), " ", name), " ",
        h("button", {type: "submit"}, t("setup.createToken"))), status, made),
    h("section", {}, h("h2", {}, t("setup.done")),
      h("p", {}, h("a", {href: "/?sample", "data-route": ""}, t("setup.sample")))));
}

/** Where a connector's credentials come from. @param {any} c */
function keyText(c) {
  if (c.access !== "api") return t("setup.ownLogin");
  if (c.secret_env) return t("setup.keyFrom", {name: c.secret_env});
  return c.key_variables.length ? t("setup.keyFound", {names: c.key_variables.join(", ")}) : t("setup.keyMissing");
}
