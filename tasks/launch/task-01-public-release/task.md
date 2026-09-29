# Public release and visibility

**Epic:** launch  **Status:** open
**Origin:** ADR 0006 (name), ADR 0007 (governance), spec §12 ("repository is public from F0")

## Goal
Publish the repository so that newcomers understand OOAT in one minute, can contribute, and have a reason to star it.

## Context
- The repository goes public at F0 (spec); a runnable demo only exists from F1. Visibility peaks when people can
  run something, so the loud announcement waits for the F1 demo.
- Creating the public repo, reserving package names and posting announcements are outward-facing: each needs
  the owner's explicit go.

## Acceptance criteria
### At F0 (quiet public repo)
- [x] Public repository https://github.com/pegner-ag/ooat (owner's choice, 2026-09-29).
- [ ] README: one-sentence pitch, the "is a team worth it?" diagram, status badge, links to manifesto and spec.
- [ ] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and pull-request templates, `SECURITY.md`.
- [ ] CI running `pytest` on pull requests; Opus 5.5 review on pull requests (ADR 0007).
- [x] GitHub description and topics.
- [ ] Social preview image.
- [ ] Package names `ooat` reserved on PyPI and npm with a minimal placeholder release.

### At F1 (announcement)
- [ ] `pip install ooat` + a 5-minute quickstart that runs one task end to end and shows the Gate decision and its cost.
- [ ] Short demo video or GIF of the dashboard / ledger.
- [ ] Launch post built on the manifesto's evidence (15× tokens, −39 to −70 % on sequential tasks) and the
      honest "when not to use OOAT" section; submissions to Hacker News, relevant subreddits, LinkedIn.
- [ ] "good first issue" labels on catalog packs and adapters.

## Out of scope
Paid promotion; a hosted service (spec: out of scope).
