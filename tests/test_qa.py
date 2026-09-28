"""QA: chunking, vector helpers, retrieval, indexing idempotency, routing/
answer branching, citation resolution, and cost logging -- all against a
fake Anthropic client and a fake embedder, mirroring test_extract.py's
approach at unit-test speed instead of a live call."""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.config import Settings
from atb.models import Account, Chunk, Document, DocumentSource, IngestLog
from atb.qa import embed as embed_module
from atb.qa.chunk import chunk_text
from atb.qa.embed import EmbeddingConfigError, embed_texts
from atb.qa.pipeline import AccountNotFoundError, run_ask, run_indexing
from atb.qa.retrieval import retrieve_chunks
from atb.qa.schema import Answer, Citation, RoutingDecision
from atb.qa.vector import cosine_similarity, pack_embedding, unpack_embedding


def _make_document(session: Session, *, account_id: int | None, raw_text: str) -> Document:
    doc = Document(
        account_id=account_id,
        source=DocumentSource.FOLDER,
        origin_path="acme/note.md",
        raw_text=raw_text,
        content_hash=f"hash-{raw_text!r}-{id(raw_text)}",
    )
    session.add(doc)
    session.flush()
    return doc


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


def test_chunk_text_empty_returns_no_windows():
    assert chunk_text("", chunk_size=100, chunk_overlap=10) == []


def test_chunk_text_shorter_than_chunk_size_returns_one_window():
    text = "short text"
    assert chunk_text(text, chunk_size=100, chunk_overlap=10) == [(0, len(text))]


def test_chunk_text_splits_with_overlap_and_covers_whole_text():
    text = "a" * 250
    windows = chunk_text(text, chunk_size=100, chunk_overlap=20)

    assert windows[0] == (0, 100)
    assert windows[1] == (80, 180)
    assert windows[-1][1] == len(text)
    # every window is within bounds
    for start, end in windows:
        assert 0 <= start < end <= len(text)


# ---------------------------------------------------------------------------
# vector.py
# ---------------------------------------------------------------------------


def test_pack_unpack_embedding_round_trips():
    vector = [0.1, -0.2, 0.3, 0.0]
    blob = pack_embedding(vector)
    restored = unpack_embedding(blob)
    assert len(restored) == len(vector)
    for original, got in zip(vector, restored, strict=True):
        assert abs(original - got) < 1e-6


def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_returns_zero_not_nan():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


# ---------------------------------------------------------------------------
# embed.py -- proxy embeddings: batching, order preservation, config errors.
# Real network calls are never made; httpx.MockTransport stands in for the
# proxy so these run at unit-test speed offline.
# ---------------------------------------------------------------------------


def _mock_transport(*, shuffle: bool = False) -> tuple[httpx.MockTransport, list[int]]:
    """Fake /v1/embeddings: echoes one vector per input, keyed by `index`.
    `shuffle` reverses the response order to prove the caller re-sorts by
    index rather than trusting arrival order. Returns (transport, batch_sizes)
    where batch_sizes records len(input) per request, for asserting batching."""
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        payload = json.loads(request.content)
        inputs = payload["input"]
        batch_sizes.append(len(inputs))
        rows = [{"index": i, "embedding": [float(len(text)), 0.0]} for i, text in enumerate(inputs)]
        if shuffle:
            rows = list(reversed(rows))
        return httpx.Response(200, json={"data": rows})

    return httpx.MockTransport(handler), batch_sizes


@pytest.fixture
def _proxy_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "test-token")


def test_embed_texts_empty_input_returns_empty_without_calling_proxy(_proxy_env, monkeypatch):
    def _boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("embed_texts([]) must not call the proxy")

    monkeypatch.setattr(embed_module, "_transport_override", httpx.MockTransport(_boom))
    assert embed_texts([]) == []


def test_embed_texts_missing_env_vars_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(EmbeddingConfigError):
        embed_texts(["hello"])


def test_embed_texts_single_batch_preserves_order(_proxy_env, monkeypatch):
    transport, batch_sizes = _mock_transport()
    monkeypatch.setattr(embed_module, "_transport_override", transport)

    texts = ["a", "bb", "ccc"]
    vectors = embed_texts(texts)

    assert batch_sizes == [3]
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]


def test_embed_texts_multi_batch_boundary_preserves_order_and_count(_proxy_env, monkeypatch):
    transport, batch_sizes = _mock_transport()
    monkeypatch.setattr(embed_module, "_transport_override", transport)

    texts = ["x" * (i + 1) for i in range(300)]  # lengths 1..300, distinct per position
    vectors = embed_texts(texts)

    assert batch_sizes == [128, 128, 44]  # 300 inputs -> 3 requests of ~128
    assert len(vectors) == 300
    assert [v[0] for v in vectors] == [float(i + 1) for i in range(300)]


def test_embed_texts_resorts_out_of_order_index_fields(_proxy_env, monkeypatch):
    transport, _ = _mock_transport(shuffle=True)
    monkeypatch.setattr(embed_module, "_transport_override", transport)

    texts = ["a", "bb", "ccc", "dddd"]
    vectors = embed_texts(texts)

    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# retrieve_chunks
# ---------------------------------------------------------------------------


def test_retrieve_chunks_scores_by_similarity_and_scopes_by_account(
    db_session: Session, monkeypatch
):
    account_a = Account(name="Acme")
    account_b = Account(name="Globex")
    db_session.add_all([account_a, account_b])
    db_session.flush()

    doc_a = _make_document(db_session, account_id=account_a.id, raw_text="doc a text")
    doc_b = _make_document(db_session, account_id=account_b.id, raw_text="doc b text")

    close = Chunk(document_id=doc_a.id, text="close", char_start=0, char_end=5,
                  embedding=pack_embedding([1.0, 0.0]))
    far = Chunk(document_id=doc_a.id, text="far", char_start=0, char_end=3,
                embedding=pack_embedding([0.0, 1.0]))
    other_account = Chunk(document_id=doc_b.id, text="other", char_start=0, char_end=5,
                          embedding=pack_embedding([1.0, 0.0]))
    db_session.add_all([close, far, other_account])
    db_session.flush()

    monkeypatch.setattr("atb.qa.retrieval.embed_texts", lambda texts: [[1.0, 0.0]])

    results = retrieve_chunks(db_session, "query", account_id=account_a.id, top_k=6)

    assert [r.chunk.text for r in results] == ["close", "far"]
    assert results[0].score > results[1].score


def test_retrieve_chunks_respects_top_k(db_session: Session, monkeypatch):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="text")
    for i in range(5):
        db_session.add(
            Chunk(
                document_id=doc.id,
                text=f"chunk {i}",
                char_start=0,
                char_end=1,
                embedding=pack_embedding([1.0, 0.0]),
            )
        )
    db_session.flush()

    monkeypatch.setattr("atb.qa.retrieval.embed_texts", lambda texts: [[1.0, 0.0]])
    results = retrieve_chunks(db_session, "query", account_id=account.id, top_k=2)
    assert len(results) == 2


def test_retrieve_chunks_skips_unembedded_chunks(db_session: Session, monkeypatch):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="text")
    db_session.add(Chunk(document_id=doc.id, text="no embedding", char_start=0, char_end=1))
    db_session.flush()

    monkeypatch.setattr("atb.qa.retrieval.embed_texts", lambda texts: [[1.0, 0.0]])
    results = retrieve_chunks(db_session, "query", account_id=account.id, top_k=6)
    assert results == []


# ---------------------------------------------------------------------------
# run_indexing
# ---------------------------------------------------------------------------


def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 0.0] for t in texts]


def test_run_indexing_chunks_and_embeds_eligible_documents(db_session: Session, monkeypatch):
    monkeypatch.setattr("atb.qa.pipeline.embed_texts", _fake_embed_texts)
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="a" * 250)
    db_session.flush()

    summary = run_indexing(db_session, chunk_size=100, chunk_overlap=20)

    assert summary.indexed == 1
    assert summary.chunks_written > 0
    chunks = db_session.execute(select(Chunk).where(Chunk.document_id == doc.id)).scalars().all()
    assert len(chunks) == summary.chunks_written
    assert all(c.embedding is not None for c in chunks)

    log = db_session.execute(select(IngestLog).where(IngestLog.stage == "index")).scalar_one()
    assert log.status == "ok"
    assert log.estimated_cost_usd == 0.0


def test_run_indexing_is_idempotent_without_force(db_session: Session, monkeypatch):
    monkeypatch.setattr("atb.qa.pipeline.embed_texts", _fake_embed_texts)
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    _make_document(db_session, account_id=account.id, raw_text="some note text")
    db_session.flush()

    first = run_indexing(db_session, chunk_size=100, chunk_overlap=20)
    second = run_indexing(db_session, chunk_size=100, chunk_overlap=20)

    assert first.indexed == 1
    assert second.indexed == 0


def test_run_indexing_force_rechunks_and_replaces_existing_chunks(db_session: Session, monkeypatch):
    monkeypatch.setattr("atb.qa.pipeline.embed_texts", _fake_embed_texts)
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="some note text")
    db_session.flush()

    run_indexing(db_session, chunk_size=100, chunk_overlap=20)

    summary = run_indexing(db_session, chunk_size=100, chunk_overlap=20, force=True)

    assert summary.indexed == 1
    chunks = db_session.execute(select(Chunk).where(Chunk.document_id == doc.id)).scalars().all()
    assert len(chunks) == 1
    logs = db_session.execute(select(IngestLog).where(IngestLog.stage == "index")).scalars().all()
    assert len(logs) == 2


def test_run_indexing_ignores_unresolved_documents(db_session: Session, monkeypatch):
    monkeypatch.setattr("atb.qa.pipeline.embed_texts", _fake_embed_texts)
    _make_document(db_session, account_id=None, raw_text="unresolved note")
    db_session.flush()

    summary = run_indexing(db_session, chunk_size=100, chunk_overlap=20)
    assert summary.indexed == 0


# ---------------------------------------------------------------------------
# run_ask (fake anthropic client, no live API calls)
# ---------------------------------------------------------------------------


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0


@dataclass
class _FakeToolUseBlock:
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeResponse:
    content: list[_FakeToolUseBlock]
    usage: _FakeUsage


class _FakeMessages:
    """Returns queued responses in call order -- run_ask calls route_question
    then (unless declined) answer_question, always in that order."""

    def __init__(self, results: list):
        self._results = list(results)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        result = self._results.pop(0)
        block = _FakeToolUseBlock(input=result.model_dump(mode="json"))
        return _FakeResponse(content=[block], usage=_FakeUsage())


@dataclass
class _FakeClient:
    messages: _FakeMessages


def _settings() -> Settings:
    return Settings()


def test_run_ask_raises_for_unknown_account(db_session: Session):
    client = _FakeClient(messages=_FakeMessages([]))
    with pytest.raises(AccountNotFoundError):
        run_ask(db_session, client, question="who?", account_name="Nope Inc", settings=_settings())


def test_run_ask_declines_unsupported_crm_without_calling_answer_question(db_session: Session):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()

    routing = RoutingDecision(category="unsupported_crm", reason="asks about renewal date")
    client = _FakeClient(messages=_FakeMessages([routing]))

    result = run_ask(
        db_session, client, question="when does their contract renew?",
        account_name="Acme", settings=_settings(),
    )

    assert result.category == "unsupported_crm"
    assert result.answer.can_answer is False
    assert client.messages.calls == 1  # only routing, never answer_question

    log = db_session.execute(select(IngestLog).where(IngestLog.stage == "answer")).scalar_one()
    assert log.status == "ok"
    assert log.estimated_cost_usd is not None and log.estimated_cost_usd > 0


def test_run_ask_structured_never_retrieves_chunks(db_session: Session, monkeypatch):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()

    def _boom(*args, **kwargs):
        raise AssertionError("retrieve_chunks should not be called for structured questions")

    monkeypatch.setattr("atb.qa.pipeline.retrieve_chunks", _boom)

    routing = RoutingDecision(category="structured", reason="asks about contacts")
    answer = Answer(can_answer=True, answer_text="Jane Doe is the key contact.", citations=[])
    client = _FakeClient(messages=_FakeMessages([routing, answer]))

    result = run_ask(
        db_session, client, question="who are the key contacts?",
        account_name="Acme", settings=_settings(),
    )

    assert result.category == "structured"
    assert result.retrieved_chunks == []
    assert client.messages.calls == 2


def test_run_ask_synthesis_retrieves_chunks(db_session: Session, monkeypatch):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="The migration is on track.")
    db_session.add(
        Chunk(
            document_id=doc.id,
            text="The migration is on track.",
            char_start=0,
            char_end=27,
            embedding=pack_embedding([1.0, 0.0]),
        )
    )
    db_session.flush()

    monkeypatch.setattr("atb.qa.retrieval.embed_texts", lambda texts: [[1.0, 0.0]])

    routing = RoutingDecision(category="synthesis", reason="needs note summary")
    answer = Answer(
        can_answer=True,
        answer_text="The migration is on track.",
        citations=[Citation(document_id=doc.id, quote="The migration is on track.")],
    )
    client = _FakeClient(messages=_FakeMessages([routing, answer]))

    result = run_ask(
        db_session, client, question="how is the migration going?",
        account_name="Acme", settings=_settings(),
    )

    assert result.category == "synthesis"
    assert len(result.retrieved_chunks) == 1
    assert result.answer.citations[0].char_start == 0
    assert result.answer.citations[0].char_end == len("The migration is on track.")


def test_run_ask_resolves_citation_span_to_none_when_quote_not_found(db_session: Session):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()
    doc = _make_document(db_session, account_id=account.id, raw_text="Some unrelated text.")
    db_session.flush()

    routing = RoutingDecision(category="structured", reason="looking up facts")
    answer = Answer(
        can_answer=True,
        answer_text="claim",
        citations=[Citation(document_id=doc.id, quote="text that never appears")],
    )
    client = _FakeClient(messages=_FakeMessages([routing, answer]))

    result = run_ask(
        db_session, client, question="anything?", account_name="Acme", settings=_settings()
    )

    assert result.answer.citations[0].char_start is None
    assert result.answer.citations[0].char_end is None


def test_run_ask_logs_exactly_one_answer_ingest_log_row(db_session: Session):
    account = Account(name="Acme")
    db_session.add(account)
    db_session.flush()

    routing = RoutingDecision(category="structured", reason="looking up facts")
    answer = Answer(can_answer=True, answer_text="ok", citations=[])
    client = _FakeClient(messages=_FakeMessages([routing, answer]))

    run_ask(db_session, client, question="anything?", account_name="Acme", settings=_settings())

    logs = db_session.execute(select(IngestLog).where(IngestLog.stage == "answer")).scalars().all()
    assert len(logs) == 1
    assert logs[0].estimated_cost_usd is not None
