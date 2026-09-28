"""normalize/core.py: every format must produce plain text plus the hints
resolve/ depends on. See plan Verification 1 -- these are the deterministic
layers pytest is meant to cover."""

from __future__ import annotations

import io

import pytest

from atb.ingest.base import RawDocument
from atb.models import DocumentSource
from atb.normalize.core import UnsupportedFormatError, normalize


def _doc(filename: str, **kwargs) -> RawDocument:
    return RawDocument(
        source=DocumentSource.FOLDER, origin_path=filename, filename=filename, **kwargs
    )


def test_markdown_frontmatter_customer_hint():
    text = (
        "---\ncustomer: Acme Corp\ntitle: Kickoff\nauthor: Jane Doe\n---\n\n"
        "We discussed the renewal timeline."
    )
    result = normalize(_doc("kickoff.md", raw_text=text))
    assert result.hints["frontmatter_customer"] == "Acme Corp"
    assert result.title == "Kickoff"
    assert result.author == "Jane Doe"
    assert "renewal timeline" in result.text


def test_markdown_customer_tag_hint():
    text = "---\ntags: [customer/globex, meeting-notes]\n---\nBody text."
    result = normalize(_doc("note.md", raw_text=text))
    assert result.hints["frontmatter_customer_tag"] == "globex"


def test_markdown_without_frontmatter_falls_back_to_filename_stem():
    result = normalize(_doc("plain.md", raw_text="just some text"))
    assert result.title == "plain"


def test_txt_preserves_incoming_hints():
    result = normalize(_doc("notes.txt", raw_text="hello", hints={"folder": "Acme"}))
    assert result.hints["folder"] == "Acme"
    assert result.text == "hello"


def test_html_extracts_title_and_visible_text():
    html = "<html><head><title>Recap</title></head><body><p>Hello world</p></body></html>"
    result = normalize(_doc("recap.html", raw_text=html))
    assert result.title == "Recap"
    assert "Hello world" in result.text


def test_eml_extracts_subject_and_from_hint():
    raw = (
        b"From: Jane Doe <jane@acme.com>\r\n"
        b"Subject: Meeting recap\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Action items attached.\r\n"
    )
    result = normalize(_doc("recap.eml", raw_bytes=raw))
    assert result.title == "Meeting recap"
    assert result.hints["email_from"] == "Jane Doe <jane@acme.com>"
    assert "Action items" in result.text


def test_docx_extracts_paragraph_text():
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("Quarterly business review notes.")
    buf = io.BytesIO()
    d.save(buf)
    result = normalize(_doc("qbr.docx", raw_bytes=buf.getvalue()))
    assert "Quarterly business review notes." in result.text


def test_unsupported_extension_raises():
    with pytest.raises(UnsupportedFormatError):
        normalize(_doc("data.xyz", raw_text="whatever"))
