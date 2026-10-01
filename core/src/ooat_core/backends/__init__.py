"""Storage backends for the ledger. A backend knows its database dialect; Ledger knows the spec.

Every backend implements the same small surface and must pass core/tests/test_ledger.py.
"""

from typing import Protocol


class LedgerIntegrityError(Exception):
    """A write would duplicate or orphan a ledger row. Backends translate their driver's integrity errors."""


class LedgerBackend(Protocol):
    def insert(self, event_row: dict, artifact_rows: list[dict]) -> None:
        """Insert one event row and its artifact rows in a single transaction.

        Raises LedgerIntegrityError, writing nothing, on a duplicate id or an artifact without its event.
        """

    def select_events(self, task: str | None, types: list[str]) -> list[dict]:
        """Event rows in append order (ascending seq), optionally filtered."""

    def select_artifact(self, artifact_id: str, version: int) -> dict | None: ...

    def max_artifact_version(self, artifact_id: str) -> int:
        """Highest stored version of an artifact, 0 if none."""

    def close(self) -> None: ...


def open_backend(url: str) -> LedgerBackend:
    """sqlite:///<path> or sqlite:///:memory:. PostgreSQL and SQL Server are planned (ADR 0008)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ValueError(f"not a ledger URL: {url}")
    if scheme == "sqlite":
        from .sqlite import SqliteBackend

        path = rest.removeprefix("/")
        if not path:  # sqlite3 would silently open a throwaway database
            raise ValueError("a sqlite ledger URL needs a path: sqlite:///<file> or sqlite:///:memory:")
        return SqliteBackend(path)
    if scheme in ("postgresql", "mssql"):
        raise NotImplementedError(f"the {scheme} ledger backend is not implemented yet (ADR 0008)")
    raise ValueError(f"unknown ledger backend: {scheme}")
