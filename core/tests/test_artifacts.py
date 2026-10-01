import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from ooat_core.artifacts import ArtifactStore
from ooat_core.blobs import BlobStore
from ooat_core.ids import new_id
from ooat_core.ledger import Ledger, new_event


@pytest.fixture
def ledger():
    led = Ledger.open("sqlite:///:memory:")
    yield led
    led.close()


@pytest.fixture
def store(ledger, tmp_path):
    return ArtifactStore(ledger, BlobStore(tmp_path / "blobs"))


def result(ref):
    return new_event(
        "RESULT", task=new_id("tsk"), contract=new_id("ctr"),
        actor={"kind": "agent", "id": new_id("agt"), "role": "role.general.worker@0.1.0"},
        body={"outcome": "DONE", "artifacts": [ref]}, refs=[ref],
    )


def test_artifact_is_readable_only_after_its_event(ledger, store):
    staged = store.stage("Shrnutí zprávy".encode(), artifact_type="summary", data_class="internal")
    with pytest.raises(KeyError):
        store.read(staged.ref)
    ledger.append(result(staged.ref), [staged])
    assert store.read(staged.ref).decode() == "Shrnutí zprávy"


def test_next_version_of_an_existing_artifact(ledger, store):
    first = store.stage(b"v1", artifact_type="summary", data_class="public")
    ledger.append(result(first.ref), [first])
    artifact_id = first.ref.split("@")[0]
    second = store.stage(b"v2", artifact_type="summary", data_class="public", artifact_id=artifact_id)
    assert second.ref == f"{artifact_id}@v2"


def test_unknown_data_class_is_rejected(store):
    with pytest.raises(ValueError, match="data class"):
        store.stage(b"x", artifact_type="summary", data_class="secret")


def test_identical_content_is_stored_once(tmp_path):
    blobs = BlobStore(tmp_path)
    assert blobs.put(b"same") == blobs.put(b"same")
    assert len([p for p in tmp_path.rglob("*") if p.is_file()]) == 1


def test_tampered_blob_is_detected(tmp_path):
    blobs = BlobStore(tmp_path)
    digest = blobs.put(b"original")
    (tmp_path / digest[:2] / digest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest"):
        blobs.get(digest)


def test_path_traversal_digest_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        BlobStore(tmp_path).get("../" + "a" * 61)


def test_put_repairs_a_damaged_blob(tmp_path):
    blobs = BlobStore(tmp_path)
    digest = blobs.put(b"original")
    (tmp_path / digest[:2] / digest).write_bytes(b"damaged")
    assert blobs.put(b"original") == digest
    assert blobs.get(digest) == b"original"


def test_concurrent_puts_of_the_same_content(tmp_path):
    blobs, content = BlobStore(tmp_path), b"x" * 2_000_000
    with ThreadPoolExecutor(8) as pool:
        digests = list(pool.map(lambda _: blobs.put(content), range(32)))
    assert set(digests) == {hashlib.sha256(content).hexdigest()}
    assert blobs.get(digests[0]) == content
    assert not list(tmp_path.rglob("*.partial"))


def test_transient_sharing_violation_is_retried(tmp_path, monkeypatch):
    """Windows refuses reads for a moment while another writer replaces the same blob."""
    from pathlib import Path as _Path

    blobs = BlobStore(tmp_path)
    digest = blobs.put(b"data")
    real_read = _Path.read_bytes
    failures = {"left": 1}

    def flaky_read(self):
        if failures["left"]:
            failures["left"] -= 1
            raise PermissionError(13, "The process cannot access the file")
        return real_read(self)

    monkeypatch.setattr(_Path, "read_bytes", flaky_read)
    assert blobs.get(digest) == b"data"
    failures["left"] = 1
    assert blobs.put(b"data") == digest
