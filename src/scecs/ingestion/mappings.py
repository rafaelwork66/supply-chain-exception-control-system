"""Explicit source-to-target mappings."""

from __future__ import annotations

from dataclasses import dataclass

from scecs.ingestion.config import LOAD_ORDER
from scecs.ingestion.contracts import build_contracts


@dataclass(frozen=True)
class TableMapping:
    """Mapping from one source dataset to one governed PostgreSQL table."""

    dataset_name: str
    table_name: str
    columns: tuple[str, ...]
    excluded_columns: tuple[str, ...]


def build_table_mappings() -> dict[str, TableMapping]:
    """Return explicit operational table mappings."""

    contracts = build_contracts()
    mappings: dict[str, TableMapping] = {}
    for dataset_name in LOAD_ORDER:
        contract = contracts[dataset_name]
        mappings[dataset_name] = TableMapping(
            dataset_name=dataset_name,
            table_name=dataset_name,
            columns=tuple(sorted(contract.required_columns)),
            excluded_columns=tuple(sorted(contract.optional_columns)),
        )
    return mappings


def mapping_report() -> list[dict[str, object]]:
    """Return source-to-target mapping rows for docs and CLI inspection."""

    return [
        {
            "dataset_name": mapping.dataset_name,
            "target_table": mapping.table_name,
            "mapped_columns": list(mapping.columns),
            "excluded_evidence_columns": list(mapping.excluded_columns),
        }
        for mapping in build_table_mappings().values()
    ]
