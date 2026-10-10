# OOAT — Known Entities & Gotchas

- The original spec file name contained Czech characters in a Unicode form the Read tool could not open on
  this Windows server; keep repository file names ASCII.
- Spec examples (topology multipliers, worked EU examples, targets, effort estimates) are the author's priors,
  not measurements — never hard-code them as facts; they belong in configuration/priors.
- Price per million tokens is deliberately not in the spec; it lives in `routing.json` with a validity date.
- Bash heredocs with non-ASCII JSON failed in this shell; write JSON files with the Write tool instead.
- Schema `$ref`s are relative (`common.schema.json#/$defs/...`) and resolve against `$id`; tests load all
  schemas into a `referencing.Registry`. Keep every `$id` under the same base URI.
- Cross-field rules JSON Schema cannot express (option ids, inheritance narrowing) belong in the linter; list
  them in `spec/README.md`.
- On Windows npm installs `claude` and `codex` as `.cmd` shims: cmd.exe re-parses the command line, so quotes, `&`,
  `|`, `%VAR%` in an argument run commands or expand variables, long arguments hit the command-line limit, and
  killing the shim on timeout leaves the real CLI running. Caller text goes through stdin or files, `run_cli` refuses
  cmd metacharacters for shims and kills the whole process tree.
- The operator's environment on this server holds many real API keys and bot tokens; child processes get only the
  allow-listed variables in `connectors/cli.py`.
- Claude Code headless: `--bare` disables the subscription login; `--system-prompt-file` works although `--help`
  lists it only inside the `--bare` text.
- Jev (TypeSafe System One API): a noul answer has no `confidence` field (use max(p, 1 - p)); a score is a
  fractional position with a `legend`; the request alias `jev-latest` is answered as a version (`jev-1.13.0`),
  so `routing.json` prices both names and decisions record the version. Docs: https://docs.typesafe.ai/llms.txt
- Regexes that scan task text (pii.py) must stay linear: an unbounded `[...]+@` local part backtracked from every
  position, so a 100k-character attachment took minutes. Bound repeats and start tokens with a lookbehind; the
  test `test_a_long_attachment_is_scanned_in_linear_time` guards it.
- Python run from a Bash heredoc: a `\n` inside a Python string in the heredoc ended up as a real newline in the
  written source (unterminated f-strings). Build backslashes with `chr(92)` or write the script with the Write
  tool first.
- Antigravity CLI (`agy`) does not run Gemini CLI's hooks in `~/.gemini/settings.json` (process watch during a
  call, 2026-10-06); it reads `~/.gemini/config/hooks.json`. The operator's Orca hooks live in the old file.
- FastAPI 0.143 includes routers lazily: `app.routes` holds `_IncludedRouter` objects, not the routes. Tests that
  list every endpoint enumerate each router's own `.routes` (`api.login_routes()`, `session_routes()`,
  `endpoints.resource_routes()`).
- The ledger stamps `ts` with the real time while tests fake the runtime's clock. A test that compares event times
  with the clock (runner backoff, stats periods) starts its fake clock at `datetime.now(timezone.utc)`.
- Starlette 1.x's `TestClient` wants `httpx2` (Pydantic's fork, github.com/pydantic/httpx2); plain `httpx` still works but warns. The test client buffers a whole streamed body, so a test that acts while a Server-Sent Events stream is open drives the stream's generator itself (`endpoints._stream`).
- Opening a SQLite connection runs the ledger's DDL, which needs the write lock: a connection opened while another
  writer holds it fails busy too. `SqliteBackend` maps that, like a busy `BEGIN IMMEDIATE`, to `LedgerBusyError`.
- FastAPI runs sync endpoints in a thread pool and iterates a sync streaming generator there too: the API keeps one
  ledger connection per thread (`threading.local`) and reads through `server.runtime()` at every step.
