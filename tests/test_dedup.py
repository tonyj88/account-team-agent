"""content_hash: whitespace-only differences must hash identically (plan
Verification 1 -- re-running ingest against an unchanged folder must add
nothing), while any actual content change must not."""

from __future__ import annotations

from atb.normalize.dedup import content_hash


def test_whitespace_only_differences_hash_identically():
    a = content_hash("Hello   world\n\nfoo")
    b = content_hash("Hello world\r\nfoo   ")
    assert a == b


def test_different_content_hashes_differently():
    assert content_hash("Hello world") != content_hash("Totally different text")


def test_hash_is_deterministic():
    text = "Some meeting notes about Acme Corp."
    assert content_hash(text) == content_hash(text)
