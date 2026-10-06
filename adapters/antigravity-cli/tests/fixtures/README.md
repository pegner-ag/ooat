`success.jsonl` and `denied_tool.jsonl` are recorded `agy` runs (agy 1.3.0, 2026-10-06) with
`--input-format stream-json --output-format stream-json --model=gemini-3.8-flash-low --sandbox
--disable-slash-commands -p=` in an empty folder: "Reply with the single word OK." and "Run the shell command
whoami and print its output." (the command was soft-denied). Sanitised: `cwd` is `C:\work`, every
`conversation_id` is zeros, and the `init` tool list is cut to `view_file`.
`mcp_list_empty.txt` and `plugin_list_empty.txt` are the recorded output of `agy mcp list` and `agy plugin list`
with nothing configured.
Files named `*_synthetic.jsonl` are hand-written results in the documented shape; replace them with recordings
when such errors are observed.
