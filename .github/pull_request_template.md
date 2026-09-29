## What and why

<!-- One topic per pull request. Link the issue or ADR this relates to. -->

## Checklist

- [ ] `python -m pytest` passes
- [ ] Schema changes include a valid example and an invalid case
- [ ] New capabilities use the lowest `impl` that works and include acceptance criteria
- [ ] Unknown facts in adapter manifests are `null`, with sources for the rest
- [ ] No secrets, personal data or client documents
- [ ] Docs in `docs/` describe the current state (no plans, no changelog)
