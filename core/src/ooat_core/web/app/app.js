// The web app's entry (design 05 §2, §4): the header, the screen for the path, signing out. Plain ES modules with
// JSDoc types checked by tsc; no build step (ADR 0016).
import { createApi, KEY_STORAGE } from "./api.js";
import { h, report } from "./dom.js";
import { money } from "./format.js";
import { currentLanguage, setLanguage, t } from "./i18n.js";
import { home, storedProject } from "./views/home.js";
import { conversationPage } from "./views/conversation.js";
import { memoryPage } from "./views/memory.js";
import { taskPage } from "./views/task.js";
import { connectors } from "./views/connectors.js";
import { usage } from "./views/usage.js";
import { setup } from "./views/setup.js";

const LANGUAGE_STORAGE = "ooat.language";
const HEADER_REFRESH_MS = 30_000;
const main = /** @type {HTMLElement} */ (document.getElementById("view"));
const top = /** @type {HTMLElement} */ (document.getElementById("top"));

/** @typedef {(root: HTMLElement, ctx: import("./api.js").Context, match: RegExpMatchArray) => Promise<void>} Screen */
/** @type {[RegExp, Screen][]} */
const ROUTES = [
  [/^\/$/, (root, ctx) => home(root, ctx)],
  [/^\/conversations\/(cnv_[A-Za-z0-9]+)$/, (root, ctx, match) => conversationPage(root, ctx, match[1])],
  [/^\/tasks\/([A-Za-z0-9_]+)$/, (root, ctx, match) => taskPage(root, ctx, match[1])],
  [/^\/memory$/, (root, ctx) => {  // the header's Memory: the project last shown on the home page
    const scope = storedProject() ?? "operator";
    history.replaceState(null, "", `/memory/${scope}`);
    return memoryPage(root, ctx, scope);
  }],
  [/^\/memory\/([a-z0-9][a-z0-9_-]*)$/, (root, ctx, match) => memoryPage(root, ctx, match[1])],
  [/^\/usage$/, (root, ctx) => usage(root, ctx)],
  [/^\/connectors$/, (root, ctx) => connectors(root, ctx)],
  [/^\/setup$/, (root, ctx) => setup(root, ctx)],
];
/** @type {[string, () => string][]} */
const NAV = [
  ["/", () => t("nav.inbox")],
  ["/memory", () => t("nav.memory")],
  ["/usage", () => t("nav.usage")],
  ["/connectors", () => t("nav.connectors")],
  ["/setup", () => t("nav.setup")],
];

const api = createApi({fetch: window.fetch.bind(window), storage: localStorage, onSignedOut: signedOut});
/** @type {AbortController | null} */
let screen = null;
let timer = 0;

function route() {
  screen?.abort();
  screen = new AbortController();
  const ctx = {api, navigate, signal: screen.signal};
  document.documentElement.lang = currentLanguage();
  main.replaceChildren();
  drawTop().catch(() => {});  // the header is a convenience; a failed refresh keeps the last one
  for (const [pattern, show] of ROUTES) {
    const match = location.pathname.match(pattern);
    if (match) {
      show(main, ctx, match).catch((error) => report(main, error));
      return;
    }
  }
  main.append(h("p", {class: "error"}, t("app.notFound")));
}

/** @param {string} path */
function navigate(path) {
  history.pushState(null, "", path);
  route();
}

async function drawTop() {
  const [me, day, week, status] = await Promise.all([api.json("/me"), api.json("/stats?period=1d"),
    api.json("/stats?period=7d"), api.json("/status")]);
  const spent = (/** @type {any} */ stats) => money(stats.spend.metered_usd + stats.spend.shadow_usd);
  top.replaceChildren(
    h("nav", {}, ...NAV.map(([path, label]) => h("a", {href: path, "data-route": ""}, label()))),
    h("span", {class: "muted"}, t("top.spend", {day: spent(day), week: spent(week)}), " · ",
      status.runner.state === "running" ? t("top.busy") : t("top.idle")),
    h("span", {}, me.operator, " · ",
      h("button", {type: "button", class: "link", onclick: switchLanguage}, currentLanguage() === "cs" ? "EN" : "CS"),
      " · ", h("button", {type: "button", class: "link", onclick: signOut}, t("top.signOut"))));
}

function switchLanguage() {
  const next = setLanguage(currentLanguage() === "cs" ? "en" : "cs");
  localStorage.setItem(LANGUAGE_STORAGE, next);
  route();
}

async function signOut() {
  try {
    await api.json("/logout", {method: "POST", body: {}});
  } finally {
    localStorage.removeItem(KEY_STORAGE);
    signedOut();
  }
}

function signedOut() {
  screen?.abort();
  clearInterval(timer);
  top.replaceChildren();
  main.replaceChildren(h("h1", {}, "OOAT"), h("p", {}, t("app.signedOut")));
}

document.addEventListener("click", (event) => {  // in-app links change the screen without a reload
  const link = event.target instanceof Element ? event.target.closest("a[data-route]") : null;
  if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(link.getAttribute("href") ?? "/");
});
window.addEventListener("popstate", route);

setLanguage(localStorage.getItem(LANGUAGE_STORAGE) ?? navigator.language);
if (localStorage.getItem(KEY_STORAGE)) {
  route();
  timer = window.setInterval(() => drawTop().catch(() => {}), HEADER_REFRESH_MS);
} else {
  signedOut();
}
