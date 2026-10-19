# The owner's reception cases

Cases picked by the owner from the output of `evals/candidates.py`, with anything sensitive removed and `expected`
written. Each `*.json` file here is one list in the format of `../run.py`; the keys `got`, `correction` and `then`
of a candidate may stay, the runner ignores them. CI checks that every file loads. It never runs them, because a
run calls the operator's real connectors and costs money.

Before merging a change of the reception's prompt or routing, run:

    python evals/reception/run.py --config ooat.toml --cases evals/reception/cases --min-expected 0.8

and put its three figures in the pull request.
