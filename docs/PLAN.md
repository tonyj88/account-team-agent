# Account Team Bot — Plan (source of truth, adopted 2026-09-28)

## Context
Tony started this repo (local Python CLI, SQLite, Claude via the org's Vertex proxy) as a
Q&A "brain" over meeting notes. After review + Q&A, the goal is sharper:

- **North star:** keep leadership's **Account Plan document** accurately filled in and
  periodically refreshed per account, with every field traceable to a source note/CRM row.
  Q&A is a second consumer of the same data, not the product's center.
- **Users:** Tony now (laptop), team soon. **Distribution target:** a Teams/M365 Copilot
  agent that coworkers add — so design for it now, build it later after IT weighs in.
- **Pain points (all confirmed):** inconsistent notes across sources, stale facts, no CRM
  data, manual intake, no team access.
- The Account Plan template arrived 2026-09-28 (Black Duck, MEDDPICC-based, updated
  quarterly for $150k+ ARR accounts, semiannually below; within 5 business days of a
  trigger event; stored in Salesforce Notes & Attachments). See
  `docs/ACCOUNT_PLAN_MAPPING.md`.
- The old external design doc (`fizzy-gathering-dragonfly.md`) is retired; this plan
  becomes the in-repo source of truth.

## Review findings (what exists vs. what the goal needs)
Solid and reusable: connector protocol (`ingest/base.py`), normalize/redact/dedup pipeline,
rule-first resolution + review queue (`resolve/core.py`), forced-tool-use extraction with
verbatim-quote spans + retries (`extract/core.py`, `extract/store.py:_resolve_span`),
IngestLog cost tracking, 100 tests.

Gaps vs. the goal:
1. **Facts are per-document rows with no lifecycle** — no dates (`Document.occurred_at` is
   never set by any connector), no supersession, no human override. Can't produce a
   "current" account plan or avoid stale answers.
2. **Extraction schema is too narrow** — only contacts/action items/decisions/risks. Missing
   commercial, health/sentiment, technical, relationship-role signals.
3. **Contacts duplicate per document** (`extract/store.py` inserts one per mention); no roles
   (champion / decision maker / blocker).
4. **Meeting linking not built** — `Meeting` model unused; `normalize/dedup.py` references a
   non-existent `resolve/meeting_link.py`.
5. **No standard outputs** — nothing renders a per-meeting record or account brief a human
   can read/share.
6. **No service layer/API** — logic is reachable only through `cli.py`; blocks web app and
   any Copilot API plugin.
7. README claim "structured questions skip the LLM" is inaccurate (structured still goes
   router → Sonnet over a fact dump). CRM questions always decline (Phase 5 not built).

## Core design change: the Account Plan template is the data model
Template received 2026-09-28 (Word, 12 sections + appendix, plain tables). The blank .docx
is **Confidential** and is never committed: it lives on Tony's laptop at
`data/templates/account_plan.docx` (gitignored). Only its field list is in the repo:
`config/account_plan_fields.yaml` and `docs/ACCOUNT_PLAN_MAPPING.md`.

- **Scalar fields** (Snapshot, MEDDPICC elements, strategy text) → `AccountFact` (new,
  `models.py`): `account_id, field_key` (from the YAML, e.g. `meddpicc.champion`),
  `value` (JSON), `observed_at`, `source` (note | crm | human | llm_draft),
  `document_id` + `char_start/end`, `status` (current | superseded | overridden),
  `confidence`, `approval` (auto | needs_approval | approved | rejected).
- **Repeating rows** get their own tables, each row with the same provenance/approval
  columns: `Stakeholder` (merged Contact + MEDDPICC role, position, tier, relationship
  owner, next touch), `Risk` (extended: mitigation, owner, by-when), `ActionItem`
  (extended: 30/60/90 bucket from due date), later `Competitor`, `Partner`, `Opportunity`.
- **Current value rule:** human > newest CRM > newest note-derived; older values
  superseded, never deleted.
- **Human approval rule (Tony, 2026-09-28): anything low-confidence is marked for human
  approval.** A value is `needs_approval` when any of: confidence below threshold;
  `source=llm_draft` (judgement fields: thesis, R/A/G, position, the ask); sources
  disagree; the only evidence is older than the review cycle. `approved` values are only
  ever set by a human. The rendered plan visibly marks unapproved values.

## Phased plan (re-ordered around the template)

MVP (Tony, 2026-09-28) = the fact-based sections: **1 Snapshot, 4 MEDDPICC,
5 Stakeholders, 10 Risks, 11 30/60/90 Actions**, plus trigger-event alerts. All other
sections are rendered blank until later phases.

**Phase A — Re-baseline + build workflow** ✅

**Phase B — Time + staleness (now)**
- Populate `Document.occurred_at`: frontmatter `date`, email `Date:` header, date in
  filename, fallback to file mtime (flagged as low-confidence). Changes in
  `normalize/core.py` + `ingest/folder.py` / `obsidian.py`.
- `atb action-items list/resolve` CLI, and verify via live before/after `atb ask` that
  `(done)` items stop being reported as owed; adjust `_ANSWER_SYSTEM_PROMPT` in
  `qa/core.py` if not.
- Include dates in `gather_structured_context` (`qa/structured.py`).

**Phase C — Account Plan data model + MEDDPICC extraction (next; Opus 5 design)**
- `AccountFact` + approval states + `Stakeholder` table; load
  `config/account_plan_fields.yaml` as the field catalog.
- Redesign `extract/schema.py` + `SYSTEM_PROMPT` around the MVP sections: MEDDPICC
  evidence per element (verbatim quote required), stakeholders with MEDDPICC role and
  position, risks with mitigation/owner/date, action items with owner/due. Each item
  carries a confidence. Bump `extraction_version`; re-extract (ask Tony first — cost).
- Contact → Stakeholder merge per account (email, then normalized name), keeping every
  mention as evidence.
- Teammate note template (markdown + frontmatter: `customer`, `date`, `attendees`,
  `author`) with prompts that mirror MEDDPICC, so notes arrive pre-structured.

**Phase D — Plan preview, approval CLI, evidence file**
- `atb plan render --account X` → markdown preview in the template's 12-section order
  (MVP sections filled, others marked "not yet automated"). Unapproved values marked
  `⚠ needs approval`.
- `atb plan review --account X` (list needs_approval values with their evidence),
  `atb plan approve/reject <id>`, `atb plan set <field_key> <value>` (human-entered
  values, e.g. Target ARR, until CRM data exists).
- **Separate evidence file** per plan (Tony's choice): `<account>_evidence.md` listing, per
  field/row, the source document, date and quote.

**Phase E — Word output (fills the real template)**
- Fill `data/templates/account_plan.docx` by locating each section's table by its heading
  cell and writing cells (python-docx, already a dependency). Output
  `data/plans/<account>_<date>.docx` + the evidence file. Unapproved values get a visible
  marker so nothing unconfirmed goes to Salesforce unnoticed.
- Record plan versions (Last Reviewed / Next Review in Section 1).

**Phase F — Trigger events + review cadence**
- Extraction flags trigger events from the template appendix: champion/EB leaves or
  changes role; reorg/acquisition/funding; earnings miss/budget or hiring freeze;
  competitor foothold; security incident/audit finding; renewal in final two quarters.
- `atb plan due` lists plans due for refresh (ARR ≥ $150k quarterly, else semiannual),
  plans with a trigger event in the last 5 business days, and **accounts with no plan
  yet** — ranked (highest ARR, nearest renewal first) to pace the "4+ new plans per week"
  target. No plans exist today, so initially this is the creation queue.

**Phase G — Structured data via C1-governed MCP (Salesforce proven 2026-09-28)**
Result of `docs/C1_ACCESS_TEST.md`: Claude Code on the laptop, connected to C1's MCP
URL, answered owner / contract / renewal for a real account from live Salesforce.
Findings that shape the design:
- **No ARR field in Salesforce.** Opportunity `Amount` is total contract value; ARR has
  to be *derived* (e.g. active contract TCV ÷ term in years). The rule is deterministic
  Python, shown in the evidence file, and `current_arr` stays `needs_approval` until
  leadership confirms the ARR definition.
- Renewal date comes from the **active contract end date**, cross-checked against the
  open renewal opportunity; disagreement ⇒ `needs_approval`.
- Records have stable IDs (contract number, opportunity) ⇒ provenance cites the
  Salesforce record + field, which is stronger than a quote.

How C1 exposes tools (seen 2026-09-28): not one tool per app, but a small **meta-tool**
set — `search_tools` (discover app tools), `execute` (run one; flagged
**destructive · open-world** because it can run *any* granted operation, writes
included), read-only helpers (`find_api_objects`, `count_api_objects`,
`get_execution`, `list_guides`/`load_guide`), and a virtual file store
(`create_vfs*`, `list_vfs_files`, `get_vfs_download_url`) that may suit bulk pulls.

**What's reachable (discovery 2026-09-28):** Salesforce — 28 read tools (`get_*` for
Account, Contact, Contract, Opportunity, OpportunityContactRole, OpportunityLineItem,
Asset, Case, Task, Event, Note, ContentDocument/Version, Order, Product2, User, …, plus
`salesforce_soql_query*`); a `salesforce/quirks` guide for SOQL patterns (the skill
loads it first). ZoomInfo — `list_companies`, `list_contacts`, `enrich_company`,
`enrich_contact`. **Zendesk: not connected, and not needed** (internal IT tickets only).

Salesforce object → template section:
| Object | Feeds |
|---|---|
| Account, User | 1 Snapshot: owners, segment/geo, industry |
| Contract | 1 renewal date + ARR derivation; renewal trigger |
| Opportunity, OpportunityLineItem | 9 Opportunities; 3 products; 2 "today" spend |
| Asset, Order/OrderItem, Product2 | 3 What they buy (products, licences, seats) |
| Contact, OpportunityContactRole | 5 Stakeholders (names, titles, recorded roles) |
| Task, Event | 5 "next touch" / coverage; activity recency for health |
| Case | 3 support tickets/ERs, 10 risks (escalations), security-incident trigger — **confirmed**: customer support cases live here |
| Note, ContentDocument | extra notes source. **No account plans exist yet** (confirmed) — first plans are created from scratch; after that, the bot's own last approved plan (local DB) is the baseline for refreshes |
ZoomInfo: contacts (titles, seniority, reporting lines) → 5 and 6; company (industry,
size, funding) → 1 and trigger events. `enrich_*` calls may consume ZoomInfo credits —
prefer `list_*`; enrich only with Tony's OK.

**Write-safety guardrail (required before G0 ships):** the bot must never change
Salesforce or ZoomInfo.
- `.claude/settings.json`: allow the read-only C1 tools; leave `execute` on "ask" (never
  auto-approved).
- A `PreToolUse` hook on the C1 `execute` tool with an **allowlist** of app tools:
  `salesforce_get_*`, `salesforce_soql_query*` (SELECT only), `zoominfo_list_*`;
  `zoominfo_enrich_*` → ask. Anything else is blocked. Today every granted tool is a
  read, but the allowlist protects against writes granted later. Deterministic code,
  not a prompt instruction.
- The skill's instructions also say read-only, as a second layer.

Architecture — **Claude Code fetches, Python decides:**
- **G0 — Fetcher (Claude Code skill, no Python LLM calls):** a project skill
  `.claude/skills/pull-account/` (`/pull-account <account>`) that uses the C1 MCP tools
  to read Salesforce (account, owners, active contracts, opportunities, products/assets)
  and ZoomInfo, then writes **one JSON snapshot
  per account per source** to `data/drop/crm/<source>/<account>_<timestamp>.json` in a
  fixed schema (`config/snapshot_schema.json`): raw field values + record IDs + pulled_at.
  The skill does **no** interpretation (no ARR math, no judgement) — it only copies
  fields. Runs on the company gateway model (Sonnet 5 is enough). A variant pulls every
  account Tony owns (`/pull-account --mine`).
- **G1 — Snapshot ingest (Python, deterministic):** `ingest/crm_snapshot.py` validates
  the JSON against the schema, stores it as a Document (redacted like any input), and
  writes `AccountFact`s / opportunity rows with `source=crm` (or `zoominfo`),
  citing record ID + field. Derived fields (ARR, growth gap, renewal-in-final-two-
  quarters trigger) are computed here by code. Newer snapshots supersede older ones.
- **G2 — Copilot draft import + reconciliation** (unchanged, lower priority now): read a
  Copilot-filled template, store cells as `copilot_draft` (always `needs_approval`),
  `atb plan reconcile` against evidence.
- **Fallbacks:** CSV/XLSX exports into `data/drop/exports/` mapped by
  `config/export_mappings.yaml` into the **same snapshot schema** (only if MCP access is
  lost or a source isn't exposed via C1); screenshots last.
- Later: the Python bot could call C1's MCP URL itself for unattended refresh, but that
  needs a stored OAuth token — only after the Claude Code fetcher proves out and IT is OK
  with it.

**Phase I — Remaining sections**
- 3 Where we are today, 7 Competition, 8 Partners, 9 Opportunities (needs G0/G1), then
  2 Strategy, 6 Org chart, 12 The Ask as `llm_draft` values that always need approval.
- Meeting linking (`resolve/meeting_link.py`: account + date + attendee overlap) — lets
  the evidence file show when two sources disagree about the same meeting.

**Phase J — Service layer + local web app**
- `atb/service.py` wrapping ask / plan / review / action-items; CLI calls it. FastAPI app
  in `api/` (OpenAPI surface a Copilot API plugin needs) + minimal local UI.

**Phase H — Team distribution (GATED: IT answer)**
- C1 also documents connecting **Copilot Studio** to C1-governed tools and publishing
  that agent to M365 Copilot. Since C1 access is per user, each teammate would pull only
  what they're entitled to — the team-access problem gets simpler. Strong Phase H
  candidate.
- Research with IT which M365 Copilot agent type is allowed: declarative agent over
  SharePoint (just publish Phase D/E files) vs. API plugin (needs hosted Phase J API + auth).
- Shared intake (email-forward IMAP connector already stubbed in `config.py`) once teammates
  contribute. Graph/Teams bot and Salesforce write stay deprioritized.

**Phase H-fallback — Cloudflare web app for 3–5 users (if IT rejects the Copilot agent)**
Architecture: **the laptop stays the processing engine; Cloudflare only serves.**
Ingest, redaction, extraction and embedding keep running locally through the corporate
proxy. A new `atb publish` command pushes a *read model* to Cloudflare:
- **D1** (SQLite) ← accounts, current `AccountFact`s, open action items, contacts, cited
  snippets. Same schema family as local SQLite, so the export is a straight table copy.
- **R2** ← rendered briefs / Account Plan files for download.
- **Vectorize** ← chunk embeddings (only needed if live Q&A is enabled).
- **Worker** (TypeScript, Hono) serves a small UI: account list → brief view with
  citations → facts table → (optional) "ask" box. Traffic for 3–5 users is well within
  the free/low tier.
- **Cloudflare Access** in front (email OTP or the company IdP) so only named teammates
  get in — no auth code to write.

Two levels, pick at build time:
1. **Read-only (lowest risk, build first):** Worker only displays pre-computed briefs/facts
   published from the laptop. No LLM calls in the cloud, no API key in Cloudflare.
2. **Live Q&A:** Worker embeds the question, queries Vectorize + D1, and calls Claude
   directly. Requires an Anthropic API key stored as a Worker secret (the corporate
   Vertex proxy likely isn't reachable from Cloudflare) and a TS port of the
   route/answer prompts from `qa/core.py`.

Design implications pulled forward into earlier phases:
- Phase D/E/J outputs must be serializable (JSON/markdown) so `atb publish` is just an
  exporter — no Python needed in the cloud.
- Keep redaction at ingest (already true) so nothing un-redacted can ever be published.

Open decision to confirm before building (not a code question): whether customer data may
be stored on a Cloudflare account, and whose account (company vs. personal). If not
allowed, this fallback degrades to the Phase J web app running on an internal VM.

## Build workflow: models, subagents, handoff
Constraint: all build sessions run through the company LLM gateway, which offers
**Opus 5 and Sonnet 5** only. Every instruction file pins explicit model IDs
(`claude-opus-5`, `claude-sonnet-5`) rather than aliases like `opus`/`sonnet`, which may
resolve to models the gateway doesn't serve.

**Subagent definitions** — new `.claude/agents/*.md`, checked into the repo so every
session (laptop or cloud) sees the same roster:

| Agent | Model | Use for | Tools |
|---|---|---|---|
| `atb-architect` | claude-opus-5 | Designing a phase: schema changes, `fields.yaml`, prompt design, Account Plan mapping. Output: a task list written into CHECKPOINT. | read-only |
| `atb-implementer` | claude-sonnet-5 | One scoped task from CHECKPOINT: code + tests, then `uv run pytest` and `uv run ruff check` must pass. | all |
| `atb-reviewer` | claude-sonnet-5 | Per-task review of the diff before commit, checking the project invariants: provenance (every fact has a doc + span), redaction at ingest, no un-cited answers, human override wins. | read-only + Bash for tests |
| `atb-phase-reviewer` | claude-opus-5 | Once per phase, before merge: cross-task correctness, plan fit, invariants tests can't cover. | read-only + Bash for tests |
| `atb-explorer` | claude-sonnet-5 | Codebase search to find where something lives. | read-only |

Each agent file's body carries the project invariants (the README design principles) so
subagents don't need the whole chat history.

**`CLAUDE.md`** (new, short): main session runs on claude-sonnet-5 (Opus 5 only where the CHECKPOINT Model guide says); start every session by
reading `CHECKPOINT.md` → "Handoff"; standard loop is architect (only for a new phase) →
implementer per task (parallel only when tasks touch different files) → reviewer →
commit → update CHECKPOINT. Also the test/lint commands and the rule not to commit
`data/` or `config.toml`.

**`CHECKPOINT.md` gets a "Handoff" section**, rewritten at the end of every session:
- current phase + the next 1–3 tasks, each tagged with the agent to spawn
  (e.g. `→ atb-implementer: add occurred_at parsing for email Date header`)
- blockers / decisions waiting on Tony (e.g. Account Plan template, IT answer, Cloudflare
  data approval)
- last verification result (tests count, last live check)
- phase table gains an "Agent(s)" column: design phases → architect; build →
  implementer; every phase ends with reviewer.

Runtime models (separate from build models): `config.py` `ModelConfig` keeps
`claude-sonnet-5` for extract/answer. `route` is currently `claude-haiku-4-5`, which was
live-verified through the gateway; if the gateway drops Haiku, change `route` to
`claude-sonnet-5` in `config.toml` (no code change). The Cloudflare "live Q&A" level would
need gateway access from Cloudflare or a separate key — another reason to build the
read-only level first.

## Verification
- `uv run pytest` + `uv run ruff check` green after every task; new unit tests for date
  parsing, supersession + approval rules, stakeholder merge, section rendering, docx
  filling (against a synthetic fixture docx with the same table layout — never the real
  template), trigger detection, review-due dates.
- Phase B: live before/after `atb ask` on a real account showing a resolved action item no
  longer reported as owed.
- Phase C/D: re-extract (after Tony OKs cost); render one real account's preview. Every
  MVP value has an evidence-file entry whose quote matches its source document;
  low-confidence and judgement values show `⚠ needs approval`; no redaction leaks.
- Phase E: open the generated .docx in Word on the laptop — layout unchanged, MVP cells
  filled, unapproved markers visible, evidence file alongside.
- Phase F: a note stating "our champion is leaving" raises a trigger; `atb plan due`
  lists a $150k+ account whose last review is > 1 quarter old.
- Phase J: `uvicorn` locally, hit `/ask` and `/plan/{account}`; OpenAPI spec renders.
- H-fallback: `wrangler dev` against a local D1 seeded by `atb publish --dry-run`; then
  deploy, confirm Access blocks an unlisted email and a teammate can open a plan whose
  evidence matches the local DB.
