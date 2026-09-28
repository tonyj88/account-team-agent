"""The ingestion protocol every connector implements.

This is the degradation mechanism described in the plan: folder and obsidian
need no external permissions and ship first; email/graph_teams are added as
access arrives, with zero change to normalize/resolve/extract/store. Nothing
downstream of poll() should ever need to know which connector produced a
RawDocument.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from atb.models import DocumentSource


@dataclass(frozen=True)
class RawDocument:
    """Unnormalized content plus enough metadata to normalize and resolve
    it. `raw_bytes` for binary formats (docx/pdf); `raw_text` when the
    connector already has decoded text (md/txt/eml body)."""

    source: DocumentSource
    origin_path: str  # file path, email message-id, Graph message id, etc.
    filename: str  # used for format sniffing (extension) in normalize/
    raw_bytes: bytes | None = None
    raw_text: str | None = None
    author: str | None = None
    occurred_at: datetime | None = None
    # Free-form hints a connector can supply toward entity resolution --
    # e.g. folder-derived account hint, frontmatter tags, participant
    # emails -- consumed by resolve/, never trusted blindly.
    hints: dict[str, str] | None = None


class SourceConnector(Protocol):
    """Every intake path -- folder, Obsidian, email, Teams channel --
    implements this. `enabled` mirrors the connector's config flag so the
    ingest CLI can skip disabled connectors without importing their
    (possibly permission-gated) dependencies."""

    enabled: bool

    def poll(self) -> Iterable[RawDocument]:
        """Yield documents seen since the last poll. Connectors that
        maintain their own "already seen" state (e.g. an IMAP UID
        watermark) should do so internally; the folder connector uses the
        Document.content_hash uniqueness constraint downstream instead, so
        re-polling the same file is cheap and safe, not just tolerated."""
        ...


def path_hints(path: Path, drop_root: Path) -> dict[str, str]:
    """Shared helper: derive resolution hints from a file's location
    relative to the watched root, e.g. data/drop/Acme Corp/notes.md ->
    {"folder": "Acme Corp"}. Used by both folder.py and obsidian.py so a
    customer-named subfolder means the same thing in either vault."""
    try:
        rel = path.relative_to(drop_root)
    except ValueError:
        return {}
    if len(rel.parts) > 1:
        return {"folder": rel.parts[0]}
    return {}
