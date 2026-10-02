# ADR 0012 — The operator takes responsibility for client and personal data

**Status:** accepted · **Date:** 2026-10-02 · **Context:** the personal-data pre-scan (ADR 0011) raises tasks
with an e-mail address or phone number to `personal`, but no route for `personal` exists: the reference policy
requires a provider contract no manifest can state, regions are mostly unknown and no manifest is verified.

## Decision

1. When enabling a connector for `client_confidential` or `personal`, the named operator takes responsibility for
   that data: legal basis, processing agreement with the provider, where it is processed. It is recorded in
   `ADAPTER_ACKNOWLEDGED.body.responsibility` with the date and holds for 12 months.
2. For those two classes the responsibility meets `require_contract`, supplies the processing regions when the
   manifest does not know them, and supplies "training off" when the manifest does not know it. The operator's
   check of the card counts as the verification date for the 12-month rule.
3. With responsibility and "training off", a connector may carry those two classes beyond its manifest's
   `allowed_data_classes` (for example a subscription CLI), unless the manifest says the provider trains on
   inputs. `special_category` is never covered.
4. The operator's `[policy]` in `ooat.toml` can block countries (vendor or model origin) for every class and limit
   personal data to listed regions. The gateway enforces it; the card and the listing show it.

## Spec text this overrides

- §9 "Routing enforces classes against each adapter's `allowed_data_classes`": the operator's responsibility may
  extend them for `client_confidential` and `personal` (point 3).
- §9 rule 2: the later of the manifest's `verified_on` and the operator's `confirmed_on` counts.
- §9 reference routing policy: "a contract" is met by the operator's recorded responsibility.

## Consequences

- Tasks with personal details run once the operator has enabled one connector for `personal`; the pre-scan stays.
- OOAT records statements; it does not verify them. The operator answers for them (spec §9).
- The spec v0.2 revision carries these changes into §9.
- Decided by the owner on 2026-10-02.
