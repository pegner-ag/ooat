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
