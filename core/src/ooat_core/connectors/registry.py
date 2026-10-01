"""Discovery of installed connectors (entry-point group "ooat.connectors").

A connector that fails to load, has an invalid manifest, an unsupported kind or a duplicate id is listed as
broken and never used; it does not stop the other connectors from loading.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points

from ..validation import SpecValidationError, validate
from . import ENTRY_POINT_GROUP, ModelConnector


@dataclass(frozen=True)
class BrokenConnector:
    name: str
    error: str


class Registry:
    def __init__(self, connectors: Iterable[ModelConnector] = (), broken: Iterable[BrokenConnector] = ()):
        self.broken: list[BrokenConnector] = list(broken)
        found: dict[str, list[ModelConnector]] = {}
        for connector in connectors:
            connector_id = self._check(connector)
            if connector_id is not None:
                found.setdefault(connector_id, []).append(connector)
        self._connectors: dict[str, ModelConnector] = {}
        for connector_id, same_id in found.items():
            if len(same_id) > 1:  # which one is meant is unknowable, so neither is used
                self.broken.append(BrokenConnector(connector_id, f"{len(same_id)} connectors share this id"))
            else:
                self._connectors[connector_id] = same_id[0]

    def _check(self, connector) -> str | None:
        manifest = getattr(connector, "manifest", None)
        name = manifest.get("id", repr(connector)) if isinstance(manifest, dict) else repr(connector)
        if getattr(connector, "kind", None) != "model":
            self.broken.append(BrokenConnector(name, f"unsupported connector kind: {getattr(connector, 'kind', None)!r}"))
            return None
        try:
            validate("provider", manifest)
        except (SpecValidationError, TypeError) as error:
            self.broken.append(BrokenConnector(name, str(error)))
            return None
        return manifest["id"]

    @classmethod
    def discover(cls) -> "Registry":
        connectors, broken = [], []
        for entry_point in entry_points(group=ENTRY_POINT_GROUP):
            try:
                connectors.append(entry_point.load()())
            except Exception as error:  # a broken plugin must not take the gateway down
                broken.append(BrokenConnector(entry_point.name, f"{type(error).__name__}: {error}"))
        return cls(connectors, broken)

    def ids(self) -> list[str]:
        return sorted(self._connectors)

    def get(self, connector_id: str) -> ModelConnector | None:
        return self._connectors.get(connector_id)
