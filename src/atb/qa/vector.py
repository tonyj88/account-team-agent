"""Packing/scoring for chunk embeddings, stored as float32 blobs on Chunk.

Pure stdlib (`array`, no numpy/fastembed import) so this module stays
importable -- and testable -- without the `search` extra installed.
"""

from __future__ import annotations

import array


def pack_embedding(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def unpack_embedding(blob: bytes) -> list[float]:
    return array.array("f", blob).tolist()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
