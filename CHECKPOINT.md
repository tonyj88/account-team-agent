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

Models: **O5** = claude-opus-5, **S5** = claude-sonnet-5. "impl → rev" always means
`atb-implementer` (S5) → `atb-reviewer` (S5) per task; every phase ends with
`atb-phase-reviewer` (O5).

| # | Deliverable | Design | Build | Gated on | Status |
|---|---|---|---|---|---|
| 0–4 | Scaffold, ingest/normalize/dedup, resolution + review queue, LLM extraction, QA CLI | — | — | — | ✅ done (pre-replan) |
| A | Re-baseline: docs/PLAN.md, CLAUDE.md, subagents, this Handoff | — | main session | — | ✅ done |
| B | Time + staleness: `occurred_at`, action-item resolve CLI, dated QA context | architect (O5; S5 ok) | impl → rev (S5) | — | ⬜ next |
| C | Standardized capture: `AccountFact` + `fields.yaml`, wider signals + new extraction prompt, contact merge, meeting linking, teammate note template | architect (**O5 required**) | impl → rev (S5) | — | ⬜ |
| D | Account brief render + `atb facts override` | main session (S5) | impl → rev (S5) | C | ⬜ |
| E | CRM CSV stub → CRM-sourced facts | main session (S5) | impl → rev (S5) | C | ⬜ |
| F | Service layer + local FastAPI web app | architect (O5) | impl → rev (S5) | D | ⬜ |
| G | Fill leadership Account Plan template + periodic refresh | architect (**O5 required**) | impl → rev (S5) | Account Plan template | ⏸ waiting |
| H | Team distribution via M365 Copilot agent | architect (O5) | — | IT answer | ⏸ waiting |
| H-fb | Cloudflare fallback (D1/R2/Worker + Access), read-only first | architect (O5) | impl → rev (S5) | IT rejects H + data approval | ⏸ waiting |

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
