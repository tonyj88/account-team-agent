"""Normalize a RawDocument (any format) into plain text plus metadata.

One normalize() dispatches by extension so ingest connectors never need to
know about docx/pdf parsing, and extraction/resolution never need to know
about file formats -- both only ever see NormalizedDocument.
"""

from __future__ import annotations

import email
import email.policy
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path

import frontmatter

from atb.ingest.base import RawDocument


@dataclass
class NormalizedDocument:
    text: str
    title: str | None = None
    author: str | None = None
    # Merged from RawDocument.hints plus anything the format itself carries
    # (frontmatter tags, email From:/Subject:) -- resolve/ consumes this,
    # never raw_text, so every format contributes hints the same way.
    hints: dict[str, str] = field(default_factory=dict)


class UnsupportedFormatError(Exception):
    """Raised for a file extension normalize/ has no handler for. Callers
    should log and route to IngestLog with status="error" rather than crash
    the whole ingest run over one bad file."""


def normalize(doc: RawDocument) -> NormalizedDocument:
    ext = Path(doc.filename).suffix.lower()
    hints = dict(doc.hints or {})

    if ext == ".md":
        return _normalize_markdown(doc, hints)
    if ext == ".txt":
        return NormalizedDocument(
            text=doc.raw_text or "", title=Path(doc.filename).stem, hints=hints
        )
    if ext in (".html", ".htm"):
        return _normalize_html(doc, hints)
    if ext == ".eml":
        return _normalize_eml(doc, hints)
    if ext == ".docx":
        return _normalize_docx(doc, hints)
    if ext == ".pdf":
        return _normalize_pdf(doc, hints)

    raise UnsupportedFormatError(f"no normalizer for {doc.filename!r} ({ext})")


def _normalize_markdown(doc: RawDocument, hints: dict[str, str]) -> NormalizedDocument:
    post = frontmatter.loads(doc.raw_text or "")

    # Frontmatter is the strongest resolution signal we have (plan: Entity
    # resolution order is frontmatter/tag first) -- surface `customer` and
    # `tags` explicitly so resolve/ doesn't need to re-parse the raw post.
    customer = post.get("customer")
    if isinstance(customer, str):
        hints["frontmatter_customer"] = customer

    tags = post.get("tags")
    if isinstance(tags, str):
        tags = [tags]
    if isinstance(tags, list):
        customer_tags = [t for t in tags if isinstance(t, str) and t.startswith("customer/")]
        if customer_tags:
            hints["frontmatter_customer_tag"] = customer_tags[0].removeprefix("customer/")

    title = post.get("title") if isinstance(post.get("title"), str) else Path(doc.filename).stem
    author = post.get("author") if isinstance(post.get("author"), str) else doc.author

    return NormalizedDocument(text=post.content, title=title, author=author, hints=hints)


def _normalize_html(doc: RawDocument, hints: dict[str, str]) -> NormalizedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(doc.raw_text or "", "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else Path(doc.filename).stem
    text = soup.get_text(separator="\n", strip=True)
    return NormalizedDocument(text=text, title=title, author=doc.author, hints=hints)


def _normalize_eml(doc: RawDocument, hints: dict[str, str]) -> NormalizedDocument:
    raw = doc.raw_bytes if doc.raw_bytes is not None else (doc.raw_text or "").encode("utf-8")
    msg: Message = email.message_from_bytes(raw, policy=email.policy.default)

    subject = msg.get("Subject", Path(doc.filename).stem)
    sender = msg.get("From", doc.author)
    if sender:
        hints["email_from"] = str(sender)

    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body is not None else ""

    return NormalizedDocument(
        text=text, title=str(subject), author=str(sender) if sender else None, hints=hints
    )


def _normalize_docx(doc: RawDocument, hints: dict[str, str]) -> NormalizedDocument:
    import io

    import docx

    if doc.raw_bytes is None:
        raise UnsupportedFormatError(f"{doc.filename}: docx requires raw_bytes")

    d = docx.Document(io.BytesIO(doc.raw_bytes))
    text = "\n".join(p.text for p in d.paragraphs)
    return NormalizedDocument(
        text=text, title=Path(doc.filename).stem, author=doc.author, hints=hints
    )


def _normalize_pdf(doc: RawDocument, hints: dict[str, str]) -> NormalizedDocument:
    import io

    import pypdf

    if doc.raw_bytes is None:
        raise UnsupportedFormatError(f"{doc.filename}: pdf requires raw_bytes")

    reader = pypdf.PdfReader(io.BytesIO(doc.raw_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return NormalizedDocument(
        text=text, title=Path(doc.filename).stem, author=doc.author, hints=hints
    )
