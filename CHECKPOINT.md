# Checkpoint

Last updated: 2026-09-28

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

**Current phase:** B — Time + staleness (Phase A done).
**Branch / PR:** `claude/awesome-lamport-uwdz70`, PR tonesjones/account-team-bot#1.

**Next tasks**
1. → `atb-architect` (**claude-opus-5**): design Phase B — date parsing sources and
   precedence (frontmatter `date`, email `Date:`, filename date, file mtime as
   low-confidence), where `occurred_at` gets set, and the
   `atb action-items list/resolve` CLI shape. Output a model-tagged task list to replace
   this entry. (Phase B is small; running this on Sonnet 5 is acceptable if budget is
   tight.)
2. → `atb-implementer` (**claude-sonnet-5**): the architect's tasks, one per run.
3. → `atb-reviewer` (**claude-sonnet-5**): after each implementer run, before commit.
4. → `atb-phase-reviewer` (**claude-opus-5**): once all Phase B tasks are committed.
5. Then Phase C → `atb-architect` (**claude-opus-5**, required): design the plan data
   model and MEDDPICC-focused extraction from `docs/ACCOUNT_PLAN_MAPPING.md` and
   `config/account_plan_fields.yaml`. Phase B's dates feed Phase C/F (staleness, review
   cadence), so do B first. Design `AccountFact.source` to include
   `zoominfo` and `copilot_draft` (Phase G) from the start, and let facts cite a
   structured record (source record ID + field) as well as a text span.
6. After Phase C: Phase G (C1/Salesforce snapshots) **before** D, so the first rendered
   plan already has a real Snapshot section. G0 skill design → `atb-architect`
   (claude-opus-5); build → `atb-implementer` (claude-sonnet-5).

Phase B's final check needs a live run on Tony's laptop (gateway + real data): before/after
`atb ask` showing a resolved action item is no longer reported as owed.

**Waiting on Tony**
- Put the blank Account Plan template at `data/templates/account_plan.docx` on the laptop
  (gitignored — it's Confidential; only its field list is in the repo).
- **C1 follow-ups (Salesforce via C1 works ✅ 2026-09-28):**
  - Discovery done: Salesforce (28 read tools) and ZoomInfo (4) reachable; Zendesk not
    connected and not needed. Still to check: do **customer support cases** live in
    Salesforce `Case`? And are existing account plans stored in Salesforce Notes &
    Attachments (so the bot can start from the last plan)?
  - Never approve a C1 `execute` call that writes; until the G0 guardrail hook exists,
    review each `execute` prompt.
  - Confirm with leadership how ARR should be calculated (Salesforce Amount is TCV).
- Copilot-filled template for one account (Phase G2 test case) — lower priority now.
- Approve the cost of re-extracting all notes once the Phase C prompt is ready.
- **IT answer** on M365 Copilot agents → Phase H, or the Cloudflare fallback (plus: is
  customer data allowed on Cloudflare, on whose account?).

**Last verification**
- 2026-09-21 (laptop, live): 70/71 docs extracted ok (1 empty skipped), 100 tests passing,
  ruff clean, synthesis `atb ask` returned a cited answer with no leaked secrets.
- 2026-09-28: docs/config-only changes (plan, agents, template field list); no code behavior changed.

## Phase status

The Account Plan template (received 2026-09-28) now drives the plan. Field list:
`config/account_plan_fields.yaml`; section-by-section sources:
`docs/ACCOUNT_PLAN_MAPPING.md`. MVP = sections 1, 4, 5, 10, 11 + trigger alerts;
low-confidence values are marked for human approval.

Models: **O5** = claude-opus-5, **S5** = claude-sonnet-5. "impl → rev" always means
`atb-implementer` (S5) → `atb-reviewer` (S5) per task; every phase ends with
`atb-phase-reviewer` (O5).

| # | Deliverable | Design | Build | Gated on | Status |
|---|---|---|---|---|---|
| 0–4 | Scaffold, ingest/normalize/dedup, resolution + review queue, LLM extraction, QA CLI | — | — | — | ✅ done (pre-replan) |
| A | Re-baseline, subagents, model guide, template mapping + field list | — | main session | — | ✅ done |
| B | Time + staleness: `occurred_at`, action-item resolve CLI, dated QA context | architect (O5; S5 ok) | impl → rev (S5) | — | ⬜ next |
| C | Plan data model (`AccountFact` + approval states, `Stakeholder`) + MEDDPICC-focused extraction redesign + teammate note template | architect (**O5 required**) | impl → rev (S5) | re-extract cost OK | ⬜ |
| D | `atb plan render` markdown preview, `plan review/approve/set` CLI, separate evidence file | main session (S5) | impl → rev (S5) | C | ⬜ |
| E | Fill the real .docx template + evidence file; plan version history | architect (O5) | impl → rev (S5) | D | ⬜ |
| F | Trigger-event detection + `atb plan due` (review cadence) | main session (S5) | impl → rev (S5) | C | ⬜ |
| G | Structured data via C1 MCP: G0 `/pull-account` Claude Code skill → JSON snapshots; G1 deterministic snapshot ingest (ARR derived in code); G2 Copilot-draft reconcile; exports as fallback | architect (O5) | impl → rev (S5) | G0: none (do after C); G1: C | ⬜ after C |
| I | Remaining sections (3, 7, 8, 9, then 2, 6, 12 as drafts) + meeting linking | architect (**O5 required**, prompt work) | impl → rev (S5) | E (+ G1 for 3, 6, 9) | ⬜ |
| J | Service layer + local FastAPI web app | architect (O5) | impl → rev (S5) | E | ⬜ |
| H | Team distribution via M365 Copilot agent | architect (O5) | — | IT answer | ⏸ waiting |
| H-fb | Cloudflare fallback (D1/R2/Worker + Access), read-only first | architect (O5) | impl → rev (S5) | IT rejects H + data approval | ⏸ waiting |

Deprioritized (unchanged): Teams bot via Graph, Salesforce write (plans are uploaded to
Salesforce by hand).

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
