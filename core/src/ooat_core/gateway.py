"""Provider gateway: the only path from OOAT to a model (spec §6, §9; gateway design §6–§8).

Every call is estimated, routed (data class, acknowledgement, automation, quota, price), budget-checked, metered
and returned with a cost record for the caller's event. Connector state is read from the ledger (ADR 0010).
"""

import dataclasses
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import Config
from .connector_admin import acknowledgements
from .connectors import ConnectorError, ModelConnector, ModelRequest, ModelResponse, jurisdiction_stale
from .connectors.registry import Registry
from .ledger import DATA_CLASSES, Ledger, new_event
from .routing import Price, RoutingPolicy
from .credentials_env import SecretResolver

ACTOR = {"kind": "system", "id": "ooat-gateway"}
# Already-paid capacity first when estimated costs tie (ADR 0005).
_ACCESS_RANK = {"subscription_cli": 0, "local": 1, "api": 2, "subscription_manual": 3}
_PERSONAL_OR_HIGHER = frozenset({"personal", "special_category"})
_STATE_EVENTS = ["ADAPTER_ACKNOWLEDGED", "ADAPTER_DISABLED", "QUOTA_WARNING"]


class GatewayError(Exception):
    """NOT_PERMITTED, BUDGET, QUOTA_EXHAUSTED, UNAVAILABLE, API_ERROR or TIMEOUT (design §7)."""

    def __init__(self, code: str, message: str, trace: list[str] | None = None, cost: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.trace = trace or []  # why each connector was excluded
        self.cost = cost  # cost record for the caller's event when a connector was called


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
        connector_id = candidate.connector.manifest["id"]
        try:
            routed = dataclasses.replace(request, model=candidate.estimate.model)
            response = candidate.connector.complete(routed, _OwnSecret(self._secrets, connector_id))
        except ConnectorError as error:
            if error.code == "QUOTA_EXHAUSTED":
                self._cool_down(request, candidate.connector, error.resets_at)
            ran = error.code in ("API_ERROR", "TIMEOUT")  # the provider may have consumed tokens
            raise GatewayError(error.code, self._secrets.redact(error.message),
                               cost=self._failure_cost(request, candidate, ran)) from None
        except Exception as error:  # a connector bug must surface as a typed, redacted failure
            raise GatewayError("API_ERROR", self._secrets.redact(f"{connector_id}: {type(error).__name__}: {error}"),
                               cost=self._failure_cost(request, candidate, True)) from None
        response = self._sanitised(response)
        cost = self._cost(request, candidate, response)
        self._warn_budget(request, cost["usd"])
        return GatewayResult(response, cost, candidate.estimate)

    # Routing ------------------------------------------------------------------------------------------------

    def _route(self, request: ModelRequest) -> _Candidate:
        if request.data_class not in DATA_CLASSES:
            raise ValueError(f"unknown data class: {request.data_class}")
        events = self._ledger.events(types=_STATE_EVENTS)
        acknowledged, cooldowns = acknowledgements(events), self._cooldowns(events)
        candidates, trace, cooling = [], [], set()
        for connector_id in self._registry.ids():
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
        if data_class == "special_category":
            return "special_category needs verified redaction, not available yet"
        policy = self._routing.data_class_policy[data_class]
        if not policy["allowed"]:
            return f"{data_class} is not allowed by the routing policy"
        if data_class not in manifest["data_policy"]["allowed_data_classes"]:
            return f"{data_class} is not allowed by the manifest"
        if data_class not in acknowledgement["allowed_data_classes"]:
            return f"{data_class} was not acknowledged by the operator"
        if policy.get("require_no_training") and manifest["data_policy"]["training_on_inputs"] is not False:
            return f"{data_class} requires a connector that does not train on inputs"
        if policy.get("require_known_region") and not manifest["jurisdiction"]["processing_regions"]:
            return f"{data_class} requires a known processing region"
        if policy.get("require_verified_redaction"):
            return f"{data_class} requires verified redaction, not available yet"
        if policy.get("require_contract"):  # manifests cannot state a processing agreement yet: fail closed
            return f"{data_class} requires a provider contract, which cannot be verified yet"
        if data_class in _PERSONAL_OR_HIGHER and jurisdiction_stale(manifest, acknowledgement, self._clock().date()):
            return "jurisdiction changed or not verified within 12 months; acknowledge again for personal data"
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
        tokens_in = math.ceil(len(request.system + request.prompt) / 4)
        tokens_out = request.expected_output_tokens or request.max_output_tokens
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

    def _sanitised(self, response: ModelResponse) -> ModelResponse:
        """Connector output is untrusted: redact secrets, drop usage numbers the ledger could not store."""
        quota = response.quota_units
        if not (type(quota) in (int, float) and math.isfinite(quota) and quota >= 0):
            quota = None
        tokens = [_count(response.tokens_in), _count(response.tokens_cached), _count(response.tokens_out)]
        metering = response.metering
        if any(value is None and raw is not None for value, raw in
               zip(tokens, (response.tokens_in, response.tokens_cached, response.tokens_out))):
            tokens, metering = [None, None, None], "estimated"
        return dataclasses.replace(response, text=self._secrets.redact(str(response.text)),
                                   model=self._secrets.redact(str(response.model)), tokens_in=tokens[0],
                                   tokens_cached=tokens[1], tokens_out=tokens[2], quota_units=quota,
                                   metering=metering)

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
