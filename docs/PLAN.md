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
- The Account Plan **template hasn't arrived yet**. This plan does template-independent
  foundation work now and gates template-specific work on receiving it.
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

## Core design change: an evidence-backed "account field" layer
Introduce one generic model the Account Plan will map onto, so the template becomes config,
not code:

- `AccountFact` (new, `models.py`): `account_id, field_key` (e.g. `commercial.renewal_date`,
  `relationship.champion`, `health.sentiment`), `value` (JSON), `observed_at` (source
  document date), `source` (note | crm | human), `document_id` + `char_start/end`,
  `status` (current | superseded | overridden), `confidence`.
- **Current value rule:** human override > newest CRM row > newest note-derived fact; older
  ones marked `superseded`, never deleted (provenance + "disagreement is signal").
- Field catalog lives in a config file (`fields.yaml`): key, description, type, which
  extraction category feeds it. Swapping in the leadership template = editing this file +
  a renderer mapping.
- Existing `ActionItem/Decision/Risk/Contact` tables stay; action items get the resolve CLI
  and `observed_at`.

## Phased plan

**Phase A — Re-baseline + build workflow (small, now)**
- Add `docs/PLAN.md` (this plan) and rewrite `CHECKPOINT.md` phase table around it; fix the
  README "skips the LLM" claim and the dangling `meeting_link.py` reference.
- Set up the subagent workflow described in **Build workflow** below (agent files,
  `CLAUDE.md`, handoff section in `CHECKPOINT.md`).

**Phase B — Time + staleness (now)**
- Populate `Document.occurred_at`: frontmatter `date`, email `Date:` header, date in
  filename, fallback to file mtime (flagged as low-confidence). Changes in
  `normalize/core.py` + `ingest/folder.py` / `obsidian.py`.
- `atb action-items list/resolve` CLI (the known gap), and verify via live before/after
  `atb ask` that `(done)` items stop being reported as owed; adjust `_ANSWER_SYSTEM_PROMPT`
  in `qa/core.py` if not.
- Include dates in `gather_structured_context` (`qa/structured.py`) so answers prefer
  recent facts.

**Phase C — Standardized capture (now)**
- Expand `extract/schema.py` + `SYSTEM_PROMPT` with signal categories: commercial,
  health/sentiment, technical, relationship roles — emitted as `AccountFact` candidates
  keyed to `fields.yaml`, same verbatim-quote provenance. Bump `extraction_version`;
  re-extract.
- Contact merge: normalize by email/name per account, attach roles, keep per-doc mentions
  as evidence.
- Meeting linking (`resolve/meeting_link.py`): group docs by account + date + attendee
  overlap.
- **Teammate intake template:** a markdown note template with frontmatter (`customer`,
  `date`, `attendees`, `author`) + a short guide — the lowest-friction way to standardize
  notes before any automation.

**Phase D — Account brief output (now)**
- `atb brief render --account X` → markdown "living account brief" from current
  `AccountFact`s + open action items, each line cited. `atb brief refresh` re-renders all.
- `atb facts list/override` CLI so Tony can correct a field (writes `source=human`).
- Output to `data/briefs/<account>.md` — shareable files that a SharePoint-backed Copilot
  declarative agent could read later with zero API hosting.

**Phase E — CRM CSV stub (now/next)**
- `crm/csv_stub.py` reading Salesforce report exports from `data/crm_exports`; writes
  `AccountFact`s with `source=crm` (renewal, ARR, open cases). Router's
  `unsupported_crm` path then answers from those facts instead of declining.

**Phase F — Service layer + local web app (next)**
- `atb/service.py` wrapping ask / brief / facts / action-items; CLI calls it.
- FastAPI app in `api/` exposing those as a clean OpenAPI surface (the exact shape a
  Copilot API plugin needs) + minimal local chat/brief UI. Laptop-only, no auth yet.

**Phase G — Account Plan template (GATED: when Tony shares it)**
- Map each template section → `fields.yaml` keys; gap report of fields with no source.
- Renderer that fills the leadership format (docx if that's what it is) from current facts,
  with a "sources/last updated" appendix and highlighted fields that are stale or empty.
- Scheduled periodic refresh (ingest → extract → render) on the laptop.

**Phase H — Team distribution (GATED: IT answer)**
- Research with IT which M365 Copilot agent type is allowed: declarative agent over
  SharePoint (just publish Phase D/G files) vs. API plugin (needs hosted Phase F API + auth).
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
- Phase D/F outputs must be serializable (JSON/markdown) so `atb publish` is just an
  exporter — no Python needed in the cloud.
- Keep redaction at ingest (already true) so nothing un-redacted can ever be published.

Open decision to confirm before building (not a code question): whether customer data may
be stored on a Cloudflare account, and whose account (company vs. personal). If not
allowed, this fallback degrades to the Phase F web app running on an internal VM.

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
| `atb-reviewer` | claude-opus-5 | Review the diff before commit, checking the project invariants: provenance (every fact has a doc + span), redaction at ingest, no un-cited answers, human override wins. | read-only + Bash for tests |
| `atb-explorer` | claude-sonnet-5 | Codebase search to find where something lives. | read-only |

Each agent file's body carries the project invariants (the README design principles) so
subagents don't need the whole chat history.

**`CLAUDE.md`** (new, short): main session runs on claude-opus-5; start every session by
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
- `uv run pytest` + `uv run ruff check` green after every phase; new unit tests for date
  parsing, fact supersession rule, contact merge, meeting linking, brief rendering, CSV stub.
- Phase B: live before/after `atb ask` on a real account showing a resolved action item no
  longer reported as owed.
- Phase C/D: re-extract the existing 71 docs; spot-check one account's rendered brief —
  every line has a citation that opens to the right span; no redaction leaks.
- Phase E: drop a sample SF report CSV; "when's the renewal?" answers with a CRM citation.
- Phase F: `uvicorn` locally, hit `/ask` and `/brief/{account}`; OpenAPI spec renders.
- H-fallback: `wrangler dev` against a local D1 seeded by `atb publish --dry-run`; then
  deploy, confirm Access blocks an unlisted email and a teammate can open a brief whose
  citations match the local DB.
