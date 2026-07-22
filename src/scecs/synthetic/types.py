"""Shared lightweight types for synthetic dataset generation."""

from __future__ import annotations

from dataclasses import dataclass, field

Record = dict[str, object]
DatasetMap = dict[str, list[Record]]


@dataclass(frozen=True)
class GeneratedDatasetBundle:
    """In-memory generated datasets and generation metadata."""

    datasets: DatasetMap
    config_hash: str
    generator_version: str
    seed: int
    as_of_timestamp: str
    scenario_types: tuple[str, ...] = field(default_factory=tuple)
