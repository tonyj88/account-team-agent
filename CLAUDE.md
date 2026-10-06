# CLAUDE.md

Account Team Bot fills leadership's Account Plan for one account from cited, dated
evidence. The `/account-plan` skill gathers the evidence, and the `atb-tools` Python
toolkit decides each value. Design: `docs/PLAN.md`. Status and next steps:
`CHECKPOINT.md`.

## Start of every session

1. Read `CHECKPOINT.md`. Its **Next steps** section says what to do and on which model.
2. Read only the part of `docs/PLAN.md` that the task touches.

## Invariants

Every change keeps these. Reviewers check them.

- **Claude gathers, code decides.** The skill proposes candidate values. Only `reconcile`
  picks winners and sets status. Code under `src/atb/` makes no LLM or network calls.
- **Provenance.** Every non-empty plan value cites a Salesforce `Object/Id/Field` or a
  saved text file with a verbatim quote. `validate` enforces this.
- **Freshness.** A human decision wins. Otherwise the newest dated evidence wins. Fields
  marked `system_of_record` in `config/account_plan_fields.yaml` keep the Salesforce
  value, and newer evidence only flags them. Older values stay in `history`.
- **Only a human approves.** Values from `llm_draft`, and fields whose catalog entry says
  `needs_approval`, are never `auto`.
- **Read-only connectors.** Never weaken `.claude/hooks/write_guard.py`. Never write to
  Salesforce or ZoomInfo. Never send email or Teams messages.
- **No secrets in saved sources.** Run `atb-tools redact` over saved sources. `validate`
  fails on any secret it finds.
- **Field keys come from the catalog.** Look keys up in
  `config/account_plan_fields.yaml` through `atb.catalog`. Don't hard-code them.
- **Synthetic test data only.** Tests use made-up names and a synthetic .docx, never the
  real template or customer data.

## Models

Only `claude-opus-5` and `claude-sonnet-5` are available on the company gateway. Use
Sonnet 5 by default. Use Opus 5 for design, prompt work in the skill, and end-of-phase
review. Subagents in `.claude/agents/*.md` pin explicit model IDs. Don't use the
`opus`, `sonnet`, or `haiku` aliases, because they may resolve to models the gateway
doesn't serve.

## Subagents

| Agent | Model | When |
|---|---|---|
| `atb-architect` | claude-opus-5 | A task too vague to build. Returns a task list. |
| `atb-implementer` | claude-sonnet-5 | One task: code and tests. |
| `atb-reviewer` | claude-sonnet-5 | After every implementer run, before every commit. |
| `atb-phase-reviewer` | claude-opus-5 | Once a milestone's tasks are committed, before merge. |
| `atb-explorer` | claude-sonnet-5 | Finding where something lives in the code. |

Bounded build tasks can also go to Codex through the `codex-delegate` skill. Review its
output against the invariants above before you commit it.

## Standard loop

1. Take the next task from `CHECKPOINT.md`.
2. Build it with `atb-implementer` or Codex. Run tasks in parallel only when they touch
   different files.
3. Review the diff with `atb-reviewer`. Fix findings until the verdict is "ship".
4. Commit one task per commit. Update `CHECKPOINT.md`.
5. When a milestone is done, run `atb-phase-reviewer`, fix its findings, then push and
   open or update the PR.
6. Ask Tony before anything under **Waiting on Tony**, before a live run on customer
   data, and before anything is uploaded or shared.

## Commands

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
uv run atb-tools --help
```

## Never

- Commit `data/`, `config.toml`, or the Account Plan template.
- Print a real secret while debugging redaction. Mask it.
