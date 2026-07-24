"""Rejected-record classification helpers."""

from __future__ import annotations

import hashlib


def safe_value_hash(value: object) -> str:
    """Hash a rejected value instead of storing unsafe raw content."""

    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
