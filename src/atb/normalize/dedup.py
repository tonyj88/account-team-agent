"""Content-hash dedup.

Hashing normalized text (not raw bytes) means the same meeting note re-
exported in a different format, or re-saved with different line endings,
still hashes identically -- which is the point: re-running ingest against
an unchanged drop folder must add nothing (plan: verification step 1).

This only catches exact re-ingests. Near-duplicate coverage of the same
meeting from different sources (Terret vs. a teammate's own notes) is a
separate, deliberate non-goal here -- resolve/meeting_link.py (planned,
docs/PLAN.md Phase C, not yet built) will link them by (account, date,
attendee overlap) instead of hashing them together. Collapsing those would throw away the "per Terret" vs. "per
Tony's notes" signal the plan calls out as worth keeping.
"""

from __future__ import annotations

import hashlib
import re


def content_hash(text: str) -> str:
    """SHA-256 of whitespace-normalized text. Whitespace-only differences
    (trailing spaces, \\r\\n vs \\n, a stray blank line) are exactly the
    kind of noise a re-export or re-save introduces without changing
    content, so they're normalized away before hashing."""
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
