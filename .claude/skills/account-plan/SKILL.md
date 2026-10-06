---
name: account-plan
description: Fill leadership's Account Plan (.docx) for one account from Salesforce (via ConductorOne) and Microsoft 365 evidence, with every value cited and uncertain values marked for approval. Use when Tony asks for, refreshes or rebuilds an account plan, e.g. "/account-plan Acme Corp".
---

# /account-plan <account>

You gather dated evidence and propose candidate values. The `atb-tools` commands decide
which value wins, check the evidence, and fill the template. Do not pick winners yourself
and do not edit `plan.json` by hand.

Scope: MVP sections only: header, 1 Snapshot, 4 MEDDPICC, 5 Stakeholders, 10 Risks,
11 30/60/90 Actions. Field keys and labels are in `config/account_plan_fields.yaml`.

## Rules
- **Read-only.** Never write to Salesforce or ZoomInfo. Never send, reply to or forward
  email or Teams messages. Never create, change or delete calendar events or files. The
  write-guard hook (`.claude/hooks/write_guard.py`) enforces this; do not try to work
  around a denial.
- **Customer data stays local.** Everything goes under `data/` (gitignored). Never commit
  it or paste it into another service.
- **Quote, don't paraphrase.** Every note-sourced value needs a verbatim quote from a
  text file you saved. `validate` rejects paraphrases.
- **Extract by field; never summarize the meeting.** Drop anything that maps to no field.

## 1. Set up the run folder
`RUN=data/plans/<account-slug>/<YYYY-MM-DD>` with `sources/` inside it. If an earlier run
exists, its `plan.json` is the baseline.

## 2. Gather (in this order)
1. **Salesforce via C1** (`search_tools`, then `execute`; load the `salesforce/quirks`
   guide first). Account (owner, segment, industry, `ACV_Current__c`, LastModifiedDate),
   active Contracts (EndDate), open renewal Opportunity, Contacts and
   OpportunityContactRoles, recent Tasks/Events, escalated Cases. Get field history from
   `AccountHistory`, `OpportunityFieldHistory`, `ContractHistory` for the as-of date; if a
   field has no history, use the record's `LastModifiedDate` and set `as_of_weak: true`.
2. **Calendar** (`outlook_calendar_search`, newest first): meetings with the account in the
   last 6 months, or since the baseline plan date.
3. **Teams transcripts** for those meetings: read the event, follow
   `meetingTranscriptUrl`, read the series without start/end and match the occurrence by
   `createdDateTime`. Save the raw VTT to `sources/<meeting-date>_<id>.vtt`, then run
   `uv run atb-tools transcript-clean <vtt> --out sources/<meeting-date>_<id>.txt
   --internal-org "<our company label>" --internal-domain <our domain>`. Quote from the
   `.txt`. A locked (HTTP 423) or missing transcript is not an error: note it and move on.
4. **Email and Teams chat** (`outlook_email_search`, `chat_message_search`): sort by date
   yourself. Save each message you quote to `sources/` as plain text.
5. **SharePoint/OneDrive** docs about the account; save the text you quote.
6. **Local notes** (Tony's Obsidian side notes): a note and a transcript from the same
   day cover the same meeting; quote the transcript and use the note for Tony's own
   observations.

## 3. Write `candidates.json`
Schema: `src/atb/plan.py` (`Candidates`). Emit **every** candidate you find, including
older and conflicting ones: reconcile needs them to apply the freshness rule and to write
the Salesforce drift report.
- Salesforce: `kind: salesforce`, `ref: "<Object>/<RecordId>/<Field>"`, `as_of` from field
  history.
- Text sources: `kind` (email, transcript, teams_chat, sharepoint, confluence, note),
  `ref` = web URL or path, `text_file` = path relative to `$RUN`, `quote` copied exactly,
  plus `speaker`, `speaker_side`, `timestamp` for transcripts.
- Judgements (R/A/G, stakeholder position, health): `kind: llm_draft`, with the
  supporting quote in the reasoning you show Tony, not in the value.
- Customer statements are the evidence for pain, metrics, decision criteria, decision
  process and competition. Internal statements are evidence only for our own actions and
  commitments. When only an internal speaker supports a customer-belief field, set
  `confidence: low`.
- Rows (stakeholders, risks, action_plan): `field` = section key, `row_key` = person's
  name or a short risk/action id, `row` = column key → text.
- `snapshot.current_arr` and `snapshot.renewal_dates` are system-of-record: still emit
  conversation candidates that contradict them, so they get flagged.

## 4. Run the toolkit
```bash
uv run atb-tools reconcile $RUN/candidates.json --baseline <previous>/plan.json \
  --out $RUN/plan.json --drift $RUN/sf_drift.md
uv run atb-tools validate $RUN/plan.json
uv run atb-tools render $RUN/plan.json --template data/templates/account_plan.docx \
  --out $RUN/<account-slug>_<date>.docx --evidence $RUN/evidence.md
uv run atb-tools diff $RUN/plan.json --baseline <previous>/plan.json
```
If `validate` reports errors, fix `candidates.json` (usually a quote that isn't verbatim,
or a missing saved text file) and run again from `reconcile`. Never weaken a value's
status to get past validation.

## 5. Report to Tony
Keep it short: the output paths, how many values need approval (⚠) and why, the
Salesforce drift items to update by hand, the labels `render` could not place, and any
sources that were unavailable (locked transcripts, empty searches). Ask before uploading
anything to SharePoint.
