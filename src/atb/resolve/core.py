"""Entity resolution: map a NormalizedDocument to an Account.

Resolution order (plan: "Entity resolution is rule-first, with a human
queue"): explicit frontmatter/tag, then folder path, then participant email
domain, then fuzzy match against AccountAlias. Anything below the fuzzy-
match confidence threshold goes to the review queue instead of being
guessed -- a note filed under the wrong customer is worse than one filed
nowhere, and an LLM is never used here for exactly that reason.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.models import Account, AccountAlias
from atb.normalize.core import NormalizedDocument

# Below this similarity score, a name-like hint is treated as ambiguous
# rather than resolved -- tuned to require a near-exact match ("Acme Corp"
# vs "Acme Corporation") while rejecting genuinely different names
# ("Acme" vs "Ace Inc"). Revisit once real customer names show this is too
# strict or too loose.
FUZZY_MATCH_THRESHOLD = 0.82


@dataclass
class ResolutionResult:
    account_id: int | None
    matched_via: str | None  # "frontmatter_customer" | "folder" | "email_domain" | "fuzzy" | None
    candidates: list[str] | None = None  # populated only when unresolved
    reason: str | None = None
    # The hint text resolve() actually tried to match, whether it succeeded
    # or not. On an unresolved result this is what a review-queue CLI
    # should offer to remember as an AccountAlias -- it is the text a
    # future note with the same ambiguity will repeat, unlike doc.title
    # (which is usually just the filename stem and often unrelated).
    attempted_text: str | None = None


def resolve(doc: NormalizedDocument, session: Session) -> ResolutionResult:
    """Try each strategy in descending order of confidence; stop at the
    first hit. Never falls through to a guess -- an unresolved document
    returns candidates for the review queue instead."""

    for hint_key in ("frontmatter_customer", "frontmatter_customer_tag", "folder"):
        value = doc.hints.get(hint_key)
        if not value:
            continue
        account_id = _match_name_or_alias(session, value)
        if account_id is not None:
            return ResolutionResult(account_id=account_id, matched_via=hint_key)

    email_from = doc.hints.get("email_from")
    if email_from:
        domain = _extract_domain(email_from)
        if domain:
            account_id = _match_alias(session, domain, kind="email_domain")
            if account_id is not None:
                return ResolutionResult(account_id=account_id, matched_via="email_domain")

    candidate_text = (
        doc.hints.get("frontmatter_customer")
        or doc.hints.get("frontmatter_customer_tag")
        or doc.hints.get("folder")
        or doc.title
        or ""
    )
    if candidate_text:
        match = _best_fuzzy_match(session, candidate_text)
        if match is not None:
            account_id, score = match
            if score >= FUZZY_MATCH_THRESHOLD:
                return ResolutionResult(
                    account_id=account_id, matched_via="fuzzy", attempted_text=candidate_text
                )

    candidates = _top_candidates(session, candidate_text) if candidate_text else []
    return ResolutionResult(
        account_id=None,
        matched_via=None,
        candidates=candidates,
        reason=f"no confident match (hints={doc.hints!r}, title={doc.title!r})",
        attempted_text=candidate_text or None,
    )


def _all_names(session: Session) -> list[tuple[int, str]]:
    """(account_id, name) pairs from both Account.name and every alias --
    the full universe a hint can match against."""
    rows: list[tuple[int, str]] = list(session.execute(select(Account.id, Account.name)).all())
    rows += list(
        session.execute(
            select(AccountAlias.account_id, AccountAlias.alias).where(AccountAlias.kind == "name")
        ).all()
    )
    return rows


def _match_name_or_alias(session: Session, value: str) -> int | None:
    value_norm = value.strip().casefold()
    for account_id, name in _all_names(session):
        if name.strip().casefold() == value_norm:
            return account_id
    return None


def _match_alias(session: Session, value: str, *, kind: str) -> int | None:
    row = session.execute(
        select(AccountAlias.account_id).where(
            AccountAlias.kind == kind, AccountAlias.alias == value.strip().casefold()
        )
    ).first()
    return row[0] if row else None


def _best_fuzzy_match(session: Session, candidate: str) -> tuple[int, float] | None:
    names = _all_names(session)
    if not names:
        return None
    candidate_norm = candidate.strip().casefold()
    scored = [
        (account_id, difflib.SequenceMatcher(None, candidate_norm, name.casefold()).ratio())
        for account_id, name in names
    ]
    account_id, score = max(scored, key=lambda pair: pair[1])
    return account_id, score


def _top_candidates(session: Session, candidate: str, limit: int = 3) -> list[str]:
    names = _all_names(session)
    if not names:
        return []
    candidate_norm = candidate.strip().casefold()
    scored = sorted(
        (
            (name, difflib.SequenceMatcher(None, candidate_norm, name.casefold()).ratio())
            for _, name in names
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [name for name, _ in scored[:limit]]


def _extract_domain(email_address: str) -> str | None:
    if "@" not in email_address:
        return None
    # Handles "Jane Doe <jane@acme.com>" as well as a bare address.
    addr = email_address.strip().rstrip(">").split("<")[-1]
    return addr.split("@")[-1].strip().casefold() or None
