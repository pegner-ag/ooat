"""An OS file lock beside the ledger: the process holding it is the one that runs tasks (design 05 §7).

`ooat serve` holds it while it runs; `ooat task run`, and `submit` or `hil answer` when they would run the task,
take it for their run. A process that cannot get it leaves running to the holder, so no task is ever run by two
processes. The OS releases the lock when the process ends, also after a crash.
"""

import os
from pathlib import Path


class RunnerLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        """Take the lock without waiting; False when another process (or another RunnerLock) holds it."""
        if self._file is not None:
            raise RuntimeError("this lock is already held")
        file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self._file = file
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._file.close()
            self._file = None


def for_ledger(ledger_url: str) -> RunnerLock | None:
    """The lock of a file ledger (`<ledger file>.runner.lock`); None for an in-memory ledger."""
    location = ledger_url.removeprefix("sqlite:///")
    if location == ledger_url or location == ":memory:":
        return None
    return RunnerLock(f"{location}.runner.lock")
