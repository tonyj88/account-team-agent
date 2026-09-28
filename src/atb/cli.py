"""Operator CLI. `atb ingest` runs the zero-permission connectors; `atb
review` works the human queue that entity resolution deliberately falls
back to instead of guessing (plan: Entity resolution)."""

from __future__ import annotations

from pathlib import Path

import anthropic
import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from atb.config import get_settings
from atb.extract.pipeline import run_extraction
from atb.ingest.folder import FolderConnector
from atb.ingest.obsidian import ObsidianConnector
from atb.ingest.pipeline import run_ingest
from atb.models import Account, AccountAlias, Document, ReviewQueueItem, _utcnow
from atb.normalize.core import UnsupportedFormatError, normalize
from atb.qa.pipeline import AccountNotFoundError, run_ask, run_indexing
from atb.redact import redact_text
from atb.store.db import init_db, session_scope

app = typer.Typer(help="Account Team Bot operator CLI")
review_app = typer.Typer(help="Work the entity-resolution review queue")
accounts_app = typer.Typer(help="Manage accounts")
qa_app = typer.Typer(help="Index documents for retrieval and ask questions")
redact_app = typer.Typer(help="Review the secret-redaction heuristics before trusting them")
app.add_typer(review_app, name="review")
app.add_typer(accounts_app, name="accounts")
app.add_typer(qa_app, name="qa")
app.add_typer(redact_app, name="redact")

console = Console()


def _ensure_db() -> None:
    settings = get_settings()
    init_db(settings.db_path)


@app.command()
def ingest() -> None:
    """Run every configured connector once (folder + obsidian today;
    email/graph_teams join this list as their config.enabled flips true --
    see plan: Ingestion, one protocol many connectors)."""
    settings = get_settings()
    init_db(settings.db_path)

    connectors = [
        FolderConnector(root=settings.intake.folder.path, enabled=settings.intake.folder.enabled),
        ObsidianConnector(
            vault_path=settings.intake.obsidian.vault_path or Path("."),
            enabled=settings.intake.obsidian.enabled,
        ),
    ]

    with session_scope() as session:
        summary = run_ingest(
            connectors, session, redaction_enabled=settings.redaction.enabled
        )

    console.print(
        f"[green]ingested {summary.ingested}[/green]  "
        f"[yellow]duplicates {summary.duplicates}[/yellow]  "
        f"[yellow]unresolved -> review queue {summary.unresolved}[/yellow]  "
        f"[red]errors {summary.errors}[/red]"
    )
    for detail in summary.error_details:
        console.print(f"  [red]error:[/red] {detail}")


@app.command()
def extract(
    limit: int | None = typer.Option(
        None, help="Extract at most this many documents this run."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Call the model and report cost, but write nothing to the DB."
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract documents already at the current extraction version too.",
    ),
) -> None:
    """Run LLM extraction (contacts, action items, decisions, risks) over
    every resolved document not yet extracted. `anthropic.Anthropic()` picks
    up credentials from ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN
    automatically -- no key is passed explicitly (plan: Phase 3)."""
    settings = get_settings()
    init_db(settings.db_path)
    client = anthropic.Anthropic()

    with session_scope() as session:
        summary = run_extraction(
            session,
            client,
            model=settings.models.extract,
            limit=limit,
            dry_run=dry_run,
            force=force,
        )

    console.print(
        f"[green]extracted {summary.extracted}[/green]  "
        f"[yellow]skipped (dry-run) {summary.skipped}[/yellow]  "
        f"[red]errors {summary.errors}[/red]  "
        f"[cyan]est. cost ${summary.total_estimated_cost_usd:.4f}[/cyan]"
    )
    for detail in summary.error_details:
        console.print(f"  [red]error:[/red] {detail}")


@review_app.command("list")
def review_list() -> None:
    """Show every unresolved document waiting for a human to say which
    account it belongs to."""
    _ensure_db()
    with session_scope() as session:
        rows = session.execute(
            select(ReviewQueueItem, Document)
            .join(Document, ReviewQueueItem.document_id == Document.id)
            .where(ReviewQueueItem.resolved_at.is_(None))
            .order_by(ReviewQueueItem.created_at)
        ).all()

        if not rows:
            console.print("[green]review queue is empty[/green]")
            return

        table = Table(title="Review queue")
        table.add_column("queue id")
        table.add_column("document")
        table.add_column("origin")
        table.add_column("attempted hint")
        table.add_column("candidates")
        for item, doc in rows:
            table.add_row(
                str(item.id),
                doc.title or "(untitled)",
                doc.origin_path,
                item.attempted_hint or "(none)",
                ", ".join(item.candidate_names or []) or "(none)",
            )
        console.print(table)


@review_app.command("resolve")
def review_resolve(
    queue_id: int,
    account_name: str = typer.Argument(..., help="Exact existing account name to assign"),
    alias: str | None = typer.Option(
        None, help="Text to remember as an alias for this account (default: the document title)"
    ),
    create: bool = typer.Option(
        False, "--create", help="Create the account if it does not already exist"
    ),
) -> None:
    """Assign a queued document to an account and, crucially, write an
    AccountAlias so the same wording resolves automatically next time --
    the queue should shrink for a given customer's naming quirks, not
    recur (plan: "the system learns each customer's naming variants
    once")."""
    _ensure_db()
    with session_scope() as session:
        item = session.get(ReviewQueueItem, queue_id)
        if item is None or item.resolved_at is not None:
            console.print(f"[red]no open review item with id {queue_id}[/red]")
            raise typer.Exit(code=1)

        document = session.get(Document, item.document_id)
        assert document is not None

        account = session.execute(
            select(Account).where(Account.name == account_name)
        ).scalar_one_or_none()
        if account is None:
            if not create:
                console.print(
                    f"[red]no account named {account_name!r}. Pass --create to make one.[/red]"
                )
                raise typer.Exit(code=1)
            account = Account(name=account_name)
            session.add(account)
            session.flush()

        document.account_id = account.id
        item.resolved_at = _utcnow()

        # Prefer the exact hint text resolve() failed to match over the
        # document title -- the title is usually just the filename stem and
        # will not generally match the wording a future ambiguous note
        # repeats, whereas attempted_hint is that wording verbatim.
        alias_text = (alias or item.attempted_hint or document.title or account_name).strip()
        if alias_text and alias_text.casefold() != account_name.casefold():
            existing_alias = session.execute(
                select(AccountAlias).where(
                    AccountAlias.alias == alias_text.casefold(), AccountAlias.kind == "name"
                )
            ).scalar_one_or_none()
            if existing_alias is None:
                session.add(
                    AccountAlias(account_id=account.id, alias=alias_text.casefold(), kind="name")
                )

        console.print(
            f"[green]resolved[/green] queue item {queue_id} -> account {account.name!r} "
            f"(alias recorded: {alias_text!r})"
        )


@accounts_app.command("add")
def accounts_add(name: str) -> None:
    """Create an account up front, before any note about it arrives -- lets
    frontmatter/folder resolution hit on the first note instead of
    detouring through the review queue."""
    _ensure_db()
    with session_scope() as session:
        existing = session.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
        if existing is not None:
            console.print(f"[yellow]account {name!r} already exists (id={existing.id})[/yellow]")
            return
        account = Account(name=name)
        session.add(account)
        session.flush()
        console.print(f"[green]created account {name!r} (id={account.id})[/green]")


@accounts_app.command("list")
def accounts_list() -> None:
    _ensure_db()
    with session_scope() as session:
        accounts = session.execute(select(Account).order_by(Account.name)).scalars().all()
        if not accounts:
            console.print("[yellow]no accounts yet[/yellow]")
            return
        table = Table(title="Accounts")
        table.add_column("id")
        table.add_column("name")
        for a in accounts:
            table.add_row(str(a.id), a.name)
        console.print(table)


@qa_app.command("index")
def qa_index(
    limit: int | None = typer.Option(None, help="Index at most this many documents this run."),
    force: bool = typer.Option(
        False, "--force", help="Re-chunk and re-embed documents already indexed too."
    ),
) -> None:
    """Chunk + embed resolved documents for retrieval. Embedding now calls the
    org's proxy (qa/embed.py) -- a real API call, not the old local fastembed
    path -- so this has a (small) per-batch cost, unlike before."""
    settings = get_settings()
    init_db(settings.db_path)

    with session_scope() as session:
        summary = run_indexing(
            session,
            chunk_size=settings.qa.chunk_size,
            chunk_overlap=settings.qa.chunk_overlap,
            limit=limit,
            force=force,
        )

    console.print(
        f"[green]indexed {summary.indexed}[/green]  "
        f"[yellow]skipped {summary.skipped}[/yellow]  "
        f"[cyan]chunks written {summary.chunks_written}[/cyan]"
    )


@app.command()
def ask(
    question: str,
    account: str = typer.Option(..., "--account", help="Exact existing account name"),
) -> None:
    """Ask a question about an account, answered from what's already been
    ingested + extracted + indexed. Declines rather than guessing when the
    answer needs data this system doesn't have yet (e.g. CRM renewal date)."""
    settings = get_settings()
    init_db(settings.db_path)
    client = anthropic.Anthropic()

    with session_scope() as session:
        try:
            result = run_ask(
                session, client, question=question, account_name=account, settings=settings
            )
        except AccountNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc

        if result.answer.can_answer:
            console.print(f"[green]{result.answer.answer_text}[/green]")
        else:
            console.print(f"[yellow]{result.answer.answer_text}[/yellow]")

        for citation in result.answer.citations:
            document = session.get(Document, citation.document_id)
            origin = document.origin_path if document else "(unknown document)"
            span = (
                f"chars {citation.char_start}-{citation.char_end}"
                if citation.char_start is not None
                else "span not verified"
            )
            console.print(f"  [dim][doc #{citation.document_id}, {span}] {origin}[/dim]")

    console.print(f"[cyan]est. cost ${result.estimated_cost_usd:.4f}[/cyan]")


def _source_line_offset(raw_text: str | None, normalized_text: str) -> int:
    """redact_text() runs on the NORMALIZED text (e.g. frontmatter/HTML/etc.
    already stripped by normalize()), so its 1-indexed line numbers count
    lines of the normalized text, not the source file a human would open in
    an editor. For markdown with frontmatter, normalize() drops a leading
    block of lines, which silently shifts every reported line number.

    This locates where the normalized text begins inside the original raw
    text and returns how many source lines precede it, so the CLI can
    report line numbers a human can actually navigate to. Returns 0 (no
    shift) whenever the normalized text isn't a literal substring of the
    raw text (e.g. non-text formats like docx/pdf/html, where no single
    "source line number" is meaningful anyway)."""
    if not raw_text:
        return 0
    idx = raw_text.find(normalized_text)
    if idx == -1:
        return 0
    return raw_text.count("\n", 0, idx)


@redact_app.command("scan")
def redact_scan() -> None:
    """Dry-run: walks every configured intake source and reports what the
    redact.py heuristics WOULD remove, per file/rule/line -- writes nothing
    to the DB or to disk. This is the review mechanism for trusting the
    heuristics before `atb ingest` runs them for real (redact.py's rules are
    positional/structural, not label-word matching -- see its docstring),
    so it deliberately never touches init_db()/session_scope()."""
    settings = get_settings()
    connectors: list[FolderConnector | ObsidianConnector] = [
        FolderConnector(root=settings.intake.folder.path, enabled=settings.intake.folder.enabled),
        ObsidianConnector(
            vault_path=settings.intake.obsidian.vault_path or Path("."),
            enabled=settings.intake.obsidian.enabled,
        ),
    ]

    total_files = 0
    total_findings = 0
    rule_totals: dict[str, int] = {}

    for connector in connectors:
        for raw in connector.poll():
            try:
                normalized = normalize(raw)
            except UnsupportedFormatError:
                continue  # same files `atb ingest` would skip -- not this command's job

            result = redact_text(normalized.text)
            if not result.findings:
                continue

            line_offset = _source_line_offset(raw.raw_text, normalized.text)

            total_files += 1
            total_findings += len(result.findings)
            console.print(f"[bold]{raw.origin_path}[/bold]")
            table = Table(show_header=True, header_style="bold")
            table.add_column("source line" if line_offset else "line")
            table.add_column("rule")
            table.add_column("would-redact length")
            for finding in sorted(result.findings, key=lambda f: f.line_number):
                table.add_row(
                    str(finding.line_number + line_offset),
                    finding.rule,
                    str(finding.redacted_length),
                )
                rule_totals[finding.rule] = rule_totals.get(finding.rule, 0) + 1
            console.print(table)

    console.print(
        f"\n[cyan]{total_files} file(s) with findings, {total_findings} finding(s) total[/cyan]"
    )
    if rule_totals:
        breakdown = ", ".join(f"{rule}={n}" for rule, n in sorted(rule_totals.items()))
        console.print(f"[cyan]by rule: {breakdown}[/cyan]")
    console.print("[dim]dry-run only -- nothing was written to the DB or to disk[/dim]")


if __name__ == "__main__":
    app()
