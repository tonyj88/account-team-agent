# Account Team Bot

A shared "brain" for a small account team (AE, CSM, SE, TAMs) so anyone can
ask plain-language questions about a customer — key contacts, renewal date,
open support cases, action items owed — instead of relying on whoever
happened to attend a given meeting.

It centralizes scattered meeting notes and transcripts (Obsidian, plain
files, exported docs, Terret scribe transcripts, Teams Copilot recaps) into
one place, extracts structured facts with an LLM, and answers questions with
citations back to the source note.

The long-term goal is to keep leadership's Account Plan document filled in
and refreshed per account, with every field cited to a source.

- **[docs/PLAN.md](docs/PLAN.md)** — the design and phased plan.
- **[CHECKPOINT.md](CHECKPOINT.md)** — current status and the **Handoff**
  section (next tasks and which subagent to use). Start there when picking
  this project back up.
- **[CLAUDE.md](CLAUDE.md)** — how Claude Code sessions work on this repo.

## Design principles

- **Graceful degradation.** Every Microsoft/Salesforce integration is a
  pluggable adapter with a zero-permission fallback. No permission grant is
  on the critical path — permission requests are historically the biggest
  risk to a project like this.
- **Provenance over confidence.** Every extracted fact stores the document
  and character span it came from, so every answer is citable. An uncited
  answer about a customer commitment is worse than no answer.
- **Structured questions skip retrieval.** Questions about recorded facts
  ("who are the key contacts", "what do we owe them") are answered from
  extracted relational data only; just synthesis questions ("summarize our
  last call") pull note excerpts via embeddings. Sending a deterministic
  question through RAG is how you get a confidently wrong answer. (Both
  paths still use an LLM to phrase the answer; CRM questions like "when's
  the renewal" are declined until the CRM adapter lands.)
- **Disagreement is signal.** The same meeting can arrive from multiple
  sources (Terret vs. a teammate's own notes); near-duplicates are kept
  separately and linked, not silently collapsed.

## Stack

Python 3.13, `uv`, SQLAlchemy 2.0 + SQLite (+ vector search over packed
embeddings), Typer + Rich CLI, Anthropic SDK (Sonnet 5 for
extraction/answers, Haiku 4.5 for routing), pytest, ruff.

## Layout

```
src/atb/
  models.py       SQLAlchemy models: Account, Contact, Document, Chunk,
                   ActionItem, Meeting, AccountAlias, IngestLog
  config.py        typed settings / feature flags
  store/           session management, storage
  ingest/          SourceConnector protocol + folder/Obsidian connectors
  normalize/       md/docx/pdf/eml/html -> Document, plus dedup
  resolve/         document -> Account, alias table, review queue
  extract/         LLM structured extraction with provenance + retry logic
  redact.py        secret redaction, applied at ingest before hashing/storage
  qa/              embeddings, retrieval, structured + synthesis answers
  crm/             CrmProvider protocol (CSV-stub adapter; Salesforce not built)
  api/, channels/  web app / bot surfaces (not yet built)
  cli.py           Typer CLI entry point
tests/
```

## Getting started

```bash
uv sync
uv run atb --help
uv run pytest
```

Customer data and credentials are gitignored (`data/`, `*.sqlite*`,
`config.toml`) — never commit them.

## Common commands

```bash
uv run atb ingest              # pull in new documents from configured sources
uv run atb extract             # run LLM extraction over ingested documents
uv run atb qa index            # (re)build the embedding index
uv run atb ask "<question>" --account <name>
uv run atb redact scan         # dry-run secret scan, no DB access
```

Run `uv run atb --help` for the full command list, including the review
queue for unresolved account matches.
