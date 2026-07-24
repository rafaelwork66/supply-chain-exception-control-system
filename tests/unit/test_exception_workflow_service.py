"""Unit tests for core exception workflow controls."""

from __future__ import annotations

import uuid

import pytest

from scecs.workflow.service import (
    STATE_TRANSITIONS,
    ApprovalControlError,
    InvalidTransitionError,
    _validate_material_approval,
    _validate_transition,
    is_transition_allowed,
)


def test_transition_matrix_contains_only_governed_core_edges() -> None:
    """The service should expose only the PR-scoped lifecycle path."""

    assert STATE_TRANSITIONS == {
        ("open", "assigned"),
        ("assigned", "investigating"),
        ("investigating", "action_agreed"),
        ("action_agreed", "monitoring"),
        ("monitoring", "resolved"),
        ("resolved", "closed"),
        ("resolved", "investigating"),
    }
    assert is_transition_allowed("resolved", "investigating")
    assert not is_transition_allowed("open", "monitoring")
    assert not is_transition_allowed("closed", "open")


def test_invalid_transition_is_rejected_before_persistence() -> None:
    """Invalid lifecycle moves should fail in validation before any database write."""

    with pytest.raises(InvalidTransitionError):
        _validate_transition("open", "monitoring")

    with pytest.raises(InvalidTransitionError):
        _validate_transition("assigned", "closed")


def test_material_decision_requires_independent_approval() -> None:
    """Resolution, closure, and suppression cannot be self-approved."""

    actor = uuid.uuid4()
    approver = uuid.uuid4()

    _validate_material_approval(actor, approver)

    with pytest.raises(ApprovalControlError):
        _validate_material_approval(actor, None)

    with pytest.raises(ApprovalControlError):
        _validate_material_approval(actor, actor)
