"""A configurable fake model connector for gateway tests (no network, no secrets)."""

from ooat_core.connectors import ConnectorError, Detection, ModelResponse

JURISDICTION = {
    "vendor_entity": "Fake Vendor Ltd", "vendor_country": "IE", "host_entity": "Fake Vendor Ltd",
    "processing_regions": ["eu"], "eu_region_available": True, "model_origin_country": "IE",
    "training_on_inputs": False, "retention": "30 days", "zero_retention_available": False,
    "transfer_notes": None, "source_urls": ["https://fake.invalid/privacy"], "verified_on": "2026-09-01",
}


def fake_manifest(connector_id="prv.fake.api", access="api", tiers=None, version="1.0.0",
                  allowed=("public", "internal", "client_confidential", "personal"),
                  automation="unknown", jurisdiction=None):
    manifest = {
        "id": connector_id, "version": version, "vendor": connector_id.split(".")[1], "access": access,
        "tiers": tiers or {"workhorse": "fake-model"}, "metering": "exact" if access == "api" else "reported",
        "automation_permitted": automation, "concurrency": 1,
        "data_policy": {"training_on_inputs": False, "retention_days": 30, "allowed_data_classes": list(allowed)},
        "jurisdiction": dict(jurisdiction or JURISDICTION),
    }
    if access.startswith("subscription"):
        manifest["plan"] = {"fee_usd_month": 100, "quota_window_hours": 5, "units": "token_equivalent"}
    if access == "subscription_cli":
        manifest["runner"] = "fake-cli"
    return manifest


class FakeConnector:
    kind = "model"

    def __init__(self, manifest=None, text="Hotovo.", usage=(1000, 0, 200), error=None, secret_seen=None,
                 reported_model=None):
        self.manifest = manifest or fake_manifest()
        self.reported_model = reported_model  # a model other than the routed one, as a CLI may run
        self.text, self.usage, self.error = text, usage, error
        self.calls = []
        self.secret_seen = secret_seen  # connector id whose secret is requested on each call

    def detect(self):
        return Detection(True, "fake connector")

    def complete(self, request, secrets):
        self.calls.append(request)
        if self.secret_seen:
            secrets.get(self.secret_seen)
        if self.error:
            raise self.error
        tokens_in, tokens_cached, tokens_out = self.usage
        model = self.reported_model or request.model or self.manifest["tiers"][request.tier]
        metering = "exact" if self.manifest["access"] == "api" else "reported"
        return ModelResponse(self.text, model, tokens_in, tokens_cached, tokens_out, None, metering)


def quota_error(resets_at=None):
    return ConnectorError("QUOTA_EXHAUSTED", "usage limit reached", resets_at=resets_at)
