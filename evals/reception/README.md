# Reception message set

Measures the reception (design 08 §11) against messages with the decision a person would expect:
`answer`, `task`, `confirm`, `ask`, `continue_task`, `status`, `cancel`, `command`, `switch` or `forget`.

```
python evals/reception/run.py --config ooat.toml --cases my-messages.json --project docs
```

It uses the operator's connectors and costs a few cents per case. It writes nothing to the operator's ledger: each
case runs in a scratch ledger in memory, which gets only the connectors' acknowledgements. A case may give earlier
turns as `context` (`person`, `reception`, and the reception's numbered `options`), so continuations and numbered
answers can be measured.

The figures it prints are compared with design 08 §1:
- the share decided as expected;
- the share decided without a question;
- the mean cost per message, with a target of USD 0.02.

`example.json` is made up. The owner's own messages are the owner's data. They stay outside the repository until
the owner has picked them and removed anything sensitive.

## Growing the set

Corrections are where the reception was wrong, so they are the best cases. Export them, with the tasks the operator
rejected, to a file outside the repository:

    python evals/candidates.py --config ooat.toml --out ../reception-candidates.json

A candidate has `expected` left empty, and `run.py` refuses such a case. The owner writes the expected decision,
removes anything sensitive and saves the picked cases in `cases/`. From there they run as one set:

    python evals/reception/run.py --config ooat.toml --cases evals/reception/cases --min-expected 0.8

The run exits with 1 below the share given, so it can guard a change of the reception's prompt.
