# Checkpoint

Last updated: 2026-09-30

Short status snapshot. Design lives in [docs/PLAN.md](docs/PLAN.md); session workflow in
[CLAUDE.md](CLAUDE.md). Update this file at the end of every session that changes what's
built or what's next — it is the source of truth for "where are we", not chat history.

## Model guide (Claude Enterprise, updated 2026-09-30)

**Start each new session on the model listed for the next milestone.** Don't switch
models partway through a session: the prompt cache is per model, so the new model
rereads the whole context uncached. Get savings with Sonnet subagents (fresh, small
context) and fresh sessions that resume from this file.

| Milestone | Start session on | Subagents | Why |
|---|---|---|---|
| **R1** Docs/agents/CLAUDE.md update, model pins | **Sonnet 5.5** | none needed | Mechanical edits |
| **R2** design (plan schema, candidates.json, reconcile/freshness/approval, speaker weighting) | **Opus 5.5** | `atb-architect` | Design errors spread everywhere |
| **R2** build (validate, derive, reconcile, transcript clean + tests) | **Sonnet 5.5** | implementer → reviewer | Well-specified code |
| **R3** render (docx skill + field→cell map), evidence, sf_drift, diff | **Sonnet 5.5** | implementer → reviewer | Wiring |
| **R4** `/account-plan` skill prompts + live Agilent run | **Opus 5.5** | reviewer (Sonnet) | Prompt and extraction quality on messy data |
| **R5** `/plan-review`, `/plan-due`, scheduled task | **Sonnet 5.5** | implementer → reviewer | Wiring |
| **R6** SharePoint publish for teammates' Copilot | **Sonnet 5.5** | — | Later |
| End-of-phase review (after R2–R3, after R4–R5) | **Opus 5.5** | `atb-phase-reviewer` | Cross-task issues |

R1 must update the model IDs in `.claude/agents/*.md` and CLAUDE.md from
`claude-opus-5`/`claude-sonnet-5` (old gateway) to `claude-opus-5-5`/`claude-sonnet-5-5`.
First confirm that Sonnet 5.5 is available on the Enterprise plan.

## Handoff

**Direction change (2026-09-30):** Claude-native re-plan adopted. Claude Code (Tony only)
gathers from C1/Salesforce + M365 + local notes; a small deterministic Python toolkit
reconciles (newest dated evidence wins; SF drift report), validates, and fills the
template. Old pipeline frozen at tag `v0-pipeline`. See docs/PLAN.md.
**Branch:** `master` (re-plan merged). Create a branch per milestone, e.g. `r1/docs-agents`.

**Next tasks**
1. **R1** — start on **Sonnet 5.5**: update CLAUDE.md + `.claude/agents/*` invariants to the
   new design; guardrail scope now includes M365 write tools (see docs/R0_DISCOVERY.md).
2. **R2** — start on **Opus 5.5**, `atb-architect`: design candidates.json / plan.schema.json and
   the reconcile + approval rules, using R0 findings (SF field history for as-of dates;
   transcripts for any meeting Tony attended; skip locked ones gracefully). Then `atb-implementer` per task.

- R2 design input: transcript preprocessing + field-driven extraction + per-transcript cache (docs/PLAN.md → Transcript handling).
- R2 design input: Obsidian = side notes only (no more pasted recaps); reconcile must
  merge a note and a transcript for the same meeting (account + date) into one source.

**Waiting on Tony**
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
