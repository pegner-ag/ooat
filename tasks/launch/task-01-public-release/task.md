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
- [x] `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), issue and pull-request templates, `SECURITY.md` with private vulnerability reporting enabled.
- [x] CI running `pytest` (`.github/workflows/tests.yml`); Opus 5.5 review workflows (`claude-review.yml`, `claude.yml`).
- [ ] Owner installs the Claude GitHub App and sets `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` (review workflows fail until then).
- [ ] Code of Conduct contact: replace the GitHub-profile pointer with a dedicated contact address if the owner wants one.
- [x] GitHub description, topics and issue labels (`spec`, `catalog`, `adapter`).
- [x] Social preview image `docs/assets/social-preview.png` (also README header).
- [ ] Owner uploads it in GitHub Settings → Social preview (no API for this).
- [ ] Package names `ooat` reserved on PyPI and npm with a minimal placeholder release.

### At F1 (announcement)
- [ ] `pip install ooat` + a 5-minute quickstart that runs one task end to end and shows the Gate decision and its cost.
- [ ] Short demo video or GIF of the dashboard / ledger.
- [ ] Launch post built on the manifesto's evidence (15× tokens, −39 to −70 % on sequential tasks) and the
      honest "when not to use OOAT" section; submissions to Hacker News, relevant subreddits, LinkedIn.
- [ ] "good first issue" labels on catalog packs and adapters.

## Out of scope
Paid promotion; a hosted service (spec: out of scope).
