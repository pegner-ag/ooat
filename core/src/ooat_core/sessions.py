"""Web sessions of `ooat serve` (design 05 §6).

A login code is a one-time secret printed in the terminal as a link; it sits in the URL fragment, so it never
reaches a server log, and the page posts it. `ooat serve` and `ooat login` write it as a file named by the code's
SHA-256 into the login folder beside the ledger: whoever can write there holds the terminal, the same trust as the
CLI's `--operator`. A code is valid 5 minutes and used once. The server turns it into a session: an HttpOnly,
SameSite=Strict cookie valid 12 hours, plus a CSRF token for unsafe methods. Sessions live in the server's memory,
so a restart signs everyone out.
"""

import hashlib
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .connector_admin import checked_operator

LOGIN_TTL = timedelta(minutes=5)
SESSION_TTL = timedelta(hours=12)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def login_folder(ledger_url: str) -> Path | None:
    """`ooat-login` beside a file ledger; None for an in-memory ledger (nothing can log in to it)."""
    location = ledger_url.removeprefix("sqlite:///")
    if location == ledger_url or location == ":memory:":
        return None
    return Path(location).parent / "ooat-login"


def issue_login_code(folder: Path, operator: str, now: datetime) -> str:
    """A fresh one-time code for the operator; only its hash is written, with its expiry."""
    operator = checked_operator(operator)
    # Only its owner may read or add codes. On Windows the mode is ignored: the folder lies beside the ledger in the
    # operator's profile and inherits that folder's ACL, which OOAT does not change.
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder.chmod(0o700)  # also when it existed with a wider mode
    for old in folder.glob("*.json"):  # codes nobody used
        try:
            if _utc(json.loads(old.read_text(encoding="utf-8"))["expires"]) <= now:
                old.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            continue
    code = secrets.token_urlsafe(32)
    (folder / f"{_digest(code)}.json").write_text(json.dumps({
        "operator": operator, "expires": (now + LOGIN_TTL).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    return code


def redeem_login_code(folder: Path, code: str, now: datetime) -> str | None:
    """The operator of a valid code, which is then used up; None for an unknown, used or expired code."""
    if not code or len(code) > 128:
        return None
    path = folder / f"{_digest(code)}.json"
    claimed = path.with_suffix(".used")
    try:
        path.replace(claimed)  # atomic: of two redeemers only one gets the file
    except OSError:
        return None
    try:
        data = json.loads(claimed.read_text(encoding="utf-8"))
    finally:
        claimed.unlink(missing_ok=True)
    if _utc(data["expires"]) <= now:
        return None
    try:  # the file is only as trusted as the folder: a reserved or malformed name signs nobody in
        return checked_operator(data["operator"])
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class Session:
    operator: str
    csrf: str
    expires: datetime


class Sessions:
    """Open web sessions, by the SHA-256 of their cookie value."""

    def __init__(self):
        self._open: dict[str, Session] = {}
        self._lock = threading.Lock()

    def open(self, operator: str, now: datetime) -> tuple[str, Session]:
        cookie, session = secrets.token_urlsafe(32), Session(operator, secrets.token_urlsafe(32), now + SESSION_TTL)
        with self._lock:
            self._open = {k: s for k, s in self._open.items() if s.expires > now}
            self._open[_digest(cookie)] = session
        return cookie, session

    def get(self, cookie: str, now: datetime) -> Session | None:
        with self._lock:
            session = self._open.get(_digest(cookie))
        return session if session is not None and session.expires > now else None

    def close(self, cookie: str) -> None:
        with self._lock:
            self._open.pop(_digest(cookie), None)
