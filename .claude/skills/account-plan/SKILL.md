---
name: account-plan
description: Fill leadership's Account Plan (.docx) for one account from Salesforce (through ConductorOne) and Microsoft 365 evidence. Every value is cited, and uncertain values are marked for approval. Use when Tony asks to create, refresh, or rebuild an account plan, for example "/account-plan Acme Corp".
---

# /account-plan <account>

You gather dated evidence and propose candidate values. The `atb-tools` commands decide
which value wins, check the evidence, and fill the template. Don't pick winners yourself,
and don't edit `plan.json` by hand.

This version fills the header and sections 1 (Snapshot), 4 (MEDDPICC), 5 (Stakeholders),
10 (Risks), and 11 (30/60/90 actions). Field keys and labels are in
`config/account_plan_fields.yaml`.

## Rules

- **Read only.** Never write to Salesforce or ZoomInfo. Never send, reply to, or forward
  email or Teams messages. Never create, change, or delete calendar events or files.
  `.claude/hooks/write_guard.py` enforces this. If the hook denies a call, don't look for
  another way to make it.
- **Keep customer data local.** Save everything under `data/`, which git ignores. Never
  commit it or paste it into another service.
- **Quote, don't paraphrase.** Every value from a conversation or document needs a
  verbatim quote from a text file you saved. `validate` rejects paraphrases.
- **Extract by field.** Never summarize a meeting. Drop anything that maps to no field.

## 1. Set up the run folder

Use `RUN=data/plans/<account-slug>/<YYYY-MM-DD>`, with a `sources/` folder inside it. If
an earlier run exists for the account, its `plan.json` is the baseline.

## 2. Gather the evidence

Gather in this order:

1. **Salesforce, through C1.** Load the `salesforce/quirks` guide first, then use
   `search_tools` and `execute`. Read:
   - The Account: owner, segment, industry, `ACV_Current__c`, and `LastModifiedDate`.
   - Active Contracts and their `EndDate`, and the open renewal Opportunity.
   - Contacts and OpportunityContactRoles.
   - Recent Tasks and Events, and escalated Cases.

   Get the as-of date for each field from `AccountHistory`, `OpportunityFieldHistory`,
   or `ContractHistory`. If a field has no history, use the record's `LastModifiedDate`
   and set `as_of_weak: true`.
2. **Calendar.** Use `outlook_calendar_search`, newest first. Find meetings with the
   account from the last six months, or since the baseline plan's date.
3. **Teams transcripts** for those meetings.
   1. Read the event and follow its `meetingTranscriptUrl`. Read the series without
      `start` and `end`, and match the occurrence by `createdDateTime`.
   2. Save the raw file to `sources/<meeting-date>_<id>.vtt`.
   3. Run `uv run atb-tools transcript-clean <vtt> --out sources/<meeting-date>_<id>.txt
      --internal-org "<our org label>" --internal-domain <our email domain>`.
   4. Quote from the `.txt` file.

   If a transcript is locked (HTTP 423) or missing, note it and move on. That isn't an
   error.
4. **Email and Teams chat.** Use `outlook_email_search` and `chat_message_search`, and
   sort the results by date yourself. Save each message you quote to `sources/` as plain
   text.
5. **SharePoint and OneDrive** documents about the account. Save the text you quote.
6. **Local notes** in Tony's Obsidian vault. A note and a transcript from the same day
   cover the same meeting. Quote the transcript. Use the note for Tony's own
   observations.

Before you quote from any saved file, run `uv run atb-tools redact $RUN/sources/*`. It
removes meeting passcodes and other secrets in place. `validate` fails if a secret is
left.

## 3. Write `candidates.json`

The format is the `Candidates` model in `src/atb/plan.py`. Include every candidate you
find, older and conflicting ones too. `reconcile` needs them to apply the freshness rule
and to write the Salesforce drift report.

- **Salesforce values.** Set `kind: salesforce`, `ref: "<Object>/<RecordId>/<Field>"`,
  and `as_of` from the field history.
- **Text sources.** Set `kind` to `email`, `transcript`, `teams_chat`, `sharepoint`,
  `confluence`, or `note`. Set `ref` to the web URL or path, `text_file` to the path
  relative to `$RUN`, and `quote` to the exact text. For transcripts, also set `speaker`,
  `speaker_side`, and `timestamp`.
- **Judgements** such as R/A/G, stakeholder position, and health. Set `kind: llm_draft`.
  Show Tony the supporting quotes in your report, not in the value.
- **Who said it.** Customer statements are the evidence for pain, metrics, decision
  criteria, decision process, and competition. Internal statements are evidence only for
  our own actions and commitments. If only an internal speaker supports a claim about
  what the customer believes, set `confidence: low`.
- **Rows** for stakeholders, risks, and actions. Set `field` to the section key
  (`stakeholders`, `risks`, or `action_plan`), `row_key` to the person's name or a short
  id, and `row` to a map from column key to text.
- **System-of-record fields.** `snapshot.current_arr` and `snapshot.renewal_dates` keep
  the Salesforce value. Still include conversation candidates that contradict them, so
  `reconcile` flags them.

## 4. Run the toolkit

```bash
uv run atb-tools reconcile $RUN/candidates.json --baseline <previous-run>/plan.json \
  --out $RUN/plan.json --drift $RUN/sf_drift.md
uv run atb-tools validate $RUN/plan.json
uv run atb-tools render $RUN/plan.json --template data/templates/account_plan.docx \
  --out $RUN/<account-slug>_<date>.docx --evidence $RUN/evidence.md
uv run atb-tools diff $RUN/plan.json --baseline <previous-run>/plan.json
```

Leave out `--baseline` on the first run for an account.

If `validate` reports errors, fix `candidates.json` and run again from `reconcile`. The
usual causes are a quote that isn't verbatim or a saved text file that is missing. Never
lower a value's confidence or change its kind just to get past `validate`.

## 5. Report to Tony

Keep the report short:

- The output paths.
- How many values need approval (⚠), and why.
- The Salesforce drift items to update by hand.
- The labels that `render` couldn't place.
- The sources that weren't available, such as locked transcripts or empty searches.

Ask before you upload anything to SharePoint.
