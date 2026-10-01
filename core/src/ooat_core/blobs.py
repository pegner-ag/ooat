"""Content-addressed storage of artifact bodies on the local filesystem (Solo profile)."""

import hashlib
from pathlib import Path

_HEX = frozenset("0123456789abcdef")


class BlobStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, content: bytes) -> str:
        """Store content once and return its SHA-256 hex digest."""
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".partial")
            partial.write_bytes(content)
            partial.replace(path)  # readers never see a half-written blob
        return digest

    def get(self, digest: str) -> bytes:
        content = self._path(digest).read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError(f"blob {digest} does not match its digest")
        return content

    def _path(self, digest: str) -> Path:
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise ValueError(f"not a SHA-256 hex digest: {digest}")
        return self.root / digest[:2] / digest
