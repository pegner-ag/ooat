import json
import os
import sys
import time

import pytest
from connector_fakes import FakeConnector

from ooat_core.connectors import ConnectorError, cli
from ooat_core.connectors.conformance import check_connector


def python(code):
    # UTF-8 mode: the vendor CLIs (Node, Rust) read stdin as UTF-8; a Windows Python child would use the locale.
    return [sys.executable, "-X", "utf8", "-c", code]


def test_stdin_reaches_the_process_and_stdout_comes_back():
    result = cli.run_cli(python("import sys; print(sys.stdin.read().upper())"), "dobrý den", 30)
    assert result.returncode == 0 and result.stdout.strip() == "DOBRÝ DEN"


def test_process_runs_in_an_empty_directory():
    result = cli.run_cli(python("import os; print(len(os.listdir('.')))"), "", 30)
    assert result.stdout.strip() == "0"


def test_missing_executable_is_unavailable():
    with pytest.raises(ConnectorError) as info:
        cli.run_cli(["ooat-no-such-cli"], "", 30)
    assert info.value.code == "UNAVAILABLE"


def test_slow_process_times_out():
    with pytest.raises(ConnectorError) as info:
        cli.run_cli(python("import time; time.sleep(5)"), "", 0.5)
    assert info.value.code == "TIMEOUT"


def test_conformance_accepts_the_fake_connector():
    check_connector(FakeConnector())


def test_conformance_rejects_an_invalid_manifest():
    connector = FakeConnector()
    del connector.manifest["jurisdiction"]
    with pytest.raises(Exception):
        check_connector(connector)



def test_child_process_never_sees_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("OOAT_SOMETHING_TOKEN", "t0ken")
    code = "import os; print(sorted(k for k in os.environ if 'API_KEY' in k or 'TOKEN' in k)); print('PATH' in os.environ)"
    lines = cli.run_cli(python(code), "", 30).stdout.splitlines()
    assert lines == ["[]", "True"]


ECHO = """
import json, os, sys, time
if sys.argv[1:] == ["sleep"]:
    time.sleep(8)
files = {name: open(name, encoding="utf-8").read() for name in sorted(os.listdir("."))}
print(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read(), "files": files}))
"""


@pytest.fixture
def shim(tmp_path):
    """A .cmd shim like the ones npm installs for claude and codex: cmd.exe re-parses its command line."""
    (tmp_path / "echo_args.py").write_text(ECHO, encoding="utf-8")
    path = tmp_path / "fakecli.cmd"
    path.write_text(f'@"{sys.executable}" -X utf8 "%~dp0echo_args.py" %*\r\n', encoding="ascii")
    return str(path)


windows_only = pytest.mark.skipif(os.name != "nt", reason=".cmd shims exist only on Windows")


@windows_only
@pytest.mark.parametrize("argument", ['a" & echo INJECTED & rem "', "%PATH%", "x|y", "line\nbreak", "a^b", "!x!"])
def test_shim_refuses_arguments_cmd_would_interpret(shim, argument):
    with pytest.raises(ConnectorError) as info:
        cli.run_cli([shim, "--system", argument], "", 30)
    assert info.value.code == "UNAVAILABLE" and "cmd.exe" in info.value.message


@windows_only
def test_caller_text_travels_in_files_and_stdin_through_a_shim(shim):
    text = 'quote " & %PATH% ^ ! | < > dobrý den'
    result = cli.run_cli([shim, "--system-file", "system.txt", "--tools", ""], "Ahoj, světe", 30,
                         files={"system.txt": text})
    data = json.loads(result.stdout)
    assert data["argv"] == ["--system-file", "system.txt", "--tools", ""]
    assert data["stdin"] == "Ahoj, světe" and data["files"] == {"system.txt": text}


@windows_only
def test_timeout_kills_the_whole_process_tree_behind_a_shim(shim):
    started = time.monotonic()
    with pytest.raises(ConnectorError) as info:
        cli.run_cli([shim, "sleep"], "", 1)
    assert info.value.code == "TIMEOUT" and time.monotonic() - started < 5


def test_file_names_must_stay_inside_the_working_directory():
    with pytest.raises(ValueError):
        cli.run_cli(python("print(1)"), "", 30, files={"../escape.txt": "x"})
