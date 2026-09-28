"""Brute-force cosine-similarity retrieval over Chunk embeddings.

No sqlite-vec, no vector DB -- a small vault's chunk count makes this
instant. Revisit if `atb qa index`/`atb ask` start taking noticeably long
(see config.py: QaConfig).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.models import Chunk, Document
from atb.qa.embed import embed_texts
from atb.qa.vector import cosine_similarity, unpack_embedding


@dataclass
class RetrievedChunk:
    chunk: Chunk
    score: float


def retrieve_chunks(
    session: Session,
    query: str,
    *,
    account_id: int | None,
    top_k: int,
) -> list[RetrievedChunk]:
    """Embeds `query`, scores every embedded Chunk (scoped to `account_id`
    when given) by cosine similarity, returns the top_k descending."""
    query_vec = embed_texts([query])[0]

    stmt = (
        select(Chunk)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.embedding.is_not(None))
    )
    if account_id is not None:
        stmt = stmt.where(Document.account_id == account_id)
    candidates = session.execute(stmt).scalars().all()

    scored = [
        RetrievedChunk(chunk=c, score=cosine_similarity(query_vec, unpack_embedding(c.embedding)))
        for c in candidates
    ]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]
