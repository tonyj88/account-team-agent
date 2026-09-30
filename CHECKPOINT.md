# Checkpoint

Last updated: 2026-09-30

Short status snapshot. Design lives in [docs/PLAN.md](docs/PLAN.md); session workflow in
[CLAUDE.md](CLAUDE.md). Update this file at the end of every session that changes what's
built or what's next — it is the source of truth for "where are we", not chat history.

## Model guide

Only `claude-opus-5` and `claude-sonnet-5` are available (company LLM gateway).
**Default is Sonnet 5.** Use Opus 5 only for the rows marked below.

| Work | Model | How |
|---|---|---|
| Running the session (orchestrating, committing, updating this file) | **claude-sonnet-5** | Start Claude Code on Sonnet 5 unless the next Handoff step says Opus 5 |
| Implementing a task (code + tests) | **claude-sonnet-5** | `atb-implementer` |
| Per-task review before each commit | **claude-sonnet-5** | `atb-reviewer` |
| Codebase search | **claude-sonnet-5** | `atb-explorer` |
| Designing a phase: schema, `fields.yaml`, fact lifecycle rules | **claude-opus-5** | `atb-architect` |
| Writing or changing an LLM prompt / extraction schema | **claude-opus-5** | `atb-architect` designs it; implementer (Sonnet 5) wires it in |
| Debugging bad extraction or answer quality on real notes | **claude-opus-5** | Opus 5 main session |
| Mapping the Account Plan template to fields (Phase G) | **claude-opus-5** | `atb-architect` |
| End-of-phase review before merge | **claude-opus-5** | `atb-phase-reviewer` |
| Optional final PR review | Claude Code cloud session | Ask on the phase PR |

Small, mechanical phases (D, E) may skip the architect and go straight to implementer
tasks written by the Sonnet 5 main session; they still end with `atb-phase-reviewer`.

## Handoff

**Direction change (2026-09-30):** Claude-native re-plan adopted. Claude Code (Tony only)
gathers from C1/Salesforce + M365 + local notes; a small deterministic Python toolkit
reconciles (newest dated evidence wins; SF drift report), validates, and fills the
template. Old pipeline frozen at tag `v0-pipeline`. See docs/PLAN.md.
**Branch:** `replan/claude-native`.

**Next tasks**
1. R1 finish (main session, S5): update CLAUDE.md + `.claude/agents/*` invariants to the
   new design; guardrail scope now includes M365 write tools (see docs/R0_DISCOVERY.md).
2. R2 → `atb-architect` (claude-opus-5): design candidates.json / plan.schema.json and
   the reconcile + approval rules, using R0 findings (SF field history for as-of dates;
   transcripts for any meeting Tony attended; skip locked ones gracefully). Then `atb-implementer` per task.

- R2 design input: transcript preprocessing + field-driven extraction + per-transcript cache (docs/PLAN.md → Transcript handling).
- R2 design input: Obsidian = side notes only (no more pasted recaps); reconcile must
  merge a note and a transcript for the same meeting (account + date) into one source.

**Waiting on Tony**
- **Confirm ARR source:** SuperDuck ACV is NULL for all external customers (pipeline gap), so the plan now uses Salesforce `Account.ACV_Current__c`. OK? Report the SuperDuck gap to the data team?
- Pick/create the SharePoint (or OneDrive) folder for plans — none exists today (R0).
- Before R4 live run on Agilent (C1 + M365 reads).

**Last verification**
- 2026-09-30: R0b done — SuperDuck join via sfdc_id ✅, core.scans ✅, ACV ❌ (NULL for all), health marts miss NULL-ACV accounts; SF ACV_Current__c ✅ (no field history); Confluence account pages ✅ (Rovo costs credits → prefer CQL).
- 2026-09-30: R0 discovery done (docs/R0_DISCOVERY.md): calendar, email, Teams chat, SharePoint ✅; transcripts ✅ for meetings Tony attended (incl. others' — one series 423-locked at organizer storage); SF field history ✅ via SOQL; OneNote untested.

## Phase status

| # | Deliverable | Status |
|---|---|---|
| 0–4, A | Old pipeline (ingest, extraction, QA CLI) | ✅ frozen at `v0-pipeline` |
| B, C, G, H, H-fb, J | Old plan phases | ❌ retired by re-plan |
| R0 | Connector discovery | ✅ docs/R0_DISCOVERY.md |
| R0b | Probe SuperDuck + Atlassian | ✅ docs/R0_DISCOVERY.md |
| R1 | Re-plan docs, agents, CLAUDE.md | 🟡 next: CLAUDE.md + agents |
| R2 | plan schema + validate + reconcile + derive | ⬜ |
| R3 | render docx + evidence + sf_drift + diff | ⬜ |
| R4 | `/account-plan` skill + C1 allowlist hook; Agilent live run | ⬜ |
| R5 | `/plan-review`, `/plan-due` | ⬜ |
| R6 | Publish to SharePoint for teammates' Copilot | ⏸ later |

## Known issues carried forward
- `Document.occurred_at` is never set → no recency anywhere (Phase B).
- No way to mark an action item done; unverified whether `(done)` changes answers
  (Phase B).
- Contacts duplicate per document; no roles (Phase C → `Stakeholder`).
- `Meeting` model unused; `resolve/meeting_link.py` not built (Phase I).
- Loading `config/account_plan_fields.yaml` needs PyYAML, which is not a dependency yet —
  Phase C adds it (or the architect converts the file to TOML, stdlib `tomllib`).
- Tests for .docx filling must use a synthetic fixture with the same table layout, never
  the real (Confidential) template.
- Embedding cost logged as $0 in IngestLog.
- Runtime router uses `claude-haiku-4-5` (live-verified through the gateway). If the
  gateway drops it, set `models.route = "claude-sonnet-5"` in `config.toml`.
