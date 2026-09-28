"""Orchestration for `atb qa index` and `atb ask`, logging cost/token spend
to IngestLog the same way extract/pipeline.py does (plan: "ingest history and
cost history are the same table").

Eligible for indexing = resolved to an account (account_id is not null --
an unattached document has no account to scope retrieval to) and not yet
chunked, unless `force=True`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.config import Settings
from atb.extract.store import _resolve_span
from atb.models import Account, Chunk, Document, IngestLog
from atb.qa.chunk import chunk_text
from atb.qa.core import answer_question, route_question
from atb.qa.embed import embed_texts
from atb.qa.retrieval import RetrievedChunk, retrieve_chunks
from atb.qa.schema import Answer, Citation
from atb.qa.structured import gather_structured_context
from atb.qa.vector import pack_embedding
from atb.redact import redact_text

_DECLINE_CRM_ANSWER = Answer(
    can_answer=False,
    answer_text="I don't know -- that requires CRM data not yet connected.",
    citations=[],
)


@dataclass
class IndexingSummary:
    indexed: int = 0
    skipped: int = 0
    chunks_written: int = 0


def _eligible_documents(session: Session, *, limit: int | None, force: bool) -> list[Document]:
    stmt = select(Document).where(Document.account_id.is_not(None))
    if not force:
        stmt = stmt.where(~Document.chunks.any())
    stmt = stmt.order_by(Document.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


def run_indexing(
    session: Session,
    *,
    chunk_size: int,
    chunk_overlap: int,
    limit: int | None = None,
    force: bool = False,
) -> IndexingSummary:
    """Chunks + embeds eligible documents. No LLM call, but embedding is a
    real API call to the proxy now and does carry a (small) per-batch cost
    (qa/embed.py) -- IngestLog still logs it as estimated_cost_usd=0.0 since
    that cost isn't tracked here yet."""
    summary = IndexingSummary()
    documents = _eligible_documents(session, limit=limit, force=force)

    for document in documents:
        if force and document.chunks:
            for existing in list(document.chunks):
                session.delete(existing)
            session.flush()

        windows = chunk_text(document.raw_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not windows:
            summary.skipped += 1
            continue

        texts = [document.raw_text[start:end] for start, end in windows]
        vectors = embed_texts(texts)
        for (start, end), text, vector in zip(windows, texts, vectors, strict=True):
            session.add(
                Chunk(
                    document_id=document.id,
                    text=text,
                    char_start=start,
                    char_end=end,
                    embedding=pack_embedding(vector),
                )
            )
        summary.indexed += 1
        summary.chunks_written += len(windows)
        session.add(
            IngestLog(
                document_id=document.id,
                origin_path=document.origin_path,
                stage="index",
                status="ok",
                detail=f"chunks={len(windows)}",
                estimated_cost_usd=0.0,
            )
        )

    return summary


@dataclass
class AskResult:
    account_name: str | None
    category: str
    answer: Answer
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    estimated_cost_usd: float = 0.0


class AccountNotFoundError(Exception):
    pass


def _resolve_account(session: Session, account_name: str) -> Account:
    account = session.execute(
        select(Account).where(Account.name == account_name)
    ).scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError(f"no account named {account_name!r}")
    return account


def _resolve_citation_spans(session: Session, citations: list[Citation]) -> None:
    """Mirrors extract/store.py's `_resolve_span` discipline: an LLM-reported
    char span is never trusted, only the verbatim quote -- resolved here
    against the cited Document's own raw_text."""
    for citation in citations:
        document = session.get(Document, citation.document_id)
        if document is None:
            citation.char_start, citation.char_end = None, None
            continue
        citation.char_start, citation.char_end = _resolve_span(document.raw_text, citation.quote)


def run_ask(
    session: Session,
    client: anthropic.Anthropic,
    *,
    question: str,
    account_name: str,
    settings: Settings,
) -> AskResult:
    account = _resolve_account(session, account_name)

    decision, route_usage = route_question(question, model=settings.models.route, client=client)
    total_cost = route_usage.estimated_cost_usd

    retrieved: list[RetrievedChunk] = []
    if decision.category == "unsupported_crm":
        answer = _DECLINE_CRM_ANSWER
    else:
        structured_context = gather_structured_context(session, account.id)
        if decision.category == "synthesis":
            retrieved = retrieve_chunks(
                session, question, account_id=account.id, top_k=settings.qa.top_k
            )
        answer, answer_usage = answer_question(
            question,
            account_name=account.name,
            structured_context=structured_context,
            retrieved_chunks=retrieved,
            model=settings.models.answer,
            client=client,
        )
        total_cost += answer_usage.estimated_cost_usd
        _resolve_citation_spans(session, answer.citations)
        # Last-resort net: source notes are redacted at ingest and both
        # prompts (extract/core.py, qa/core.py) instruct the model never to
        # copy a credential into output, but a generated answer is still
        # free text -- run it through the same structural redactor before
        # it's returned/printed. Citation.quote is left alone: it's already
        # resolved against the (already-redacted) Document.raw_text above,
        # and redacting it here would just make it stop matching.
        answer.answer_text = redact_text(answer.answer_text).text

    session.add(
        IngestLog(
            document_id=None,
            origin_path=f"ask:{account.name}",
            stage="answer",
            status="ok",
            detail=f"category={decision.category} question={question!r}",
            model=settings.models.answer,
            estimated_cost_usd=total_cost,
        )
    )

    return AskResult(
        account_name=account.name,
        category=decision.category,
        answer=answer,
        retrieved_chunks=retrieved,
        estimated_cost_usd=total_cost,
    )
