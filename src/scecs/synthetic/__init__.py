"""Deterministic synthetic source-data generator for SCECS.

The package creates portfolio-safe operational source datasets for later ingestion
and testing. It deliberately does not implement risk scoring, exception creation,
workflow services, notifications, dashboards, or AI recommendations.
"""

from scecs.synthetic.config import SyntheticGeneratorConfig, default_portfolio_config
from scecs.synthetic.generator import generate_dataset_bundle

__all__ = ["SyntheticGeneratorConfig", "default_portfolio_config", "generate_dataset_bundle"]
