"""Plain reads of the relational facts already extracted for an account --
no LLM, no embeddings. Kept separate from core.py/retrieval.py the same way
extract/store.py is kept separate from extract/core.py: it's the part with
real logic worth testing in isolation.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from atb.models import ActionItem, ActionItemStatus, Contact, Decision, Risk


def gather_structured_context(session: Session, account_id: int) -> str:
    """Formats every Contact/ActionItem/Decision/Risk row for `account_id`
    into a compact text block for the answer prompt."""
    contacts = session.execute(
        select(Contact).where(Contact.account_id == account_id)
    ).scalars().all()
    action_items = session.execute(
        select(ActionItem).where(ActionItem.account_id == account_id)
    ).scalars().all()
    decisions = session.execute(
        select(Decision).where(Decision.account_id == account_id)
    ).scalars().all()
    risks = session.execute(select(Risk).where(Risk.account_id == account_id)).scalars().all()

    lines: list[str] = []

    lines.append("Contacts:")
    if contacts:
        for c in contacts:
            key = " (key contact)" if c.is_key_contact else ""
            title = f", {c.title}" if c.title else ""
            lines.append(f"- {c.name}{title}{key} [document_id={c.source_document_id}]")
    else:
        lines.append("- none recorded")

    lines.append("Action items:")
    if action_items:
        for item in action_items:
            status = "" if item.status == ActionItemStatus.OPEN else f" ({item.status.value})"
            owner = f", owner: {item.owner}" if item.owner else ""
            due = f", due {item.due_date.date()}" if item.due_date else ""
            lines.append(
                f"- [{item.direction.value}]{status} {item.description}{owner}{due} "
                f"[document_id={item.document_id}]"
            )
    else:
        lines.append("- none recorded")

    lines.append("Decisions:")
    if decisions:
        for d in decisions:
            lines.append(f"- {d.description} [document_id={d.document_id}]")
    else:
        lines.append("- none recorded")

    lines.append("Risks:")
    if risks:
        for r in risks:
            lines.append(f"- {r.description} [document_id={r.document_id}]")
    else:
        lines.append("- none recorded")

    return "\n".join(lines)
