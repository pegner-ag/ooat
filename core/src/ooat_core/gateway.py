"""Provider gateway: the only path from OOAT to a model (spec §6, §9; gateway design §6–§8).

Every call is estimated, routed (data class, acknowledgement, automation, quota, price), budget-checked, metered
and returned with a cost record for the caller's event. Connector state is read from the ledger (ADR 0010).
Model requests go to model connectors (`call`), typed decisions to decision connectors (`decide`, ADR 0011).
Before routing, a local pre-scan raises the data class of any request that carries personal data (pii.py).
"""

import dataclasses
import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Config
from .connector_admin import (RESPONSIBLE_CLASSES, acknowledgements, blocked_by_policy, may_extend, provider_trains,
                              responsibility_in_force)
from .connectors import (ConnectorError, DecisionAnswer, DecisionRequest, ModelConnector, ModelRequest, ModelResponse,
                         jurisdiction_stale)
from .connectors.registry import Registry
from .decisions import (check_questions, checked_answers, fallback_prompt, merged_answers, parse_fallback,
                        with_reversed_choices)
from .ledger import DATA_CLASSES, Ledger, new_event
from .pii import raised_class
from .routing import Price, RoutingPolicy
from .credentials_env import SecretResolver

ACTOR = {"kind": "system", "id": "ooat-gateway"}
# Already-paid capacity first when estimated costs tie (ADR 0005).
_ACCESS_RANK = {"subscription_cli": 0, "local": 1, "api": 2, "subscription_manual": 3}
_PERSONAL_OR_HIGHER = frozenset({"personal", "special_category"})
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED", "QUOTA_WARNING"]
# When no decision connector can answer, the cheapest text tier answers the same typed questions (spec §6).
FALLBACK_TIER = "economy"
FALLBACK_TIMEOUT_S = 120


class GatewayError(Exception):
    """NOT_PERMITTED, BUDGET, QUOTA_EXHAUSTED, UNAVAILABLE, API_ERROR or TIMEOUT (design §7)."""

    def __init__(self, code: str, message: str, trace: list[str] | None = None, cost: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace = trace or []  # why each connector was excluded
        self.cost = cost  # cost record for the caller's event when a connector was called
        self.fallback_from: GatewayError | None = None  # decide(): the decision tier's failure before this one


@dataclass(frozen=True)
class Estimate:
    connector: str
    model: str
    tokens_in: int
    tokens_out: int
    usd: float
    basis: str  # "prior" until calibration from observed costs exists (F2)


@dataclass(frozen=True)
class GatewayResult:
    response: ModelResponse
    cost: dict
    estimate: Estimate


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, DecisionAnswer]  # one per question asked; reversed twins already folded in
    engine: str  # the connector that answered; thresholds are calibrated per engine and model (ADR 0011)
    model: str  # the model version the provider reported
    cost: dict
    estimate: Estimate
    fallback_from: "GatewayError | None" = None  # why the decision tier could not answer, with its cost


@dataclass(frozen=True)
class _Candidate:
    estimate: Estimate
    connector: ModelConnector
    price: Price


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _normalised_utc(text) -> str | None:
    """An ISO 8601 time with an offset, as UTC "...Z"; None for anything else (connector output is untrusted)."""
    try:
        moment = _utc(text)
    except (TypeError, ValueError, AttributeError):
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(value) -> int | None:
    return value if type(value) is int and 0 <= value < 2**63 else None


class _OwnSecret:
    """Hands a connector its own secret only (defence in depth; the contract is fixed before connectors exist)."""

    def __init__(self, resolver: SecretResolver, connector_id: str):
        self._resolver, self._connector_id = resolver, connector_id

    def get(self, connector_id: str) -> str:
        if connector_id != self._connector_id:
            raise ConnectorError("UNAVAILABLE", f"{self._connector_id} may only read its own secret")
        return self._resolver.get(connector_id)


def _outgoing_text(request: ModelRequest | DecisionRequest) -> str:
    """Everything a connector would send to the provider, for the personal-data pre-scan."""
    if isinstance(request, DecisionRequest):  # raw texts: a JSON escape turns a newline into "\\n" and hides words
        parts = [request.state]
        for question in request.questions.values():
            criteria = question.criteria or {}
            parts += [question.instructions, *(criteria.values() if isinstance(criteria, dict) else criteria)]
        return "\n".join(parts)
    return request.system + "\n" + request.prompt


def _token_estimate(request: ModelRequest | DecisionRequest) -> tuple[int, int]:
    """(tokens in, tokens out) before the call: about 4 characters per token (spec §6 prior)."""
    if isinstance(request, DecisionRequest):
        questions = {key: dataclasses.asdict(question) for key, question in request.questions.items()}
        payload = json.dumps({"state": request.state, "questions": questions}, ensure_ascii=False)
        return math.ceil(len(payload) / 4), 16 * len(request.questions)  # a typed answer is a few tokens
    tokens_out = request.expected_output_tokens or request.max_output_tokens
    return math.ceil(len(request.system + request.prompt) / 4), tokens_out


class Gateway:
    def __init__(self, ledger: Ledger, registry: Registry, routing: RoutingPolicy, config: Config = Config(),
                 secrets: SecretResolver | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._ledger = ledger
        self._registry = registry
        self._routing = routing
        self._config = config
        self._secrets = secrets or SecretResolver(config)
        self._clock = clock

    def estimate(self, request: ModelRequest) -> Estimate:
        """Expected cost of the request on the connector routing would pick; no provider call."""
        return self._route(request).estimate

    def call(self, request: ModelRequest) -> GatewayResult:
        if request.task is None:
            raise ValueError("every gateway call belongs to a task")
        candidate = self._route(request)
        self._check_budget(request, candidate.estimate)
        response = self._invoke(request, candidate, "complete")
        cost = self._cost(request, candidate, response)
        self._warn_budget(request, cost["usd"])
        return GatewayResult(response, cost, candidate.estimate)

    def estimate_decision(self, request: DecisionRequest) -> Estimate:
        """Expected cost of the decision on the engine decide() would use; no provider call."""
        check_questions(request.questions)
        expanded = self._expanded(request)
        try:
            return self._route(expanded, kind="decision").estimate
        except GatewayError:
            return self.estimate(self._fallback_request(expanded))

    def decide(self, request: DecisionRequest) -> DecisionResult:
        """Answer typed questions on a decision connector, or on the economy text tier when none can answer.

        Every choice is also asked with its options reversed, and the answers are checked against the questions
        before anyone may act on them (spec §6, ADR 0011). A budget refusal never falls back: the text tier costs
        more. If the text tier cannot be tried either, the decision tier's error is raised; if it ran and failed,
        its own error is raised with `fallback_from` set, so the caller can record both costs.
        """
        if request.task is None:
            raise ValueError("every gateway call belongs to a task")
        check_questions(request.questions)
        expanded = self._expanded(request)
        try:
            return self._decide_on_connector(request, expanded)
        except GatewayError as error:
            if error.code == "BUDGET":
                raise
            failure = error
        try:
            result = self._decide_on_text_model(request, expanded)
        except GatewayError as error:
            if error.code == "BUDGET":  # the caller must see the budget, not the decision tier's failure
                error.fallback_from = failure
                raise
            if error.cost is None:  # nothing ran on the text tier
                raise GatewayError(failure.code, f"{failure.message}; fallback: {error.message}",
                                   failure.trace + error.trace, failure.cost) from None
            error.fallback_from = failure
            raise
        return dataclasses.replace(result, fallback_from=failure)

    def _decide_on_connector(self, request: DecisionRequest, expanded: DecisionRequest) -> DecisionResult:
        candidate = self._route(expanded, kind="decision")
        self._check_budget(expanded, candidate.estimate)
        response = self._invoke(expanded, candidate, "decide")
        cost = self._cost(expanded, candidate, response)
        try:
            answers = checked_answers(expanded.questions, response.answers)
        except ValueError as error:  # the provider answered, so the call is charged
            raise GatewayError("API_ERROR", self._secrets.redact(f"unusable answer: {error}"), cost=cost) from None
        except Exception as error:  # an answer object of the wrong shape must still be typed and charged
            raise GatewayError("API_ERROR", self._secrets.redact(f"unusable answer: {type(error).__name__}"),
                               cost=cost) from None
        self._require_model(response.model, cost)
        self._warn_budget(request, cost["usd"])
        return DecisionResult(merged_answers(request.questions, answers), candidate.connector.manifest["id"],
                              response.model, cost, candidate.estimate)

    def _decide_on_text_model(self, request: DecisionRequest, expanded: DecisionRequest) -> DecisionResult:
        result = self.call(self._fallback_request(expanded))
        try:
            answers = checked_answers(expanded.questions, parse_fallback(result.response.text, expanded.questions))
        except ValueError as error:  # the model answered, so the call is charged
            raise GatewayError("API_ERROR", self._secrets.redact(f"unusable fallback answer: {error}"),
                               cost=result.cost) from None
        except Exception as error:  # an answer object of the wrong shape must still be typed and charged
            raise GatewayError("API_ERROR", self._secrets.redact(f"unusable fallback answer: {type(error).__name__}"),
                               cost=result.cost) from None
        self._require_model(result.response.model, result.cost)
        return DecisionResult(merged_answers(request.questions, answers), result.cost["adapter"],
                              result.response.model, result.cost, result.estimate)

    @staticmethod
    def _require_model(model: str, cost: dict) -> None:
        """Thresholds are keyed by engine and model version (ADR 0011): an unnamed version cannot be acted on."""
        if not model.strip():
            raise GatewayError("API_ERROR", "the reply does not name the model version that answered", cost=cost)

    @staticmethod
    def _fallback_request(expanded: DecisionRequest) -> ModelRequest:
        system, prompt = fallback_prompt(expanded)
        options = sum(len(q.criteria) if q.type != "noul" else 1 for q in expanded.questions.values())
        return ModelRequest(tier=FALLBACK_TIER, prompt=prompt, system=system, data_class=expanded.data_class,
                            max_output_tokens=200 + 20 * options, task=expanded.task, contract=expanded.contract,
                            timeout_s=max(expanded.timeout_s, FALLBACK_TIMEOUT_S))

    @staticmethod
    def _expanded(request: DecisionRequest) -> DecisionRequest:
        return dataclasses.replace(request, questions=with_reversed_choices(request.questions))

    def _invoke(self, request, candidate: "_Candidate", method: str):
        """Run the connector with the routed model; every failure becomes a typed, redacted GatewayError."""
        connector_id = candidate.connector.manifest["id"]
        try:
            routed = dataclasses.replace(request, model=candidate.estimate.model)
            response = getattr(candidate.connector, method)(routed, _OwnSecret(self._secrets, connector_id))
        except ConnectorError as error:
            if error.code == "QUOTA_EXHAUSTED":
                self._cool_down(request, candidate.connector, error.resets_at)
            ran = error.code in ("API_ERROR", "TIMEOUT")  # the provider may have consumed tokens
            raise GatewayError(error.code, self._secrets.redact(error.message),
                               cost=self._failure_cost(request, candidate, ran)) from None
        except Exception as error:  # a connector bug must surface as a typed, redacted failure
            raise GatewayError("API_ERROR", self._secrets.redact(f"{connector_id}: {type(error).__name__}: {error}"),
                               cost=self._failure_cost(request, candidate, True)) from None
        return self._sanitised(response)

    # Routing ------------------------------------------------------------------------------------------------

    def _route(self, request: ModelRequest | DecisionRequest, kind: str = "model") -> _Candidate:
        if request.data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class: {request.data_class}")
        candidates, trace, cooling = [], [], set()
        # The pre-scan runs before any connector is chosen, so a declared class can never send personal data
        # where the operator did not allow it. It only raises the class (design 04 §4, ADR 0011).
        effective = raised_class(request.data_class, _outgoing_text(request))
        if effective != request.data_class:
            trace.append(f"pre-scan found personal data: {request.data_class} raised to {effective}")
            request = dataclasses.replace(request, data_class=effective)
        events = self._ledger.events(types=_STATE_EVENTS)
        acknowledged, cooldowns = acknowledgements(events), self._cooldowns(events)
        for connector_id in self._registry.ids(kind):
            connector = self._registry.get(connector_id)
            reason = self._exclusion(connector, request, acknowledged.get(connector_id), cooldowns)
            if reason is None:
                reason, candidate = self._priced(connector, request)
                if candidate is not None:
                    candidates.append(candidate)
                    continue
            if connector_id in cooldowns and reason.startswith("quota"):
                cooling.add(connector_id)
            trace.append(f"{connector_id}: {reason}")
        pin = self._config.pins.get(request.tier)
        if pin is not None:
            pinned = [c for c in candidates if c.connector.manifest["id"] == pin]
            if not pinned:
                code = "QUOTA_EXHAUSTED" if pin in cooling else "NOT_PERMITTED"
                raise GatewayError(code, f"pinned connector {pin} cannot serve this request", trace)
            return pinned[0]
        if not candidates:
            code = "QUOTA_EXHAUSTED" if cooling else "NOT_PERMITTED"
            raise GatewayError(code, f"no connector can serve tier {request.tier} for {request.data_class}", trace)
        return min(candidates, key=lambda c: (c.estimate.usd, _ACCESS_RANK[c.connector.manifest["access"]],
                                              c.connector.manifest["id"]))

    def _exclusion(self, connector, request, acknowledgement, cooldowns) -> str | None:
        manifest, connector_id, data_class = connector.manifest, connector.manifest["id"], request.data_class
        if request.tier not in manifest["tiers"] and request.tier not in self._models(connector_id):
            return f"does not serve tier {request.tier}"
        if not self._routing.allows(request.tier, connector_id):
            return f"not listed for tier {request.tier} in routing.json"
        if manifest["access"] == "subscription_manual":
            return "manual relay needs a human in the loop (sub-project 05)"
        if acknowledgement is None:
            return "not acknowledged by the operator (or disabled)"
        blocked = blocked_by_policy(manifest, self._config)
        if blocked:
            return blocked
        if data_class == "special_category":
            return "special_category needs verified redaction, not available yet"
        policy = self._routing.data_class_policy[data_class]
        if not policy["allowed"]:
            return f"{data_class} is not allowed by the routing policy"
        # The operator's responsibility (ADR 0012) stands in for what a manifest cannot state: the processing
        # agreement, the region under it, and that training is off for this account.
        responsibility = responsibility_in_force(acknowledgement, self._clock().date())
        responsible = responsibility is not None and data_class in RESPONSIBLE_CLASSES
        if data_class not in manifest["data_policy"]["allowed_data_classes"]:
            if not responsible:
                return f"{data_class} is not allowed by the manifest"
            if not may_extend(manifest, responsibility):  # a hard rule, whatever the routing policy says
                return (f"{data_class} cannot go beyond the manifest: the provider trains on inputs or training "
                        "is not off")
        if data_class not in acknowledgement["allowed_data_classes"]:
            return f"{data_class} was not acknowledged by the operator"
        trains = provider_trains(manifest)
        no_training = trains is False or (responsible and trains is None and responsibility.get("no_training") is True)
        if policy.get("require_no_training") and not no_training:
            return f"{data_class} requires a connector that does not train on inputs"
        regions = manifest["jurisdiction"]["processing_regions"] or (
            responsibility.get("processing_regions") if responsible else None)
        if policy.get("require_known_region") and not regions:
            return f"{data_class} requires a known processing region"
        if policy.get("require_verified_redaction"):
            return f"{data_class} requires verified redaction, not available yet"
        if policy.get("require_contract") and not responsible:  # nothing else can vouch for an agreement
            return f"{data_class} requires a provider contract: take responsibility for it when enabling the connector"
        allowed_regions = self._config.personal_data_regions
        if data_class in _PERSONAL_OR_HIGHER and allowed_regions is not None and (not regions or not all(
                any(r == a or r.startswith(f"{a}-") for a in allowed_regions) for r in regions)):
            return (f"your policy allows personal data only in {sorted(allowed_regions)}; "
                    f"this connector processes in {regions or 'unknown regions'}")
        # The responsibility holds "until the facts on the card change", so client data checks them too.
        if (data_class in _PERSONAL_OR_HIGHER or responsible) and jurisdiction_stale(
                manifest, acknowledgement, self._clock().date(), responsible):
            return f"jurisdiction changed or not verified within 12 months; acknowledge again for {data_class} data"
        if manifest["automation_permitted"] == "not_permitted":
            return "provider terms do not permit automated use"
        if acknowledgement.get("automation_confirmed") is not True:  # absent in acknowledgements before ADR 0010
            return "automated use not confirmed by the operator; acknowledge again"
        if connector_id in cooldowns:
            return f"quota cool-down until {cooldowns[connector_id]}"
        return None

    def _models(self, connector_id: str) -> dict:
        return self._config.connectors.get(connector_id, {}).get("models", {})

    def _priced(self, connector, request) -> tuple[str | None, _Candidate | None]:
        connector_id = connector.manifest["id"]
        model = self._models(connector_id).get(request.tier) or connector.manifest["tiers"].get(request.tier)
        if model is None:
            return f"no model configured for tier {request.tier}", None
        # Only non-API connectors may borrow another adapter's price: the spec §6 prior for subscriptions.
        price = self._routing.price(connector_id, model, self._clock().date(),
                                    fallback=connector.manifest["access"] != "api")
        if price is None:
            return f"no price for model {model} in routing.json", None
        tokens_in, tokens_out = _token_estimate(request)
        estimate = Estimate(connector_id, model, tokens_in, tokens_out, price.usd(tokens_in, 0, tokens_out), "prior")
        return None, _Candidate(estimate, connector, price)

    def _cooldowns(self, events: list[dict]) -> dict[str, str]:
        latest = {e["body"]["adapter"]: e["body"] for e in events if e["type"] == "QUOTA_WARNING"}
        now = self._clock()
        return {connector_id: body["window_resets_at"] for connector_id, body in latest.items()
                if body["utilisation"] >= 1 and "window_resets_at" in body and _utc(body["window_resets_at"]) > now}

    # Budget, quota, metering -------------------------------------------------------------------------------

    def _contract_budget(self, request: ModelRequest) -> tuple[float, float] | None:
        """(limit, spent) for the request's contract, from CONTRACT_ISSUED and the costs of its events."""
        if request.contract is None:
            return None
        events = self._ledger.events(task=request.task)
        issued = [e for e in events if e["type"] == "CONTRACT_ISSUED" and e.get("contract") == request.contract]
        if not issued:
            raise GatewayError("NOT_PERMITTED", f"contract {request.contract} was not issued in task {request.task}")
        spent = sum(e["cost"].get("usd", 0) for e in events if e.get("contract") == request.contract and "cost" in e)
        return issued[-1]["body"]["contract"]["budget"]["max_usd"], spent

    def _check_budget(self, request: ModelRequest, estimate: Estimate) -> None:
        budget = self._contract_budget(request)
        if budget is not None and estimate.usd > budget[0] - budget[1]:
            limit, spent = budget
            raise GatewayError("BUDGET", f"estimated {estimate.usd:.4f} USD exceeds the remaining "
                                         f"{limit - spent:.4f} USD of contract {request.contract}")

    def _warn_budget(self, request: ModelRequest, usd: float) -> None:
        budget = self._contract_budget(request)
        if budget is None:
            return
        limit, spent = budget
        warned = any(e.get("contract") == request.contract
                     for e in self._ledger.events(task=request.task, types=["BUDGET_WARNING"]))
        if not warned and spent + usd >= 0.8 * limit:
            self._ledger.append(new_event("BUDGET_WARNING", task=request.task, contract=request.contract, actor=ACTOR,
                                          body={"level": "contract", "used_usd": spent + usd, "limit_usd": limit}))

    def _cool_down(self, request: ModelRequest, connector: ModelConnector, resets_at: str | None) -> None:
        resets_at = _normalised_utc(resets_at)
        if resets_at is None:
            hours = (connector.manifest.get("plan") or {}).get("quota_window_hours") or 1
            resets_at = (self._clock() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._ledger.append(new_event("QUOTA_WARNING", task=request.task, actor=ACTOR, body={
            "adapter": connector.manifest["id"], "utilisation": 1.0, "window_resets_at": resets_at}))

    def _sanitised(self, response):
        """Connector output is untrusted: redact secrets, drop usage numbers the ledger could not store.
        Decision answers are checked separately against their questions (decisions.checked_answers)."""
        quota = response.quota_units
        if not (type(quota) in (int, float) and math.isfinite(quota) and quota >= 0):
            quota = None
        tokens = [_count(response.tokens_in), _count(response.tokens_cached), _count(response.tokens_out)]
        metering = response.metering
        if any(value is None and raw is not None for value, raw in
               zip(tokens, (response.tokens_in, response.tokens_cached, response.tokens_out))):
            tokens, metering = [None, None, None], "estimated"
        fields = {"model": self._secrets.redact(str(response.model)), "tokens_in": tokens[0],
                  "tokens_cached": tokens[1], "tokens_out": tokens[2], "quota_units": quota, "metering": metering}
        if isinstance(response, ModelResponse):
            fields["text"] = self._secrets.redact(str(response.text))
        return dataclasses.replace(response, **fields)

    def _cost(self, request: ModelRequest, candidate: _Candidate, response: ModelResponse) -> dict:
        manifest, estimate = candidate.connector.manifest, candidate.estimate
        reported = response.tokens_in is not None and response.tokens_out is not None
        tokens_in = response.tokens_in if reported else estimate.tokens_in
        tokens_out = response.tokens_out if reported else estimate.tokens_out
        tokens_cached = response.tokens_cached or 0
        if not reported or response.metering == "estimated":
            basis = "estimated"
        else:
            basis = "exact" if manifest["access"] == "api" else "shadow"
        price = candidate.price
        if response.model != estimate.model:  # the provider ran another model than the one routed
            actual = self._routing.price(manifest["id"], response.model, self._clock().date(),
                                         fallback=manifest["access"] != "api")
            if actual is None:
                basis = "estimated"  # no known price for the model that ran; the routed price stands in
            else:
                price = actual
        cost = {"adapter": manifest["id"], "tier": request.tier, "tokens_in": tokens_in,
                "tokens_cached": tokens_cached, "tokens_out": tokens_out, "quota_units": response.quota_units,
                "usd": price.usd(tokens_in, tokens_cached, tokens_out), "basis": basis,
                "price_ver": self._routing.version, "estimated_usd": estimate.usd}
        return {key: value for key, value in cost.items() if value is not None}

    def _failure_cost(self, request: ModelRequest, candidate: _Candidate, ran: bool) -> dict:
        """Usage of a failed call is unknown. A call that reached the provider is charged its estimate, so the
        contract budget stops a contract that keeps failing; a call that never ran costs nothing."""
        return {"adapter": candidate.connector.manifest["id"], "tier": request.tier,
                "usd": candidate.estimate.usd if ran else 0.0, "basis": "estimated",
                "price_ver": self._routing.version, "estimated_usd": candidate.estimate.usd}
