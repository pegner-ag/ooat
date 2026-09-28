# OOAT — Known Entities & Gotchas

- The original spec file name contained Czech characters in a Unicode form the Read tool could not open on
  this Windows server; keep repository file names ASCII.
- Spec examples (topology multipliers, worked EU examples, targets, effort estimates) are the author's priors,
  not measurements — never hard-code them as facts; they belong in configuration/priors.
- Price per million tokens is deliberately not in the spec; it lives in `routing.json` with a validity date.
