import re

import pytest

from ooat_core.ids import new_id, parse_artifact_ref, ulid

ULID = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"


@pytest.mark.parametrize("prefix", ["tsk", "ctr", "agt", "evt", "art", "tok"])
def test_new_id_matches_spec_pattern(prefix):
    assert re.fullmatch(f"{prefix}_{ULID}", new_id(prefix))


def test_new_ids_are_unique():
    assert len({new_id("evt") for _ in range(1000)}) == 1000


def test_ulid_sorts_by_time():
    assert ulid(1_000) < ulid(2_000) < ulid(2**48 - 1)
    assert ulid(0).startswith("0000000000")


def test_unknown_prefix_is_rejected():
    with pytest.raises(ValueError):
        new_id("usr")


def test_parse_artifact_ref():
    art = new_id("art")
    assert parse_artifact_ref(f"{art}@v12") == (art, 12)
    for bad in (art, f"{art}@v0", "art_short@v1"):
        with pytest.raises(ValueError):
            parse_artifact_ref(bad)


@pytest.mark.parametrize("timestamp_ms", [-1, 2**48])
def test_ulid_rejects_timestamps_outside_48_bits(timestamp_ms):
    with pytest.raises(ValueError):
        ulid(timestamp_ms)
