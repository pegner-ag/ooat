"""A configurable fake model connector for gateway tests (no network, no secrets)."""

from ooat_core.connectors import ConnectorError, DecisionResponse, Detection, ModelResponse

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


def decision_manifest(connector_id="prv.fakejev.api", model="fake-decision-1", allowed=("public", "internal")):
    return fake_manifest(connector_id, "api", tiers={"decision": model}, allowed=allowed)


class FakeDecisionConnector:
    """Answers every question from a script: {question id: DecisionAnswer} or a function of the request."""

    kind = "decision"

    def __init__(self, manifest=None, answers=None, usage=(300, 20), error=None, reported_model=None):
        self.manifest = manifest or decision_manifest()
        self.answers, self.usage, self.error = answers or {}, usage, error
        self.reported_model = reported_model
        self.calls = []

    def detect(self):
        return Detection(True, "fake decision connector")

    def decide(self, request, secrets):
        self.calls.append(request)
        if self.error:
            raise self.error
        answers = self.answers(request) if callable(self.answers) else self.answers
        model = self.reported_model or request.model or self.manifest["tiers"]["decision"]
        return DecisionResponse(dict(answers), model, self.usage[0], None, self.usage[1], None, "exact")
