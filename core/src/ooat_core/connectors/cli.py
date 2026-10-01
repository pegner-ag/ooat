"""Running a vendor CLI as a connector backend (vendor-neutral helper for subscription_cli connectors).

The prompt goes through stdin (not visible in process lists, no command-line length limit), the process runs in an
empty temporary directory (no project files or instructions are picked up) with an allow-listed environment (no
secrets), and failures become ConnectorErrors.
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

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


def run_cli(args: list[str], stdin: str, timeout_s: float) -> CliResult:
    """Run args[0] with stdin; UNAVAILABLE if it is not installed, TIMEOUT if it runs past timeout_s."""
    executable = find_executable(args[0])
    if executable is None:
        raise ConnectorError("UNAVAILABLE", f"{args[0]} is not installed or not on PATH")
    with tempfile.TemporaryDirectory(prefix="ooat-cli-") as workdir:
        try:
            completed = subprocess.run([executable, *args[1:]], input=stdin, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=timeout_s, cwd=workdir,
                                       env=child_environment())
        except subprocess.TimeoutExpired:
            raise ConnectorError("TIMEOUT", f"{args[0]} did not finish within {timeout_s:g} s") from None
        except OSError as error:
            raise ConnectorError("UNAVAILABLE", f"{args[0]} could not be started: {error}") from None
    return CliResult(completed.returncode, completed.stdout, completed.stderr)
