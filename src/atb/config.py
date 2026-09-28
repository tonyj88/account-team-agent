"""Typed settings and feature flags.

Every external dependency this project has (Salesforce, Microsoft Graph, Teams)
is gated behind an `enabled` flag here, defaulting to False. The rest of the
codebase must run correctly with every flag False — that's what lets Phases
0-5 ship without waiting on a single permission grant. See the plan's
"graceful degradation" section.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# Model choice is a deliberate cost decision (see plan: "Cost model and
# controls"), not a placeholder — don't "upgrade" these defaults without
# updating that section's numbers too.
ModelTask = Literal["extract", "answer", "route"]


class ModelConfig(BaseModel):
    """Per-task model overrides. Keeps a model swap to a config edit."""

    extract: str = "claude-sonnet-5"
    answer: str = "claude-sonnet-5"
    route: str = "claude-haiku-4-5"


class FolderIntakeConfig(BaseModel):
    enabled: bool = True
    path: Path = Path("data/drop")


class ObsidianIntakeConfig(BaseModel):
    enabled: bool = False
    vault_path: Path | None = None


class EmailIntakeConfig(BaseModel):
    """Plain IMAP on a dedicated mailbox — the fallback that tends to clear
    review faster than Graph Mail.Read (see plan: Phase 0 permission asks)."""

    enabled: bool = False
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""  # pragma: allowlist secret — env var in practice
    folder: str = "INBOX"


class GraphTeamsIntakeConfig(BaseModel):
    """Requires Azure app registration + Graph ChannelMessage.Read.All.
    Off until that grant lands; nothing downstream depends on it."""

    enabled: bool = False
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""  # pragma: allowlist secret
    channel_id: str = ""


class IntakeConfig(BaseModel):
    folder: FolderIntakeConfig = Field(default_factory=FolderIntakeConfig)
    obsidian: ObsidianIntakeConfig = Field(default_factory=ObsidianIntakeConfig)
    email: EmailIntakeConfig = Field(default_factory=EmailIntakeConfig)
    graph_teams: GraphTeamsIntakeConfig = Field(default_factory=GraphTeamsIntakeConfig)


class CrmConfig(BaseModel):
    """`provider = "csv_stub"` works with zero API access — see crm/csv_stub.py.
    Switch to "salesforce" only once read-only Connected App credentials exist.
    write_enabled must stay False until Salesforce write access is granted;
    until then CrmProvider.publish_note/create_task log a dry-run diff instead
    of calling out (see plan: Phase 7)."""

    provider: Literal["csv_stub", "salesforce"] = "csv_stub"
    csv_export_path: Path = Path("data/crm_exports")
    write_enabled: bool = False

    sf_username: str = ""
    sf_password: str = ""  # pragma: allowlist secret
    sf_security_token: str = ""  # pragma: allowlist secret
    sf_domain: str = "login"


class QaConfig(BaseModel):
    """Retrieval/QA tuning. Brute-force in-DB cosine similarity is fine at
    this vault's size (Phase 4 v0) -- revisit (sqlite-vec, a real vector
    store) only if `atb qa index`/`atb ask` start taking noticeably long.

    embedding_model/embedding_dimensions configure the proxy-hosted
    embeddings call in qa/embed.py -- native 1536-dim text-embedding-3-small
    by default; embedding_dimensions=None means don't truncate."""

    chunk_size: int = 1500
    chunk_overlap: int = 200
    top_k: int = 6
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int | None = None


class TeamsChannelConfig(BaseModel):
    """Requires Azure app registration + bot channel registration. The web
    app (channels/web) is the fallback front door if this is denied or
    delayed — it needs none of this config."""

    enabled: bool = False
    app_id: str = ""
    app_password: str = ""  # pragma: allowlist secret


class RedactionConfig(BaseModel):
    """Secret redaction over source notes -- see redact.py for the rules and
    why this runs at ingest, not "on the way to the LLM". Defaults to ON:
    this is a safety layer, not an opt-in feature."""

    enabled: bool = True


class Settings(BaseModel):
    data_dir: Path = Path("data")
    db_path: Path = Path("data/atb.sqlite")

    models: ModelConfig = Field(default_factory=ModelConfig)
    intake: IntakeConfig = Field(default_factory=IntakeConfig)
    crm: CrmConfig = Field(default_factory=CrmConfig)
    qa: QaConfig = Field(default_factory=QaConfig)
    teams: TeamsChannelConfig = Field(default_factory=TeamsChannelConfig)
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)

    @classmethod
    def load(cls, path: Path | str = "config.toml") -> Settings:
        """Load from config.toml if present, else pure defaults (folder
        intake + csv_stub CRM — the zero-permission baseline)."""
        p = Path(path)
        if not p.exists():
            return cls()
        with p.open("rb") as f:
            raw = tomllib.load(f)
        return cls.model_validate(raw)


def get_settings() -> Settings:
    return Settings.load()
