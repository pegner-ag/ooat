# Operator responsibility for client and personal data — design

**Epic:** f1-skeleton · **Sub-project:** 03e · **Status:** agreed with the owner in session, 2026-10-02
**Spec:** `spec/ooat-specification.md` §9 (data classes, operator responsibility, reference routing policy);
ADR 0010 (connector state), ADR 0011 (pre-scan raises the class), ADR 0012 (new)

## 1. Intent

What the owner decided (2026-10-02):

- The local pre-scan (04b) must not stop ordinary work. A web page with an e-mail address is personal data, and
  such tasks must run without asking every few seconds.
- The operator decides once, per connector, whether client or personal data may go there, and takes
  responsibility for it.
- The operator can rule out whole countries (for example models from China) and keep personal data in chosen
  regions (for example only the EU, so nothing personal goes to the US).
- Subscription connectors (Claude Code, Codex) may carry client and personal data too, when the operator states
  that training on inputs is switched off for the account.

Today every route for `client_confidential` and `personal` is closed: the reference `routing.json` requires a
provider contract that no manifest can state, most manifests do not know their processing region, and none has
been verified, so the 12-month rule (spec §9 rule 2) treats them all as stale.

## 2. Responsibility on the acknowledgement

`ooat connectors enable` asks, when the chosen classes include `client_confidential` or `personal`:

1. "Do you take this responsibility?" — legal basis, processing agreement with the provider, knowledge of where
   it processes. No → nothing is recorded.
2. When the manifest does not know the processing regions: the regions under the operator's agreement (optional).
3. When the manifest does not know whether the provider trains on inputs: "Is training switched off for this
   account?" Required before a connector can carry these classes beyond its manifest.

`ADAPTER_ACKNOWLEDGED.body.responsibility = {confirmed_on, processing_regions?, no_training?}`, by the named
operator. It holds for 12 months from `confirmed_on`; the fingerprint rule of ADR 0010 still applies, so a change
of the jurisdiction facts asks again.

What the responsibility stands in for, in the gateway, for `client_confidential` and `personal` only:

| Reference policy requirement | Without responsibility | With responsibility |
|---|---|---|
| `require_contract` | refused (cannot be verified) | met |
| `require_known_region` | manifest regions only | manifest regions, else the operator's |
| `require_no_training` | manifest `false` only | also the operator's `no_training`, unless the manifest says the provider trains |
| manifest `allowed_data_classes` | binding | may be exceeded for these two classes |
| 12-month verification (personal) | manifest `verified_on` | the later of `verified_on` and `confirmed_on` |

`special_category` is never covered: it still needs verified redaction (spec §9).

## 3. Operator policy in `ooat.toml`

```toml
[policy]
blocked_countries = ["CN"]       # vendor_country or model_origin_country; every class
personal_data_regions = ["eu"]   # personal and special-category data only where all regions are listed
```

Unknown values never block a country (the card shows them as unknown); unknown regions do fail the region limit.
The card (`ooat connectors show`) and the listing show what the policy does to each connector.

## 4. Out of scope

- Verifying any statement: OOAT records it, the operator answers for it (spec §9: "OOAT does not assess or certify
  regulatory compliance").
- Changing `catalog/routing.json`: the reference policy stays strict; responsibility is how an operator meets it.

## 5. Testing

Unit tests for the schema, config, connector administration, gateway exclusions and the CLI; the gateway tests use
the reference policy's requirements.
