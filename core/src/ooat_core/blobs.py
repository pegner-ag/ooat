"""Content-addressed storage of artifact bodies on the local filesystem (Solo profile)."""

import hashlib
import os
import time
import uuid
from pathlib import Path

_HEX = frozenset("0123456789abcdef")
_READ_ATTEMPTS = 8  # about 1.3 s in total with the backoff below


def _read(path: Path) -> bytes:
    """Read a blob; on Windows a file being replaced by another writer refuses reads for a moment, so retry."""
    for attempt in range(_READ_ATTEMPTS):
        try:
            return path.read_bytes()
        except PermissionError:
            if attempt == _READ_ATTEMPTS - 1:
                raise
            time.sleep(0.01 * 2**attempt)
    raise AssertionError("unreachable")


class BlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, content: bytes) -> str:
        """Store content once and return its SHA-256 hex digest."""
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        if path.exists() and self._intact(path, digest):
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        # One temporary file per writer: concurrent puts of the same content must not share it.
        partial = path.with_name(f"{digest}.{uuid.uuid4().hex}.partial")
        with open(partial, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())  # the ledger may commit a reference right after this returns
        try:
            partial.replace(path)  # readers never see a half-written blob; a damaged blob is replaced
        except PermissionError:
            # Windows refuses to replace a file another writer is replacing or reading at the same moment.
            partial.unlink(missing_ok=True)
            if not (path.exists() and self._intact(path, digest)):
                raise
        return digest

    @staticmethod
    def _intact(path: Path, digest: str) -> bool:
        return hashlib.sha256(_read(path)).hexdigest() == digest

    def get(self, digest: str) -> bytes:
        content = _read(self._path(digest))
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"blob {digest} does not match its digest")
        return content

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise ValueError(f"not a SHA-256 hex digest: {digest}")
        return self.root / digest[:2] / digest
