# Checkpoint

Last updated: 2026-10-06

This file is the source of truth for what is built and what comes next. Update it at the
end of every session that changes either. The design is in [docs/PLAN.md](docs/PLAN.md).

## Status

The toolkit and the skill are built. Nothing has run on real data yet.

| Part | State | Where |
|---|---|---|
| Plan formats (`candidates.json`, `plan.json`) | Built | `src/atb/plan.py` |
| Field catalog loader | Built | `src/atb/catalog.py` |
| `reconcile`: freshness rule, approvals, `sf_drift.md` | Built, tested | `src/atb/reconcile.py` |
| `validate`: sources, verbatim quotes, approvals, secrets | Built, tested | `src/atb/validate.py` |
| `render`: label-located .docx fill, `evidence.md` | Built, tested on a synthetic template | `src/atb/render.py` |
| `transcript-clean`, `derive`, `diff`, `redact` | Built, tested | `src/atb/` |
| `/account-plan` skill | Written, not yet run | `.claude/skills/account-plan/SKILL.md` |
| Write-guard hook for C1 and M365 | Built, tested offline | `.claude/hooks/write_guard.py` |

Last verification, 2026-10-06, in a cloud session: 249 tests pass and `ruff check` is
clean. PyPI was blocked there, so the tests ran against system copies of pydantic,
PyYAML, and python-docx instead of `uv sync`. An end-to-end run on synthetic data
(transcript → reconcile → validate → render → diff) produced the expected plan and flags.

## Next steps

Run these on the laptop. They need the connectors, the template, and customer data.

1. **Set up** (Sonnet 5). Run `uv sync --all-extras`, then commit the regenerated
   `uv.lock`. Run `uv run pytest`.
2. **Check the hook** (Sonnet 5). Start Claude Code and confirm that `.claude/settings.json`
   loads the hook. Try one allowed C1 read and one blocked M365 send.
3. **Render against the real template** (Sonnet 5). Run `render` on a small `plan.json`
   with the real template. Check the "not placed" list. If labels in the template differ
   from `config/account_plan_fields.yaml`, fix the labels in the YAML. The 30/60/90 table
   may have bucket heading rows. If so, `render` needs bucket placement, which isn't
   built yet.
4. **Agilent run** (Opus 5). Run `/account-plan Agilent` and compare the result with the
   hand-made Agilent plan. Find at least one field where Teams or email is newer than
   Salesforce, and confirm the plan uses it and flags it.
5. **Second account** (Opus 5). Run the skill on the second account, which already has a
   hand-made doc built from only the M365 and C1 connectors. Change no prompts between
   the two runs. Compare the outputs field by field.
6. **Repeat run.** Run the same account twice with no new evidence. `diff` should show no
   changes.

## Definition of done

| Check | Pass condition | State |
|---|---|---|
| Setup | `uv sync` and `uv run pytest` pass on the laptop | Not run |
| Freshness rule | Unit tests for newer email, older email, and system-of-record conflict | Pass |
| Provenance | `validate` reports zero errors on the Agilent run | Not run |
| Approvals | Every `needs_approval` value shows ⚠ in the .docx | Pass on synthetic template |
| Agilent | The .docx opens in Word with the layout intact. Tony signs off. | Not run |
| Second account | Same as Agilent, with no prompt changes | Not run |
| Safety | The hook blocks a C1 write and an M365 send in a live session | Not run |
| Repeatability | A second run with no new evidence shows no `diff` | Not run |

Once every check passes, fix bugs before adding anything. A new feature needs a failing
check to justify it.

## Waiting on Tony

- Run steps 1 to 6 above on the laptop.
- Pick or create the SharePoint or OneDrive folder for finished plans. This only matters
  once publishing is back in scope.
- Confirm whether `claude-sonnet-5-5` and `claude-opus-5-5` are available on the gateway.
  If they are, update the model IDs in `CLAUDE.md` and `.claude/agents/*.md`.

## Decisions (2026-10-06)

- Current ARR is Salesforce `Account.ACV_Current__c`, treated as a system-of-record field.
- The old pipeline is deleted. It remains in git history at `0327e44`. The tag
  `v0-pipeline` exists on `tonyj88/account-team-agent`.
- The Agilent fill script stays local on the enterprise laptop and is not committed.
- The second test account is the one with an existing M365 + C1-only doc.
- Parked until the definition of done passes: SuperDuck health, ZoomInfo, Confluence and
  Jira, the transcript cache, speaker weighting in code, `/plan-review`, `/plan-due` and a
  scheduled run, an approval page, SharePoint publishing, and the non-MVP sections
  (2, 3, 6 to 9, 12).

## Known gaps

- `render` writes 30/60/90 actions in order. It doesn't place them under bucket headings.
- The hook's C1 `execute` check guesses the key that holds the app tool name. If a live
  call is denied with "no app tool name", read the real input shape and add its key.
- A note and a transcript from the same meeting count as two sources. Reconcile doesn't
  merge them yet.
