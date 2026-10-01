# Account Team Bot

Fills out leadership's **Account Plan** (`account_plan.docx`) for any account with the
most accurate, freshest information available. Every value cites its source, and
anything uncertain is flagged for human approval.

Tony runs it from **Claude Code** on his laptop. Claude gathers the evidence through
connectors, and a small deterministic Python toolkit decides which value wins, checks
the evidence, and fills in the template.

```
Salesforce (via ConductorOne) ─┐
M365: Teams transcripts, email,├─► /account-plan <account> ─► candidates ─► reconcile ─► validate ─► account_plan.docx
      chats, calendar, SharePoint│      (Claude skill)          (dated,     (newest       (quotes      + evidence.md
SuperDuck scans · Confluence   │                                quoted)     evidence     verbatim,    + sf_drift.md
Obsidian side notes ───────────┘                                            wins)        approvals)
```

**Key rules**
- **Newest dated evidence wins.** Salesforce contacts and notes go stale, so a newer
  Teams transcript or email overrides them. That value is marked ⚠ needs approval and
  listed in `sf_drift.md`, so Salesforce can be updated by hand.
- **System-of-record fields stay with Salesforce:** ARR (`Account.ACV_Current__c`),
  contract dates, and products purchased. A conversation can only flag a change.
- **Read-only:** the bot never writes to Salesforce, and never sends email or Teams
  messages. A SharePoint upload always asks first.
- **Provenance:** every value cites a Salesforce record and field, or a document plus a
  verbatim quote and date.

## Where to start a session
1. Read **[CHECKPOINT.md](CHECKPOINT.md)**: the Handoff section says what's next and
   which model to start on.
2. Design: **[docs/PLAN.md](docs/PLAN.md)**. Connector findings:
   **[docs/R0_DISCOVERY.md](docs/R0_DISCOVERY.md)**.
3. How sessions work: **[CLAUDE.md](CLAUDE.md)**.

## Roadmap
Temporary section, to be removed when the project is done. ✅ done · 🟡 in progress · ⬜ not started · ⏸ later

| # | Milestone | Start session on | Status |
|---|---|---|---|
| R0 | Connector discovery: M365, Salesforce field history, transcripts | Opus 5.5 | ✅ |
| R0b | SuperDuck + Atlassian discovery; ARR source = Salesforce ACV | Opus 5.5 | ✅ |
| R1 | Update CLAUDE.md and agent definitions to the new design; model pins → 5.5; guardrail scope covers M365 writes | **Sonnet 5.5** | ⬜ **next** |
| R2 | Plan schema + candidates.json; `reconcile` (freshness rule), `validate`, `derive`, `transcript clean` + tests | **Opus 5.5** to design → **Sonnet 5.5** to build | ⬜ |
| R3 | `render` (docx skill + field→cell map), evidence file, `sf_drift.md`, `diff` | **Sonnet 5.5** | ⬜ |
| R4 | `/account-plan` skill + C1/M365 write-guard hook; live Agilent run | **Opus 5.5** | ⬜ |
| R5 | `/plan-review`, `/plan-due`, weekly scheduled task | **Sonnet 5.5** | ⬜ |
| R6 | Publish plans and briefs to SharePoint for teammates' M365 Copilot | **Sonnet 5.5** | ⏸ |

Rule of thumb: Opus 5.5 for design and prompt quality, Sonnet 5.5 for building. Don't
switch models partway through a session (it breaks the prompt cache); start a fresh
session from the checkpoint instead.

## Open items for Tony
- Pick or create the SharePoint/OneDrive folder for finished plans.
- OK to run the live Agilent extraction in R4.

## Legacy
The earlier Python pipeline (ingest → LLM extraction → SQLite → Q&A CLI) is frozen at
the git tag `v0-pipeline`. Some of its pieces, such as `src/atb/redact.py`, will be
reused by the new toolkit.

## Development
```bash
uv sync --all-extras
uv run pytest
uv run ruff check
```
Never commit `data/`, `*.sqlite*`, `config.toml`, or the Account Plan template, which
is Confidential.
