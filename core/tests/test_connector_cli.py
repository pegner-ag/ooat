import sys

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
