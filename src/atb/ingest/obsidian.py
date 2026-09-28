"""Direct Obsidian vault connector.

Watches a vault directly, so the primary author's own notes flow in with no
extra step -- only helps that one person, but it costs almost nothing and
was explicitly kept in scope for the prototype (see plan: agreed intake
paths). Frontmatter parsing itself (python-frontmatter) happens in
normalize/, not here -- this connector's job is just to find the right
files and skip Obsidian's own housekeeping directories.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from atb.ingest.base import RawDocument, path_hints
from atb.models import DocumentSource

# Directories Obsidian and common plugins create that are never customer
# notes. Skipped outright rather than yielded-and-filtered, since their
# contents (config JSON, templates) would otherwise pollute extraction.
EXCLUDED_DIR_NAMES = {".obsidian", ".trash", "templates", "template"}


@dataclass
class ObsidianConnector:
    vault_path: Path
    enabled: bool = False

    def poll(self) -> Iterable[RawDocument]:
        if not self.enabled:
            return
        if not self.vault_path.exists():
            return

        for path in sorted(self.vault_path.rglob("*.md")):
            rel_parts = path.relative_to(self.vault_path).parts[:-1]
            if any(part.lower() in EXCLUDED_DIR_NAMES for part in rel_parts):
                continue

            hints = path_hints(path, self.vault_path)
            raw_text = path.read_text(encoding="utf-8", errors="replace")
            yield RawDocument(
                source=DocumentSource.OBSIDIAN,
                origin_path=str(path),
                filename=path.name,
                raw_text=raw_text,
                hints=hints or None,
            )
