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
