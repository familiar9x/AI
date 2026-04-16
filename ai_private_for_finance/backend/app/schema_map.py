import yaml
from dataclasses import dataclass
from typing import Dict, Any

from app.config import settings


@dataclass(frozen=True)
class SchemaMap:
    financial_table: Dict[str, Any]
    columns: Dict[str, str]


_cached: SchemaMap | None = None


def load_schema_map() -> SchemaMap:
    global _cached
    if _cached is not None:
        return _cached

    with open(settings.SCHEMA_MAP_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    _cached = SchemaMap(
        financial_table=data["financial_table"],
        columns=data.get("columns", {}),
    )
    return _cached
