"""Identifiers <prefix>_<ULID> (spec §2).

ULIDs start with a millisecond timestamp, so identifiers sort by creation time across installations.
"""

import os
import re
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = frozenset({"tsk", "ctr", "agt", "evt", "art"})
_ARTIFACT_REF = re.compile(r"^(art_[0-7][0-9A-HJKMNP-TV-Z]{25})@v([1-9][0-9]*)$")


def ulid(timestamp_ms: int | None = None) -> str:
    """26-character Crockford base32 ULID: 48-bit millisecond timestamp + 80 random bits."""
    ms = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ms < 2**48:
        raise ValueError(f"ULID timestamp out of 48-bit range: {ms}")
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{ulid()}"


def is_artifact_ref(value: str) -> bool:
    return _ARTIFACT_REF.match(value) is not None


def parse_artifact_ref(ref: str) -> tuple[str, int]:
    """Split art_<ulid>@v<n> into (artifact id, version)."""
    match = _ARTIFACT_REF.match(ref)
    if match is None:
        raise ValueError(f"not an artifact reference: {ref}")
    return match.group(1), int(match.group(2))
