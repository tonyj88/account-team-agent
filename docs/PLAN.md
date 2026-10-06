# Account Team Bot design

This document explains how the bot fills an Account Plan and why it works this way.
For what is built and what comes next, see [CHECKPOINT.md](../CHECKPOINT.md). For which
template section each source feeds, see [ACCOUNT_PLAN_MAPPING.md](ACCOUNT_PLAN_MAPPING.md).

## Goal

Fill leadership's Account Plan template for any account with the most accurate
information available. Every value cites its source. A value that needs a human decision
is visibly marked.

The first version covers the header and sections 1 (Snapshot), 4 (MEDDPICC),
5 (Stakeholders), 10 (Risks), and 11 (30/60/90 actions). The other sections render blank.

Tony is the only operator. Teammates have no Claude seats. They get the finished .docx
and ask Tony.

## Why Claude gathers and code decides

The first version of this repo was a Python pipeline. It ingested notes, called an LLM
to extract facts, stored them in SQLite, and answered questions. The connectors made
most of it unnecessary. In one Claude Code session, the C1 and Microsoft 365 connectors
read Salesforce and Teams transcripts directly, and that session filled the real
template for Agilent.

So the work splits in two:

- **The `/account-plan` skill** does what needs judgement: it searches the connectors,
  reads transcripts and email, and proposes candidate values with dated, quoted evidence.
- **The `atb-tools` toolkit** does what must be repeatable: it picks the winner for each
  field, checks every citation, and fills the template. It makes no LLM calls.

This split means a reviewer can trust the rules without trusting the model. If the
skill quotes something the source doesn't say, `validate` catches it. If two sources
disagree, `reconcile` applies the same rule every time.

```
/account-plan <account>
  1. Gather    C1 → Salesforce records and field history
               M365 → calendar, Teams transcripts, email, chat, SharePoint
               local side notes; the previous plan.json as baseline
  2. Propose   candidates.json: every candidate value with kind, as-of date,
               and a Salesforce ref or a saved text file plus a verbatim quote
  3. Decide    atb-tools reconcile → plan.json + sf_drift.md
  4. Check     atb-tools validate plan.json
  5. Fill      atb-tools render → <account>_<date>.docx + evidence.md
  6. Compare   atb-tools diff against the baseline
```

## The freshness rule

Salesforce isn't automatically the truth. It goes stale when nobody records what was
said in a meeting or an email. Commercial fields are reliable. Contacts and notes are the
fields that drift.

Every piece of evidence carries an as-of date:

| Source | As-of date |
|---|---|
| Salesforce | The field-history date (`AccountHistory`, `OpportunityFieldHistory`, `ContractHistory`). If the field has no history, the record's `LastModifiedDate`, marked `as_of_weak`. |
| Email | The sent date. |
| Teams transcript | The meeting date. |
| Note | The frontmatter or file date. |
| Baseline plan | The date of the previous plan. |

`reconcile` picks a value for each field in this order:

1. A human decision wins.
2. Otherwise, the newest dated evidence wins. On a tie, Salesforce wins.
3. Fields marked `system_of_record` keep the newest Salesforce value. These are Current
   ARR (`Account.ACV_Current__c`) and renewal dates. A newer conversation that disagrees
   sets a flag such as "Newer evidence (transcript, 2026-09-20) says: March 2027". The
   value then needs approval.
4. When newer non-Salesforce evidence beats Salesforce on any other field, the value
   needs approval and goes into `sf_drift.md`, so Tony can update Salesforce by hand.

Losing values stay in the plan's `history` and appear in `evidence.md`.

A value needs approval when any of these hold: the catalog says `needs_approval`; the
value is Claude's judgement (`llm_draft`); confidence is low; sources disagree; the
evidence is more than 182 days old; or the as-of date is weak on a field that isn't a
system-of-record field. ARR has no field history, but it is still trusted, because it is
a system-of-record field.

Only a human approves. An approved value carries forward from the baseline until newer
evidence replaces it.

## Transcripts

A transcript covers a whole meeting, about 12,000 tokens an hour. The skill extracts
evidence for plan fields. It never summarizes the meeting.

1. `atb-tools transcript-clean` parses the WEBVTT file. It drops filler such as "yeah"
   and "thanks", merges consecutive turns by the same speaker, and tags each speaker
   `customer` or `internal` from the Teams org label or the email domain. Quotes are
   checked against this cleaned text.
2. The skill reads the cleaned text, field by field, and proposes candidates with a quote,
   a timestamp, and the speaker.
3. Customer statements are the evidence for pain, metrics, decision criteria, decision
   process, and competition. Internal statements are evidence only for our own actions.
   The skill marks an internal-only claim about what the customer believes as low
   confidence, so it needs approval.

A locked transcript (HTTP 423) or a missing one isn't an error. The meeting still counts
as dated evidence of contact through the calendar.

## Checks

`validate` fails the run when any of these hold:

- A non-empty value has no source.
- A quote isn't found verbatim in its saved text file, after whitespace is collapsed.
- A `text_file` path points outside the plan folder.
- A Salesforce ref doesn't match `Object/Id/Field`.
- A value is `auto` when its catalog entry or source requires approval.
- A value is `approved` without a human or baseline source.
- A value, quote, or saved file contains a secret that `redact.py` detects.

It warns when an MVP field that the bot should fill is empty.

## Filling the template

The template is Confidential and stays out of git, so `render` can't rely on fixed cell
positions. It finds each field by the label printed in the template, taken from
`config/account_plan_fields.yaml`, and writes into the cell to the right. It finds row
tables by their header row. Values that need approval get a ⚠ marker. A flagged
system-of-record value shows the flag in brackets. Labels that `render` can't find are
reported, not guessed.

Citations go in `evidence.md`, next to the .docx, not inside it.

## Guardrails

- `.claude/hooks/write_guard.py` runs before every MCP tool call.
  - **C1 `execute`.** It allows `salesforce_get_*`, SELECT-only SOQL, and ZoomInfo
    `list_*` reads. ZoomInfo enrichment asks first. Everything else is denied.
  - **Microsoft 365.** It denies send, reply, forward, delete, and move. Upload and other
    writes ask first.
  - **Malformed calls.** It denies any connector call it can't parse.
- The skill's instructions repeat the read-only rule as a second layer.
- Customer data lives under `data/`, which is gitignored. Tests use a synthetic template.

## Parked

These wait until every check in the CHECKPOINT definition of done passes:

- SuperDuck scan-activity health. Its ACV column is empty and its health tables miss
  accounts with no ACV, so health would have to be computed from `core.scans`.
- ZoomInfo titles and reporting lines, and Confluence and Jira feature requests.
- A per-transcript cache, and speaker weighting enforced in code.
- Merging a side note and a transcript from the same meeting into one source.
- `/plan-review` for approvals, `/plan-due` for review cadence, and a weekly scheduled
  run.
- Publishing plans to SharePoint for teammates' Microsoft 365 Copilot.
- Sections 2, 3, 6 to 9, and 12.

Connector findings that inform these are in [R0_DISCOVERY.md](R0_DISCOVERY.md).
