"""Artifact staging and reading.

A staged artifact becomes visible only when the event that produces it is appended to the ledger,
so no artifact exists without provenance (spec §2).
"""

from .blobs import BlobStore
from .ids import new_id
from .ledger import Ledger, StagedArtifact

DATA_CLASSES = frozenset({"public", "internal", "client_confidential", "personal", "special_category"})


class ArtifactStore:
    def __init__(self, ledger: Ledger, blobs: BlobStore):
        self._ledger = ledger
        self._blobs = blobs

    def stage(
        self,
        content: bytes,
        *,
        artifact_type: str,
        data_class: str,
        untrusted: bool = False,
        artifact_id: str | None = None,
    ) -> StagedArtifact:
        """Store the body and return the staged record; pass artifact_id to create its next version."""
        if data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class: {data_class}")
        artifact_id = artifact_id or new_id("art")
        version = self._ledger.next_artifact_version(artifact_id)
        digest = self._blobs.put(content)
        return StagedArtifact(ref=f"{artifact_id}@v{version}", type=artifact_type, data_class=data_class,
                              untrusted=untrusted, sha256=digest, uri=f"blob:{digest}")

    def read(self, ref: str) -> bytes:
        record = self._ledger.artifact(ref)
        if record is None:
            raise KeyError(f"no appended event produced {ref}")
        return self._blobs.get(record["sha256"])
