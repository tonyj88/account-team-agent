"""Embeddings via the org's OpenAI-compatible LLM proxy -- a real API call
and real per-query cost now, unlike the local fastembed path this replaced
(huggingface.co is hard-blocked by corporate Zscaler and IT will not
allowlist it -- see MEMORY checkpoint 2026-09-18 Phase 4).

Reads ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN -- the same env vars the
anthropic SDK authenticates with -- so no separate credential is needed.
Model + optional dimensions override come from QaConfig (config.py); native
1536-dim text-embedding-3-small is the default, not truncated.

Batches internally (~128 inputs/request) and sorts each response by its
`index` field rather than trusting arrival order -- callers zip vectors
against chunk windows with strict=True (qa/pipeline.py:79), so any
reordering or count mismatch is a silent data-corruption bug.
"""

from __future__ import annotations

import os
import time

import httpx

from atb.config import get_settings

_BATCH_SIZE = 128
_TIMEOUT = 30.0
_MAX_ATTEMPTS = 5
_RETRY_STATUS = {429, 500, 502, 503, 504}

# Test seam: set to an httpx.MockTransport so tests never hit the network.
# Production leaves this None, which makes httpx.Client use its real transport.
_transport_override: httpx.BaseTransport | None = None


class EmbeddingConfigError(RuntimeError):
    """Raised when ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN aren't set --
    an actionable error instead of a bare KeyError, since both are required
    to reach the embeddings proxy."""


def _credentials() -> tuple[str, str]:
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if not base_url or not token:
        raise EmbeddingConfigError(
            "ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN must both be set (the same "
            "env vars the anthropic SDK authenticates with) to call the embeddings proxy."
        )
    return base_url.rstrip("/"), token


def _embed_batch(
    client: httpx.Client,
    batch: list[str],
    *,
    base_url: str,
    token: str,
    model: str,
    dimensions: int | None,
) -> list[list[float]]:
    """POSTs one batch, retrying on 429/5xx and transport errors with
    exponential backoff. Returns vectors re-sorted by the response's
    `index` field -- see module docstring on why order can't be trusted."""
    payload: dict = {"model": model, "input": batch}
    if dimensions is not None:
        payload["dimensions"] = dimensions

    last_exc: Exception = RuntimeError("unreachable: _MAX_ATTEMPTS must be >= 1")
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.post(
                f"{base_url}/v1/embeddings",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.TransportError as exc:
            last_exc = exc
        else:
            if response.status_code in _RETRY_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"embeddings proxy returned {response.status_code}",
                    request=response.request,
                    response=response,
                )
            else:
                response.raise_for_status()
                rows = sorted(response.json()["data"], key=lambda row: row["index"])
                return [row["embedding"] for row in rows]
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(0.5 * (2**attempt))
    raise last_exc


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Batched embedding via the proxy. Returns one float vector per input,
    same order."""
    if not texts:
        return []

    base_url, token = _credentials()
    settings = get_settings()
    model = settings.qa.embedding_model
    dimensions = settings.qa.embedding_dimensions

    vectors: list[list[float]] = []
    with httpx.Client(timeout=_TIMEOUT, transport=_transport_override) as client:
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            vectors.extend(
                _embed_batch(
                    client,
                    batch,
                    base_url=base_url,
                    token=token,
                    model=model,
                    dimensions=dimensions,
                )
            )
    return vectors
