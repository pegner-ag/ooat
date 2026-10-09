"""The cost of a contract as spec §11 measures it, and the prior used before enough runs exist (plan 04d).

Spec §11: "Cost: p50 and p90 over the last 50 runs, per adapter; history is split when the model behind a tier
changes." A run is a closed contract; its cost is every call charged to it (worker, decision checks, critic,
failed calls at their charged estimate). The ledger's cost records carry no model id, so a change of the price
version stands in for a model change.
"""

import math
from dataclasses import dataclass

MIN_RUNS = 5
RUNS = 50


def contract_costs(events: list[dict], adapter: str, tier: str) -> list[float]:
    """Cost of each closed contract whose worker ran on `adapter` at `tier`, oldest first, last RUNS only, all on
    the price version of the most recent one."""
    closed = {e["task"] for e in events if e["type"] == "TASK_CLOSED"}
    runs: dict[str, dict] = {}
    for event in events:
        ctr, cost = event.get("contract"), event.get("cost")
        if not ctr or not cost or event.get("task") not in closed:
            continue
        run = runs.setdefault(ctr, {"usd": 0.0, "worker": None})
        run["usd"] += cost.get("usd", 0.0)
        # the run belongs to the adapter of its first worker call (a RESULT or an ABSTAIN with a cost)
        if event["type"] in ("RESULT", "ABSTAIN") and run["worker"] is None:
            run["worker"] = (cost.get("adapter"), cost.get("tier"), cost.get("price_ver"))
    mine = [r for r in runs.values() if r["worker"] and r["worker"][:2] == (adapter, tier)]
    if not mine:
        return []
    versions = [r["worker"][2] for r in mine if r["worker"][2] is not None]
    current = versions[-1] if versions else None  # a run without a price version never drops versioned history
    return [r["usd"] for r in mine if r["worker"][2] in (current, None)][-RUNS:]


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with at least q of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)), 1) - 1]


@dataclass(frozen=True)
class Priors:
    output_tokens: int  # the worker's deliverable
    critic_output_tokens: int
    fallback_tokens_per_question: int  # a text-model decision; the CLI does not enforce max_output_tokens
    retry_prior: float  # share of contracts needing a second attempt
    critic_prior: float  # share of contracts in which the critic runs


def prior_usd(worker_usd: float, checks_usd: float, critic_usd: float, priors: Priors, critic_certain: bool) -> float:
    """One attempt (worker, decision checks, the critic by its share) times the expected attempts. The critic is
    certain with an untrusted attachment, or when no decision route can check the criteria."""
    share = 1.0 if critic_certain else priors.critic_prior
    return (worker_usd + checks_usd + share * critic_usd) * (1 + priors.retry_prior)
