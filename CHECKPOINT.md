# Checkpoint

Last updated: 2026-09-28

Short status snapshot. Design lives in [docs/PLAN.md](docs/PLAN.md); session workflow in
[CLAUDE.md](CLAUDE.md). Update this file at the end of every session that changes what's
built or what's next — it is the source of truth for "where are we", not chat history.

## Handoff

**Current phase:** B — Time + staleness (Phase A done this session).

**Next tasks**
1. → `atb-architect`: design Phase B — date parsing sources and precedence
   (frontmatter `date`, email `Date:`, filename date, file mtime as low-confidence),
   where `occurred_at` gets set, and the `atb action-items list/resolve` CLI shape.
   Output a task list to replace this entry.
2. → `atb-implementer` (after 1): tasks from the architect's list, one per run.
3. → `atb-reviewer`: after each implementer run, before commit.

Phase B's final check needs a live run on Tony's laptop (gateway + real data): before/after
`atb ask` showing a resolved action item is no longer reported as owed.

**Waiting on Tony**
- Leadership **Account Plan template** → unblocks Phase G.
- **IT answer** on M365 Copilot agents (declarative over SharePoint vs. API plugin) →
  Phase H, or the Cloudflare fallback.
- For the Cloudflare fallback: is customer data allowed on Cloudflare, and on whose account?

**Last verification**
- 2026-09-21 (laptop, live): 70/71 docs extracted ok (1 empty skipped), 100 tests passing,
  ruff clean, synthesis `atb ask` returned a cited answer with no leaked secrets.
- 2026-09-28: docs/workflow-only changes plus one docstring edit; no code behavior changed.

## Phase status

| # | Deliverable | Agent(s) | Gated on | Status |
|---|---|---|---|---|
| 0–4 | Scaffold, ingest/normalize/dedup, resolution + review queue, LLM extraction, QA CLI | — | — | ✅ done (pre-replan) |
| A | Re-baseline: docs/PLAN.md, CLAUDE.md, subagents, this Handoff | main | — | ✅ done |
| B | Time + staleness: `occurred_at`, action-item resolve CLI, dated QA context | architect → implementer → reviewer | — | ⬜ next |
| C | Standardized capture: `AccountFact` + `fields.yaml`, wider signals, contact merge, meeting linking, teammate note template | architect → implementer → reviewer | — | ⬜ |
| D | Account brief render + `atb facts override` | implementer → reviewer | C | ⬜ |
| E | CRM CSV stub → CRM-sourced facts | implementer → reviewer | C | ⬜ |
| F | Service layer + local FastAPI web app | architect → implementer → reviewer | D | ⬜ |
| G | Fill leadership Account Plan template + periodic refresh | architect → implementer → reviewer | Account Plan template | ⏸ waiting |
| H | Team distribution via M365 Copilot agent | architect | IT answer | ⏸ waiting |
| H-fb | Cloudflare fallback (D1/R2/Worker + Access), read-only first | architect → implementer → reviewer | IT rejects H + data approval | ⏸ waiting |

Deprioritized (unchanged): Teams bot via Graph, Salesforce write.

## Known issues carried forward
- `Document.occurred_at` is never set → no recency anywhere (Phase B).
- No way to mark an action item done; unverified whether `(done)` changes answers
  (Phase B).
- Contacts duplicate per document; no roles (Phase C).
- `Meeting` model unused; `resolve/meeting_link.py` not built (Phase C).
- Embedding cost logged as $0 in IngestLog.
- Runtime router uses `claude-haiku-4-5` (live-verified through the gateway). If the
  gateway drops it, set `models.route = "claude-sonnet-5"` in `config.toml`.
