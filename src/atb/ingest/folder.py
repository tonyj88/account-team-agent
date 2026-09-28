"""Watched-folder connector: the zero-permission baseline intake path.

Anyone on the team can drag a .md/.txt/.docx/.pdf/.eml export into
data/drop/ (or a customer-named subfolder) regardless of which note app
produced it. No API access of any kind is required, which is why this
connector -- along with obsidian.py -- ships in Phase 1, before any
permission grant.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from atb.ingest.base import RawDocument, path_hints
from atb.models import DocumentSource

# Extensions normalize/ knows how to handle. Anything else is skipped with a
# log line rather than silently ignored, so an unsupported drop is visible.
SUPPORTED_EXTENSIONS = {".md", ".txt", ".docx", ".pdf", ".eml", ".html", ".htm"}


@dataclass
class FolderConnector:
    """Walks `root` recursively and yields every supported file. Dedup is
    left entirely to Document.content_hash downstream (see base.py) --
    this connector does not track what it has already seen, so re-running
    ingest against an unchanged folder is safe and cheap by design, not by
    bookkeeping."""

    root: Path
    enabled: bool = True
    skipped: list[Path] = field(default_factory=list, compare=False)

    def poll(self) -> Iterable[RawDocument]:
        if not self.enabled:
            return
        if not self.root.exists():
            return

        self.skipped = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                self.skipped.append(path)
                continue

            hints = path_hints(path, self.root)
            if path.suffix.lower() in (".md", ".txt", ".html", ".htm", ".eml"):
                raw_text = path.read_text(encoding="utf-8", errors="replace")
                yield RawDocument(
                    source=DocumentSource.FOLDER,
                    origin_path=str(path),
                    filename=path.name,
                    raw_text=raw_text,
                    hints=hints or None,
                )
            else:
                yield RawDocument(
                    source=DocumentSource.FOLDER,
                    origin_path=str(path),
                    filename=path.name,
                    raw_bytes=path.read_bytes(),
                    hints=hints or None,
                )
