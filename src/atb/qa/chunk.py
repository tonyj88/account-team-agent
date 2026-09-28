"""Splits Document.raw_text into fixed-size, overlapping character windows.

Deliberately dumb (no sentence-awareness) for this v0 -- a small vault's
notes are short enough that a mid-sentence split rarely costs a retrieval
match, and it keeps the function trivially unit-testable.
"""

from __future__ import annotations


def chunk_text(text: str, *, chunk_size: int, chunk_overlap: int) -> list[tuple[int, int]]:
    """Returns (char_start, char_end) windows covering `text`."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [(0, len(text))]

    step = chunk_size - chunk_overlap
    windows: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        windows.append((start, end))
        if end == len(text):
            break
        start += step
    return windows
