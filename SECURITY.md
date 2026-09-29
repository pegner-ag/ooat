# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems. Report them privately through
[GitHub private vulnerability reporting](https://github.com/pegner-ag/ooat/security/advisories/new).

Include what is affected, how to reproduce it and the impact you expect. You will get an answer within
7 days. Please allow time for a fix before disclosing publicly.

## Scope

OOAT is at specification stage; there is no released runtime yet. Reports about the design are welcome too,
especially about:

- data-class enforcement and data leaving the operator's machine,
- prompt injection through untrusted content (web pages, e-mails, client documents),
- ways an agent could perform an irreversible (R3) action without a named human approver,
- secrets reaching agent context, artifacts or the ledger.
