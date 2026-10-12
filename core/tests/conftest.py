"""Every test runs with OOAT_HOME in a temporary folder: no test reads or writes the real user data folder."""

import pytest


@pytest.fixture(autouse=True)
def ooat_home(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("ooat-home")
    monkeypatch.setenv("OOAT_HOME", str(home))
    return home
