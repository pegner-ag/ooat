"""Operator API tokens for bots and scripts (design 05 §6, ADR 0016).

A token acts as the operator who issued it, within its scopes and its data-class cap. It is 256 random bits, shown
once; the ledger keeps only its SHA-256 (OPERATOR_TOKEN_ISSUED), compared in constant time, and revoking appends
OPERATOR_TOKEN_REVOKED, so who could act for whom is in the audit log. A cap above `internal` is the operator's
responsibility statement (ADR 0012): content of that class may then leave the machine through the token's client.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .connector_admin import checked_operator
from .ids import new_id
from .ledger import Ledger, new_event

SCOPES = ("submit", "read", "answer", "rate", "connectors")
CAPS = ("public", "internal", "client_confidential", "personal")  # special_category never leaves through a token
RESPONSIBLE_CAPS = ("client_confidential", "personal")
DEFAULT_DAYS, MAX_DAYS = 90, 365
PREFIX = "ooat_"  # makes a leaked token recognisable to secret scanners
EVENTS = ["OPERATOR_TOKEN_ISSUED", "OPERATOR_TOKEN_REVOKED"]
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Token:
    id: str
    operator: str
    name: str
    scopes: frozenset[str]
    max_data_class: str
    expires: datetime
    sha256: str
    revoked: bool = False


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def issue(ledger: Ledger, *, operator: str, name: str, scopes: list[str], max_data_class: str = "internal",
          days: int = DEFAULT_DAYS, responsibility: bool = False, now: datetime) -> tuple[str, dict]:
    """Append OPERATOR_TOKEN_ISSUED and return (the token, the event). The token is never stored or logged."""
    operator = checked_operator(operator)
    if not _NAME.match(name):
        raise ValueError("a token name is 1 to 32 lowercase letters, digits, '-' or '_', e.g. telegram")
    scopes = list(dict.fromkeys(scopes))
    unknown = sorted(set(scopes) - set(SCOPES))
    if not scopes or unknown:
        raise ValueError(f"scopes are some of {', '.join(SCOPES)}" + (f"; unknown: {unknown}" if unknown else ""))
    if max_data_class not in CAPS:
        raise ValueError(f"a token's data class is one of {', '.join(CAPS)}; special_category never leaves")
    if max_data_class in RESPONSIBLE_CAPS and not responsibility:
        raise ValueError(f"a token for {max_data_class} data needs your responsibility statement")
    if type(days) is not int or not 1 <= days <= MAX_DAYS:
        raise ValueError(f"a token expires after 1 to {MAX_DAYS} days")
    secret = PREFIX + secrets.token_urlsafe(32)  # 256 bits
    body = {"token": new_id("tok"), "operator": operator, "name": name, "scopes": scopes,
            "max_data_class": max_data_class, "sha256": _digest(secret),
            "expires": (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if max_data_class in RESPONSIBLE_CAPS:
        body["responsibility"] = {"confirmed_on": now.date().isoformat()}
    event = ledger.append(new_event("OPERATOR_TOKEN_ISSUED", task=None, actor={"kind": "hil", "id": operator},
                                    body=body))
    return secret, event


def tokens(events: list[dict]) -> dict[str, Token]:
    """Every issued token by id, with whether it was revoked; the events are OPERATOR_TOKEN_* in ledger order."""
    found = {}
    for event in events:
        body = event["body"]
        if event["type"] == "OPERATOR_TOKEN_ISSUED":
            found[body["token"]] = Token(body["token"], body["operator"], body["name"], frozenset(body["scopes"]),
                                         body["max_data_class"], _utc(body["expires"]), body["sha256"])
        elif event["type"] == "OPERATOR_TOKEN_REVOKED" and body["token"] in found:
            found[body["token"]] = replace(found[body["token"]], revoked=True)
    return found


def revoke(ledger: Ledger, *, operator: str, token_id: str, reason: str) -> dict:
    """OPERATOR_TOKEN_REVOKED. Any operator may revoke any token, so a leaked token can be stopped at once by whoever
    notices; operator names are self-declared, so an issuer-only rule would protect little. The event records who
    revoked it (`operator`, also the actor) and the required reason."""
    operator, reason = checked_operator(operator), reason.strip()
    if not reason:
        raise ValueError("a reason is required")
    known = tokens(ledger.events(types=EVENTS)).get(token_id)
    if known is None:
        raise ValueError(f"no token {token_id} (see `ooat tokens list`)")
    if known.revoked:
        raise ValueError(f"{token_id} is already revoked")
    return ledger.append(new_event("OPERATOR_TOKEN_REVOKED", task=None, actor={"kind": "hil", "id": operator},
                                   body={"token": token_id, "operator": operator, "reason": reason}))


def authenticate(events: list[dict], presented: str, now: datetime) -> Token | None:
    """The active token whose hash matches, or None. Every stored hash is compared in constant time."""
    if not presented.startswith(PREFIX) or len(presented) > 128:
        return None
    digest, match = _digest(presented), None
    for token in tokens(events).values():
        if hmac.compare_digest(token.sha256, digest):
            match = token
    if match is None or match.revoked or match.expires <= now:
        return None
    return match
