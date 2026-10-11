"""ooat-client: the REST API of `ooat serve` for bots and scripts, and a reference chat bridge (design 05 §9)."""

from .client import Artifact, OoatClient, OoatError, parse_message

__all__ = ["Artifact", "OoatClient", "OoatError", "parse_message"]
