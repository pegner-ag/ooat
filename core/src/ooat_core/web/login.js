// Posts the one-time code from the link `ooat serve` or `ooat login` printed (design 05 §6). The code is in the URL
// fragment, which the browser never sends to a server, and is removed from the address bar before anything else.
const status = /** @type {HTMLElement} */ (document.getElementById("status"));
const code = new URLSearchParams(location.hash.slice(1)).get("code");
history.replaceState(null, "", location.pathname);

if (!code) {
  status.textContent = "Open the link that `ooat login --operator <name>` printed in your terminal.";
} else {
  const response = await fetch("/api/v1/login", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({code}),
  });
  const body = await response.json();
  status.textContent = response.ok ? `Signed in as ${body.operator}.` : body.error.message;
}
