"""SQLAlchemy models for the account-team-bot brain.

Design principles carried from the plan:
- Provenance is not optional: every extracted fact traces back to a Document
  (and a character span within it) so answers can cite their source.
- Duplicate coverage of one meeting (Terret + Copilot + a teammates notes)
  is kept as separate Documents linked to one Meeting, never collapsed --
  disagreement between sources is signal.
- Entity resolution writes to AccountAlias so the system learns each
  customers naming variants once a human resolves an ambiguous case.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)


class Account(Base):
    """A customer. The canonical name lives here; everything else (aliases,
    Salesforce IDs) resolves to this row."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    salesforce_id: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    aliases: Mapped[list[AccountAlias]] = relationship(back_populates="account")
    contacts: Mapped[list[Contact]] = relationship(back_populates="account")
    documents: Mapped[list[Document]] = relationship(back_populates="account")
    meetings: Mapped[list[Meeting]] = relationship(back_populates="account")
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="account")
    decisions: Mapped[list[Decision]] = relationship(back_populates="account")
    risks: Mapped[list[Risk]] = relationship(back_populates="account")


class AccountAlias(Base):
    """A name/domain variant that resolves to an Account. Populated by rule-
    based resolution (frontmatter, folder path, email domain, fuzzy match)
    and by the human review queue -- never by LLM guess (plan: Entity
    resolution). One write per resolved ambiguity means it is never asked
    again."""

    __tablename__ = "account_aliases"
    __table_args__ = (UniqueConstraint("alias", "kind", name="uq_alias_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    alias: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))  # "name" | "email_domain" | "folder"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="aliases")


class Contact(Base):
    """A person at a customer account. Extracted from meeting attendees or
    synced from the CRM adapter."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_key_contact: Mapped[bool] = mapped_column(default=False)
    source_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )
    # Provenance span within the source document (plan: "every extracted row
    # stores document_id + character span"). Nullable like ActionItem's --
    # a contact seeded via accounts_add or the CRM adapter has no document
    # to span, and a source_quote extraction couldn't locate verbatim also
    # falls back to null rather than dropping the row.
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="contacts")


class DocumentSource(enum.StrEnum):
    FOLDER = "folder"
    OBSIDIAN = "obsidian"
    EMAIL = "email"
    GRAPH_TEAMS = "graph_teams"
    TERRET = "terret"  # inferred from content/sender pattern, not a connector
    COPILOT = "copilot"


class Document(Base):
    """One normalized note/transcript/summary, however it arrived. The unit
    of dedup (content_hash) and the unit of provenance for extraction."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_document_content_hash"),
        Index("ix_documents_account_created", "account_id", "ingested_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )
    meeting_id: Mapped[int | None] = mapped_column(
        ForeignKey("meetings.id"), nullable=True, index=True
    )

    source: Mapped[DocumentSource] = mapped_column(Enum(DocumentSource))
    origin_path: Mapped[str] = mapped_column(Text)  # file path, email msg-id, etc.
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)

    raw_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    # Extraction provenance/versioning (plan: "Controls to build in" --
    # re-extraction must be explicit, never automatic on every ingest run).
    extraction_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account | None] = relationship(back_populates="documents")
    meeting: Mapped[Meeting | None] = relationship(back_populates="documents")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="document")


class Meeting(Base):
    """Links multiple Documents that cover the same real-world meeting
    (matched by account + date + attendee overlap), so 'per Terret' and 'per
    Tonys notes' can both be surfaced instead of one silently overwriting
    the other."""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attendees: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    account: Mapped[Account] = relationship(back_populates="meetings")
    documents: Mapped[list[Document]] = relationship(back_populates="meeting")


class Chunk(Base):
    """A retrieval unit within a Document. `embedding` is a packed float32
    vector (qa/vector.py: pack_embedding/unpack_embedding) scored by brute-
    force cosine similarity in Python at query time -- no sqlite-vec, the
    vault is small enough for this to be instant (see Phase 4 v0 plan).
    char_start/char_end let an answer cite the exact span it drew from.

    NOTE: added after this table already existed in some deployed DBs --
    `create_all()` won't add this column to a pre-existing `chunks` table.
    Since nothing populated Chunk before this change, that's a non-issue in
    practice; a stale DB just needs `ALTER TABLE chunks ADD COLUMN embedding
    BLOB` or recreating."""

    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_document", "document_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ActionItemDirection(enum.StrEnum):
    WE_OWE = "we_owe"  # our team committed to do something
    THEY_OWE = "they_owe"  # the customer committed to do something


class ActionItemStatus(enum.StrEnum):
    OPEN = "open"
    DONE = "done"
    DROPPED = "dropped"


class ActionItem(Base):
    """An extracted commitment, with the direction field the plan calls out
    as most likely to be silently wrong -- verify this field specifically
    when spot-checking extraction quality."""

    __tablename__ = "action_items"
    __table_args__ = (Index("ix_action_items_account_status", "account_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[ActionItemDirection] = mapped_column(Enum(ActionItemDirection))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ActionItemStatus] = mapped_column(
        Enum(ActionItemStatus), default=ActionItemStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="action_items")
    document: Mapped[Document] = relationship(back_populates="action_items")


class Decision(Base):
    """A decision the account team or the customer made, extracted with the
    same provenance discipline as ActionItem (plan: extraction pulls
    "contacts, attendees, action items ... decisions, and risks")."""

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_account", "account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="decisions")
    document: Mapped[Document] = relationship()


class Risk(Base):
    """A risk to the account (churn signal, blocker, unresolved concern)
    surfaced during extraction. Same provenance shape as Decision/ActionItem."""

    __tablename__ = "risks"
    __table_args__ = (Index("ix_risks_account", "account_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    account: Mapped[Account] = relationship(back_populates="risks")
    document: Mapped[Document] = relationship()


class ReviewQueueItem(Base):
    """A document entity-resolution could not place with confidence. Surfaced
    by a CLI command and the web UI (plan: Phase 2) -- resolving one writes
    an AccountAlias so the same ambiguity does not recur."""

    __tablename__ = "review_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), unique=True)
    candidate_names: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    # The exact hint text resolve() tried and failed to match (frontmatter
    # customer/tag, folder name, or title -- whichever it fell back to).
    # Document.title is not a safe substitute: it defaults to the filename
    # stem, which will not generally equal the ambiguous customer wording a
    # future note with the same hint will repeat. Persisting this is what
    # lets `atb review resolve` suggest an alias that actually gets reused
    # (plan: "the system learns each customer's naming variants once").
    attempted_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestLog(Base):
    """One row per ingest run per document. Carries token/cost accounting
    (plan: "Spend logging" -- you cannot defend or tune a bill you cannot
    see) alongside plain success/failure so ingest history and cost history
    are the same table."""

    __tablename__ = "ingest_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    origin_path: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(32))  # "ingest" | "extract" | "index" | "answer"
    status: Mapped[str] = mapped_column(String(16))  # "ok" | "error" | "skipped_duplicate"
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
