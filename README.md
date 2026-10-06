# Account Team Bot

Fills out leadership's Account Plan (`account_plan.docx`) for one account at a time.
Every value cites where it came from. Values that need a human decision carry a ⚠ marker.

Tony runs it from Claude Code on his laptop. The `/account-plan` skill gathers evidence
through the ConductorOne (C1) and Microsoft 365 connectors. A small Python toolkit,
`atb-tools`, then picks the winning value for each field, checks the evidence, and fills
the template. The toolkit makes no LLM calls, so the same evidence always produces the
same plan.

```
Salesforce (via C1) ──┐
Teams transcripts ────┤                    atb-tools
Outlook email, chat ──┼─► /account-plan ─► reconcile ─► validate ─► render ─► <account>_<date>.docx
SharePoint files ─────┤   candidates.json  plan.json                         evidence.md
Local side notes ─────┘                    sf_drift.md
```

## How a value is chosen

- **The newest dated evidence wins.** Salesforce contacts and notes go stale, so a newer
  Teams transcript or email replaces them. The plan marks that value ⚠ and lists it in
  `sf_drift.md`, so you can correct Salesforce by hand.
- **Salesforce keeps the system-of-record fields.** These are Current ARR
  (`Account.ACV_Current__c`) and renewal dates. A conversation can flag a change to them
  but never replaces them.
- **A human decision beats everything.** Only you can approve a value. Claude's
  judgements, such as an R/A/G status, always need approval.
- **The bot only reads.** It never writes to Salesforce and never sends email or Teams
  messages. The hook in `.claude/hooks/write_guard.py` enforces this.

The full rules are in [docs/PLAN.md](docs/PLAN.md).

## Set up

You need Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras
uv run pytest
uv run ruff check
```

To fill a real plan, you also need:

- The C1 and Microsoft 365 connectors, signed in from Claude Code.
- The blank template at `data/templates/account_plan.docx`. The template is Confidential,
  so it stays out of git.

## Run it

In Claude Code, from the repository root:

```
/account-plan <account name>
```

The skill writes everything to `data/plans/<account>/<date>/`:

| File | Contents |
|---|---|
| `<account>_<date>.docx` | The filled template. |
| `evidence.md` | Each value with its sources, quotes, and older values. |
| `sf_drift.md` | Fields where newer evidence contradicts Salesforce. |
| `plan.json` | The reconciled plan. The next run uses it as the baseline. |
| `candidates.json`, `sources/` | The raw evidence that the plan was built from. |

The steps the skill follows are in
[.claude/skills/account-plan/SKILL.md](.claude/skills/account-plan/SKILL.md). You can also
run each `atb-tools` step yourself. `uv run atb-tools --help` lists them.

## Repository layout

| Path | Contents |
|---|---|
| `src/atb/` | The `atb-tools` toolkit: `reconcile`, `validate`, `render`, `diff`, `transcript`, `derive`, `redact`. |
| `src/atb/plan.py` | The `candidates.json` and `plan.json` formats. |
| `config/account_plan_fields.yaml` | Every field in the template, with its source and approval rule. |
| `.claude/skills/account-plan/` | The `/account-plan` skill. |
| `.claude/hooks/write_guard.py` | Blocks connector writes and sends. |
| `docs/` | Design, field-to-source mapping, and connector findings. |

Status and next steps are in [CHECKPOINT.md](CHECKPOINT.md).

## Never commit

`data/`, `config.toml`, or the Account Plan template. They hold customer data,
credentials, or Confidential material. `.gitignore` covers all three.

The earlier pipeline (ingest, LLM extraction, SQLite, Q&A) was removed. It is still in the
git history at commit `0327e44`.
