"""The operator's answer to a HIL request, shared by the CLI and the API (design 05 §6).

Every channel answers through `answer()`: it refuses R3 requests (spec §9 as amended by ADR 0016: no operator
identity is bound to something the operator holds yet), applies a passed deadline first so a late answer never wins,
refuses a request that already has its answer, and records the operator and the channel. The caller runs the task
on (the CLI) or queues it for the runner (the server); this module never runs a task.
"""

from .connector_admin import checked_operator
from .ledger import Ledger, new_event
from .runtime import Runtime, TaskClosed
from .validation import SpecValidationError


class UnknownRequest(ValueError):
    """No HIL_REQUEST with this id."""


class AlreadyAnswered(ValueError):
    """The request has its answer: the operator's, or the default applied after its deadline."""


class R3NeedsBoundIdentity(ValueError):
    """R3 needs a named approver bound to something they hold; a self-declared name or a token is not one."""

    code = "R3_NEEDS_BOUND_IDENTITY"


def open_requests(ledger: Ledger) -> list[dict]:
    """HIL_REQUEST events of open tasks without a HIL_RESPONSE, oldest first."""
    events = ledger.events(types=["HIL_REQUEST", "HIL_RESPONSE", "TASK_CLOSED"])
    answered = {e["body"]["request"] for e in events if e["type"] == "HIL_RESPONSE"}
    closed = {e["task"] for e in events if e["type"] == "TASK_CLOSED"}
    return [e for e in events if e["type"] == "HIL_REQUEST" and e["id"] not in answered and e["task"] not in closed]


def find_request(ledger: Ledger, request_id: str) -> dict | None:
    return next((e for e in ledger.events(types=["HIL_REQUEST"]) if e["id"] == request_id), None)


def answer(ledger: Ledger, runtime: Runtime, request_id: str, *, operator: str, choice: str | None = None,
           text: str | None = None, channel: str | None = None) -> dict:
    """Append the operator's HIL_RESPONSE and return it."""
    operator = checked_operator(operator)
    text = (text or "").strip() or None
    if choice is None and text is None:
        raise ValueError("give a choice, a text or both")
    if choice == "narrow_scope" and text is None:  # it would use up a budget question
        raise ValueError("narrow_scope needs the narrowed scope as text")
    request = find_request(ledger, request_id)
    if request is None:
        raise UnknownRequest(f"no question {request_id}")
    if request["body"].get("risk_class") == "R3":
        raise R3NeedsBoundIdentity("an R3 request needs a named approver bound to something they hold (a passkey "
                                   "or an OS-account check); a typed name or a token is not one (ADR 0016)")
    runtime.expire(request["task"])  # past its deadline the default has applied; a late answer must not win
    events = ledger.events(task=request["task"], types=["HIL_RESPONSE", "TASK_CLOSED"])
    if any(e["type"] == "HIL_RESPONSE" and e["body"]["request"] == request_id for e in events):
        raise AlreadyAnswered(f"{request_id} is already answered (after its deadline the default applies)")
    if any(e["type"] == "TASK_CLOSED" for e in events):
        raise TaskClosed(f"task {request['task']} is closed; its question needs no answer")
    body = {"request": request_id}
    if choice is not None:
        body["choice"] = choice
    if text is not None:
        body["text"] = text
    if channel is not None:
        body["channel"] = channel
    try:
        return ledger.append(new_event("HIL_RESPONSE", task=request["task"], actor={"kind": "hil", "id": operator},
                                       body=body))
    except SpecValidationError as error:  # another writer answered between the check above and the append
        if any("is already answered" in message for message in error.messages):
            raise AlreadyAnswered(f"{request_id} is already answered") from None
        raise
