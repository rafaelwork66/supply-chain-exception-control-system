"""Tests for the physical domain model metadata."""

from scecs.models import Base


def test_domain_metadata_contains_required_tables() -> None:
    """The physical model should expose the core governed table set."""

    required_tables = {
        "source_systems",
        "pipeline_runs",
        "source_loads",
        "sites",
        "suppliers",
        "products",
        "users",
        "purchase_order_lines",
        "receipt_transactions",
        "receipt_allocations",
        "candidate_risk_evaluations",
        "candidate_risk_contributions",
        "exception_episodes",
        "exception_event_envelopes",
        "exception_state_events",
        "approval_requests",
        "approval_decisions",
        "notification_events",
        "suppression_controls",
        "evidence_references",
        "evidence_links",
        "resolution_records",
        "analytics_publications",
    }

    assert required_tables.issubset(Base.metadata.tables.keys())


def test_exception_episode_has_active_uniqueness_index() -> None:
    """The ORM metadata should document the active line/site uniqueness index."""

    table = Base.metadata.tables["exception_episodes"]
    indexes = {str(index.name): index for index in table.indexes}

    active_index = indexes["uq_exception_episodes_active_line_site"]
    assert str(active_index.dialect_options["postgresql"]["where"]) == "closed_at IS NULL"
