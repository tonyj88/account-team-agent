# Checkpoint

Last updated: 2026-09-28

Status tracking for this project. Update this file at the end of any session
that changes what's built or what's next — this is the source of truth for
"where are we," not the chat history.

## Phase status

| # | Deliverable | Needs approval? | Status |
|---|---|---|---|
| 0 | Scaffold, config, models, storage | no | ✅ done |
| 1 | Normalization + dedup + `folder` and `obsidian` connectors | no | ✅ done |
| 2 | Entity resolution, alias table, review-queue CLI | no | ✅ done |
| 3 | LLM extraction with provenance | LLM API only | ✅ done, live-verified |
| 4 | QA service + web app | no | ✅ done, live-verified (web app not started) |
| 5 | CRM adapter: CSV stub only | no | ⬜ not started |
| 6 | *Deprioritized* — Teams bot + email connector | Azure app reg, Graph | ⬜ unscheduled |
| 7 | *Deprioritized* — Salesforce read/write | SF read + write | ⬜ unscheduled |

Phases 6 and 7 are deliberately deprioritized because of permission-grant risk
(the same risk that killed a prior Microsoft-transcript-automation project).
Don't resume building toward them unless explicitly reopened.

## As of last verification (2026-09-21)

- **Extraction**: 70 documents ok, 1 skipped (empty), 0 errors, out of 71 total.
- **Tests**: 100 passing, ruff clean.
- **Embeddings**: unblocked via the org's LLM proxy (`text-embedding-3-small`,
  native 1536 dims), no local model or new credential needed.
- **Redaction**: runs at ingest time (before hashing/extraction/embedding), so
  secrets never reach the DB, the model, or an answer. Verified via a
  token-masking script — no real secret value ever printed.
- **QA**: a synthesis-style `atb ask` against a real account returned a clean,
  well-cited answer with no leaked secrets.
- **Extraction retries**: forced tool-use is non-deterministic in *how* it
  fails (not just which docs fail), so `extract_document` retries up to 3
  times on a missing `tool_use` block or a validation error, billing and
  logging every attempt.

## Known gap (found while dogfooding, not yet built)

**No way to mark an action item resolved without editing the source note.**
The bot answered with a stale "Tony owes X" from an outdated note. The schema
already supports it (`ActionItem.status`: open/done/dropped, already
annotated into the QA context), but:

1. No CLI command writes to `ActionItem.status` — only extraction and the
   review queue write `ActionItem` rows. Needs something like
   `atb action-items list --account X` + `atb action-items resolve <id> --status done`.
2. Unverified whether the answer-synthesis prompt actually changes its answer
   based on a `(done)`/`(dropped)` annotation, or just displays it without
   acting on it. Needs a live before/after `ask` check.

Do this before or interleaved with Phase 5 — it's small and directly affects
whether the team trusts the bot's day-to-day answers.

## Next up

1. Action-item resolution CLI + verify it changes answers (see gap above).
2. Phase 5: CSV-stub CRM adapter (`get_account`, `get_contacts`,
   `get_open_cases`, `get_renewal` reading Salesforce report exports dropped
   in the intake folder).
3. Web app front end (FastAPI + minimal chat SPA) — currently only the CLI
   (`atb ask`) exercises the QA service.

## Where the full design lives

The governing implementation plan (architecture, phasing rationale, cost
model, verification plan) is `fizzy-gathering-dragonfly.md`, kept outside
this repo in the user's local Claude plans directory. This file is the
short-form status snapshot; the plan file is the long-form design doc.
