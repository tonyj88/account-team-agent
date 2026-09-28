"""resolve/core.py: the rule cascade must hit in the documented order and,
critically, must never guess -- an unresolved or genuinely ambiguous
document must come back with account_id=None and candidates for the human
review queue (plan: Entity resolution)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from atb.models import Account, AccountAlias
from atb.normalize.core import NormalizedDocument
from atb.resolve.core import resolve


def _seed(session: Session) -> tuple[int, int]:
    acme = Account(name="Acme Corp")
    globex = Account(name="Globex Inc")
    session.add_all([acme, globex])
    session.flush()
    session.add(AccountAlias(account_id=acme.id, alias="acme.com", kind="email_domain"))
    session.add(AccountAlias(account_id=acme.id, alias="acme", kind="name"))
    session.flush()
    return acme.id, globex.id


def test_exact_frontmatter_customer_match(db_session):
    acme_id, _ = _seed(db_session)
    doc = NormalizedDocument(text="...", hints={"frontmatter_customer": "Acme Corp"})
    result = resolve(doc, db_session)
    assert result.account_id == acme_id
    assert result.matched_via == "frontmatter_customer"


def test_customer_tag_matches_existing_alias(db_session):
    acme_id, _ = _seed(db_session)
    doc = NormalizedDocument(text="...", hints={"frontmatter_customer_tag": "acme"})
    result = resolve(doc, db_session)
    assert result.account_id == acme_id
    assert result.matched_via == "frontmatter_customer_tag"


def test_folder_hint_exact_match(db_session):
    _, globex_id = _seed(db_session)
    doc = NormalizedDocument(text="...", hints={"folder": "Globex Inc"})
    result = resolve(doc, db_session)
    assert result.account_id == globex_id
    assert result.matched_via == "folder"


def test_email_domain_match(db_session):
    acme_id, _ = _seed(db_session)
    doc = NormalizedDocument(text="...", hints={"email_from": "Jane Doe <jane@acme.com>"})
    result = resolve(doc, db_session)
    assert result.account_id == acme_id
    assert result.matched_via == "email_domain"


def test_fuzzy_match_above_threshold(db_session):
    acme_id, _ = _seed(db_session)
    doc = NormalizedDocument(text="...", hints={"frontmatter_customer": "Acme Corp."})
    result = resolve(doc, db_session)
    assert result.account_id == acme_id
    assert result.matched_via == "fuzzy"


def test_unresolved_document_returns_candidates_not_a_guess(db_session):
    _seed(db_session)
    doc = NormalizedDocument(text="...", title="Random unrelated note", hints={})
    result = resolve(doc, db_session)
    assert result.account_id is None
    assert result.candidates is not None
    assert result.reason is not None
    # Falls back to title since no other hint is present -- this is exactly
    # the case a CLI's alias suggestion must handle without assuming a
    # frontmatter/folder hint is always what is available.
    assert result.attempted_text == "Random unrelated note"


def test_unresolved_attempted_text_prefers_hint_over_title(db_session):
    """The review-queue alias suggestion must remember the ambiguous hint
    text verbatim, not the document title -- a future note repeating the
    same hint will not repeat the title (see cli.py review_resolve)."""
    _seed(db_session)
    doc = NormalizedDocument(
        text="...",
        title="note",
        hints={"frontmatter_customer": "mystery vendor call"},
    )
    result = resolve(doc, db_session)
    assert result.account_id is None
    assert result.attempted_text == "mystery vendor call"


def test_genuinely_different_name_is_never_guessed(db_session):
    _seed(db_session)
    doc = NormalizedDocument(
        text="...", hints={"frontmatter_customer": "Totally Different Company"}
    )
    result = resolve(doc, db_session)
    assert result.account_id is None


def test_no_accounts_at_all_returns_unresolved_without_crashing(db_session):
    doc = NormalizedDocument(text="...", hints={"frontmatter_customer": "Acme Corp"})
    result = resolve(doc, db_session)
    assert result.account_id is None
    assert result.candidates == []
