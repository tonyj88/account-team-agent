# Account Plan → data sources

How each section of the leadership Account Plan template (Sep 2026) gets filled. The
template itself is Confidential and is not in this repo: keep it at
`data/templates/account_plan.docx` on the laptop (gitignored). The machine-readable field
list is `config/account_plan_fields.yaml`.

## Rules (Tony, 2026-09-28)
- **MVP sections:** 1 Snapshot, 4 MEDDPICC, 5 Stakeholders, 10 Risks, 11 30/60/90
  Actions, plus trigger-event alerts. Other sections render blank until Phase I.
- **Low confidence ⇒ human approval.** A value is marked `⚠ needs approval` when any of:
  confidence below threshold; it's an LLM judgement (R/A/G, position, thesis, the ask);
  sources disagree; the only evidence is older than the review cycle. Only a human sets
  `approved`.
- **Citations go in a separate evidence file** next to the plan, not inside the .docx.
- **Structured sources (2026-09-28):** Salesforce, Zendesk and ZoomInfo list exports
  (CSV/XLSX) dropped in `data/drop/exports/`; plus Copilot-filled drafts of this
  template in `data/drop/copilot/`, which are reconciled against evidence and always
  need approval. Until G1 lands, CRM fields are entered with `atb plan set`.

## Section map

| # | Section | Source | Automation | Notes |
|---|---|---|---|---|
| — | Header: Exec Sponsor, Status R/A/G | notes / draft | partial | Status always needs approval |
| 1 | Snapshot | Salesforce export (industry/segment also ZoomInfo); dates by bot | high once CRM exists | Target ARR, Reviewed With = human; Health R/A/G = draft; Growth gap and Next Review are computed |
| 2 | Account Strategy | CRM "today"; human future | low | Thesis + must-win plays are drafts |
| 3 | Where We Are Today | Salesforce products + Zendesk tickets + notes | medium | Usage/telemetry still has no source |
| 4 | MEDDPICC | notes | **high** | Evidence = cited quotes; R/A/G = draft |
| 5 | Stakeholder Map | notes + ZoomInfo titles | high | Needs contact merge; MEDDPICC role + position need approval |
| 6 | Org Chart & Coverage | ZoomInfo reporting lines + human | medium | Tiers/codes need approval; bot lists Tier 1/2 gaps ("?" = open risk) |
| 7 | Competition | notes; drafts | medium | Who/footprint extracted; counter-position + trap question drafted |
| 8 | Channel & Partners | notes | medium | Influence + alignment need approval |
| 9 | Opportunities | Salesforce export + notes | high once CRM exists | Next action from action items |
| 10 | Risks & Blockers | notes + Zendesk escalations | high | Extraction adds mitigation, owner, by-when |
| 11 | 30/60/90 Actions | notes | high | Bucketed by due date; flag Section 4 ambers with no 30-day action |
| 12 | The Ask | human / draft | low | |
| App. | Refresh cadence + trigger events | ARR + notes | high | ≥$150k quarterly, else semiannual; trigger ⇒ update within 5 business days |

## Output
- `data/plans/<account>_<date>.docx`: the template with cells filled; unapproved values
  visibly marked.
- `data/plans/<account>_<date>_evidence.md`: per field/row, the source document, date,
  and verbatim quote.
- Uploading to Salesforce (Notes & Attachments) stays manual. Salesforce write is
  deprioritized.
