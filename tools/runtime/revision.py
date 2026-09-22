"""Canonical revision tokens for semantic records."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_body(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "revision"}


def compute_revision(record: dict[str, Any]) -> str:
    canonical = json.dumps(canonical_body(record), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"sha256:{digest}"


def with_revision(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["revision"] = compute_revision(out)
    return out
