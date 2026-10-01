"""Secret resolution for connectors (gateway design §8).

Config names environment variables; values are read only when a connector asks, and every message leaving the
gateway is passed through redact().
"""

import os
from collections.abc import Mapping

from .config import Config
from .connectors import ConnectorError

REDACTED = "[REDACTED]"


class SecretResolver:
    def __init__(self, config: Config, environ: Mapping[str, str] = os.environ):
        self._config = config
        self._environ = environ

    def get(self, connector_id: str) -> str:
        name = self._config.connectors.get(connector_id, {}).get("secret_env")
        if not name:
            raise ConnectorError("UNAVAILABLE", f"{connector_id}: no secret_env configured")
        value = (self._environ.get(name) or "").strip()  # a key copied from a file often ends with a newline
        if not value:
            raise ConnectorError("UNAVAILABLE", f"{connector_id}: environment variable {name} is not set")
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ConnectorError("UNAVAILABLE", f"{connector_id}: environment variable {name} contains whitespace "
                                                f"or control characters")
        return value

    def redact(self, text: str) -> str:
        """Replace every configured secret value in text; longest first so overlapping values leave nothing."""
        values = {self._environ.get(s.get("secret_env", ""), "") for s in self._config.connectors.values()}
        for value in sorted((v for v in values if v), key=len, reverse=True):
            text = text.replace(value, REDACTED)
        return text
