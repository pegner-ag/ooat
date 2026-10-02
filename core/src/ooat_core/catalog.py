"""Read catalog cards and the reference routing policy from the repository's catalog/ folder.

Like the schemas (validation.py), the catalog is read from the checkout, so the package works from a checkout or an
editable install; packaging it into the wheel is release work. Loading and resolving the whole catalog is
sub-project 02; the runtime only reads the cards it names.
"""

import json
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parents[3] / "catalog"


def load_card(folder: str, card_id: str) -> dict:
    """A card by id from catalog/<folder>/<id>.json; families are stored by their short name (family.base)."""
    name = card_id.removeprefix("family.") if folder == "families" else card_id
    return json.loads((CATALOG_DIR / folder / f"{name}.json").read_text(encoding="utf-8"))


def routing_path() -> Path:
    return CATALOG_DIR / "routing.json"
