# CLAUDE.md

Account Team Bot: turns meeting notes into cited, per-account facts to keep leadership's
Account Plan current and answer team questions. Design: `docs/PLAN.md`. Status and next
steps: `CHECKPOINT.md`.

## Start of every session
1. Read `CHECKPOINT.md` — the **Handoff** section says what's next and which subagent
   does it.
2. Read only the `docs/PLAN.md` phase you're working on.

## Models (company LLM gateway)
Only **claude-opus-5** and **claude-sonnet-5** are available for building.
- Main session: `claude-opus-5` (orchestrates, talks to Tony, commits).
- Subagents are pinned in `.claude/agents/*.md` with explicit model IDs. Don't use the
  `opus`/`sonnet`/`haiku` aliases or the built-in general-purpose agent with an unpinned
  model — they may resolve to models the gateway doesn't serve.

## Subagents
| Agent | Model | When |
|---|---|---|
| `atb-architect` | claude-opus-5 | Start of a new phase, or a task too vague to build. Returns a task list. |
| `atb-implementer` | claude-sonnet-5 | One task at a time from the Handoff list. Code + tests. |
| `atb-reviewer` | claude-opus-5 | After every implementer run, before every commit. |
| `atb-explorer` | claude-sonnet-5 | Finding where something lives in the code. |

## Standard loop
1. New phase? → `atb-architect`; paste its task list into CHECKPOINT Handoff.
2. For each task → `atb-implementer`. Run tasks in parallel only if the Handoff marks
   them as touching different files.
3. → `atb-reviewer` on the diff. Fix findings (another implementer run) until "ship".
4. Main session commits (one commit per task), then updates CHECKPOINT: phase table,
   Handoff, last verification.
5. Ask Tony before anything in "Waiting on Tony", before live LLM runs that re-extract
   everything (cost), and before any outward-facing deploy.

## Commands
```bash
uv sync --all-extras
uv run pytest
uv run ruff check
uv run atb --help
```

## Never
- Commit `data/`, `*.sqlite*`, or `config.toml` (customer data and credentials).
- Print real secret values while debugging redaction — mask them.
- Break the invariants listed in `.claude/agents/atb-reviewer.md`.
