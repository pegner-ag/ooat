# ADR 0013 — Project domain: moonindustries.eu

**Status:** accepted · **Date:** 2026-10-04 · **Context:** ADR 0006 and ADR 0003 #7 left the schema `$id` host as
the placeholder `ooat.invalid` until a domain was chosen.

## Decision

1. OOAT's home is `moonindustries.eu`, under the path `/ooat/`. The owner holds the domain for alternative
   projects; OOAT is the first.
2. Schema identifiers move to `https://moonindustries.eu/ooat/spec/v0.1/<name>.schema.json`. The version segment
   stays and changes with the spec version.
3. The identifiers are names, not addresses: nothing has to be served at them for validation, because the schemas
   are resolved locally from `spec/schemas/`. Publishing them, a project page and documentation on the domain is a
   separate step that needs an IIS site, a certificate and the owner's go.
4. Nothing operational is ever served from the domain: no ledger, artifacts, configuration, keys or tasks. These
   stay in the operator's working folder outside every web root.

## Consequences

- The name OOAT, the repository `pegner-ag/ooat` and the planned package names stay as decided in ADR 0006.
- Documents that hold a schema must keep the new `$id`; a test checks that every schema shares the same base.
- Decided by the owner on 2026-10-04.
