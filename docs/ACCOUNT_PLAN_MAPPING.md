# Account Plan sections and their sources

This page lists where each section of the leadership Account Plan template (Sep 2026)
gets its values. The template is Confidential and isn't in this repo. Keep it at
`data/templates/account_plan.docx` on the laptop. The machine-readable field list, with
each field's label, source, and approval rule, is `config/account_plan_fields.yaml`.

## Scope

- **Filled now:** the header, 1 Snapshot, 4 MEDDPICC, 5 Stakeholders, 10 Risks, and
  11 30/60/90 Actions.
- **Blank for now:** 2, 3, 6, 7, 8, 9, and 12.

## Section map

| # | Section | Source | Notes |
|---|---|---|---|
| H | Header: Exec Sponsor, Status R/A/G | Notes, Claude draft | Status always needs approval. |
| 1 | Snapshot | Salesforce `Account`, `User`, `Contract` | Current ARR is `Account.ACV_Current__c`. Renewal date is the active contract end date. Both are system-of-record fields. Target ARR and Reviewed With come from a human. Health R/A/G is a Claude draft. `atb-tools` computes Next Review and Growth $ Gap. |
| 2 | Account Strategy | Salesforce for "today", human for the future | Parked. |
| 3 | Where We Are Today | Salesforce `Asset`, `Contract`, `OpportunityLineItem`, `Case`, notes | Parked. |
| 4 | MEDDPICC | Transcripts, email, notes | Evidence is a cited quote. Each R/A/G is a Claude draft. |
| 5 | Stakeholder Map | Salesforce `Contact`, `OpportunityContactRole`, `Task`, `Event`; transcripts and notes | MEDDPICC role and position need approval. |
| 6 | Org Chart and Coverage | ZoomInfo reporting lines, human | Parked. |
| 7 | Competition | Notes, Claude drafts | Parked. |
| 8 | Channel and Partners | Notes | Parked. |
| 9 | Opportunities | Salesforce `Opportunity`, notes | Parked. |
| 10 | Risks and Blockers | Transcripts, notes, escalated Salesforce `Case` records | Each risk has a mitigation, an owner, and a date. |
| 11 | 30/60/90 Actions | Transcripts, email, notes | `derive.action_bucket` buckets actions by due date. |
| 12 | The Ask | Human, Claude draft | Parked. |
| App. | Review cadence and trigger events | ARR, notes | An account with ARR of $150k or more is reviewed quarterly. Others are reviewed every six months. A trigger event means an update within 5 business days. |

## Approval

A value is marked ⚠ needs approval when any of these hold:

- Its catalog entry says `needs_approval`.
- It is Claude's judgement: R/A/G, position, thesis, or the ask.
- Its confidence is low.
- Its sources disagree.
- Its newest evidence is more than 182 days old.

Only a human sets `approved`. The full rule is in [PLAN.md](PLAN.md#the-freshness-rule).

## Output

Each run writes to `data/plans/<account>/<date>/`:

- `<account>_<date>.docx`: the template with cells filled and unapproved values marked.
- `evidence.md`: for each field and row, the sources, dates, and verbatim quotes.
- `sf_drift.md`: fields where newer evidence contradicts Salesforce.
- `plan.json`: the next run's baseline.

No account plans existed before this bot, so the first plan for each account starts from
scratch. Uploading to Salesforce stays manual. The C1 tools are read-only.
