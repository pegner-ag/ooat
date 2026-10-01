"""Running a vendor CLI as a connector backend (vendor-neutral helper for subscription_cli connectors).

Rules every CLI connector inherits:
- Caller text (prompts, system text) never travels in argv: the prompt goes through stdin, longer texts through
  files written into the working directory. On Windows, npm installs CLIs as .cmd shims, and cmd.exe re-parses the
  command line: quotes, &, |, %VAR% and similar in an argument would run commands or expand variables.
- Arguments that cmd.exe would interpret are refused when the executable is a .cmd/.bat shim.
- The process runs in an empty temporary directory with an allow-listed environment (no secrets).
- On timeout the whole process tree is killed: killing only cmd.exe would leave the real CLI running.
"""

import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import PurePath

from . import ConnectorError

# Variables a CLI needs to find itself, its own login and the network. Everything else, notably API keys and any
# secret_env the gateway knows, stays out of the child: secrets reach connectors only through their SecretSource,
# and a CLI that saw ANTHROPIC_API_KEY would bill the API instead of the subscription.
_ALLOWED = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "USERNAME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TERM", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS",
    "CODEX_HOME", "CLAUDE_CONFIG_DIR",
})
_ALLOWED_PREFIXES = ("LC_", "XDG_")
_CMD_SPECIAL = frozenset('"&|<>^%!\r\n')


def child_environment(environ=None) -> dict[str, str]:
    environ = os.environ if environ is None else environ
    return {name: value for name, value in environ.items()
            if name.upper() in _ALLOWED or name.upper().startswith(_ALLOWED_PREFIXES)}


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str


def find_executable(name: str) -> str | None:
    return shutil.which(name)


def _check_shim_arguments(executable: str, args: list[str]) -> None:
    if not executable.lower().endswith((".cmd", ".bat")):
        return
    for argument in args:
        if _CMD_SPECIAL & set(argument):
            raise ConnectorError("UNAVAILABLE", "refusing an argument that cmd.exe would interpret; "
                                                "pass caller text through stdin or a file")


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_cli(args: list[str], stdin: str, timeout_s: float, files: dict[str, str] | None = None) -> CliResult:
    """Run args[0] with stdin in an empty directory holding `files`; refer to them in args by bare file name.

    UNAVAILABLE if the CLI is not installed or an argument is unsafe for a .cmd shim, TIMEOUT past timeout_s.
    """
    for name in files or {}:
        if PurePath(name).name != name or name in ("", ".", ".."):
            raise ValueError(f"file names must be plain names inside the working directory: {name!r}")
    executable = find_executable(args[0])
    if executable is None:
        raise ConnectorError("UNAVAILABLE", f"{args[0]} is not installed or not on PATH")
    _check_shim_arguments(executable, args[1:])
    # New process group / session, so a timeout can kill the CLI behind a shim, not only the shim.
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    with tempfile.TemporaryDirectory(prefix="ooat-cli-", ignore_cleanup_errors=True) as workdir:
        for name, content in (files or {}).items():
            with open(os.path.join(workdir, name), "w", encoding="utf-8", newline="") as file:
                file.write(content)
        try:
            process = subprocess.Popen([executable, *args[1:]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                       cwd=workdir, env=child_environment(), **group)
        except OSError as error:
            raise ConnectorError("UNAVAILABLE", f"{args[0]} could not be started: {error}") from None
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_tree(process)
            raise ConnectorError("TIMEOUT", f"{args[0]} did not finish within {timeout_s:g} s") from None
    return CliResult(process.returncode, stdout, stderr)
