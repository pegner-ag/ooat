# ADR 0006 — Project name

**Status:** accepted · **Date:** 2026-09-29 · **Answers:** Q10

The project is published as open source under the name **OOAT**.

## Availability check (2026-09-29)

| Namespace | Name | Result |
|---|---|---|
| PyPI | `ooat`, `ooat-core`, `ooat-sdk`, `ooat-cli` | free |
| npm | `ooat`, `ooat-sdk`, `@ooat/sdk` | free (org `@ooat` not checked beyond the package) |
| GitHub | user/org `ooat` | taken by an inactive personal account (1 public repo, last update 2020) |
| GitHub | `ooat-dev`, `ooat-framework`, `ooat-project` | free |

Existing GitHub repositories named `ooat` are unrelated, empty personal projects. Trademark registries
were not searched.

## Consequences

- Package names `ooat` (PyPI, npm) are used as planned.
- The public repository is https://github.com/pegner-ag/ooat.
- Schema `$id` host stays `ooat.invalid` until a domain is chosen. (Superseded by ADR 0013: `moonindustries.eu`.)
