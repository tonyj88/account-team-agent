# R0 — Connector discovery (2026-09-30)

Read-only probes, run from Claude Code with Tony's account, against one real account.
No customer data is recorded here.

## M365 connector
| Source | Result | How |
|---|---|---|
| Calendar | ✅ | `outlook_calendar_search` (query = account name, `order: newest`) → attendees, dates, organizer |
| **Teams transcripts** | ✅ for meetings Tony attended, whoever organized them · ⚠ one series was blocked | Read the event (`read_resource calendar:///…`) → its `meetingTranscriptUrl` → `read_resource` returns WEBVTT with speakers + timestamps (~50 KB/hr). Tested: a meeting Tony organized ✅; a meeting a colleague organized ✅ (the series read returned every transcript in the series). One recurring series returned **HTTP 423 "Access to this site has been blocked"**. That's a lock on that organizer's storage (an admin/retention lock, or the account is deprovisioned), not an attendee restriction. Read the series URL **without** `start/end` and match the occurrence yourself by the transcript's `createdDateTime`: the occurrence-window query missed a transcript that existed. |
| Teams chats + channels | ✅ | `chat_message_search` (KQL, date filter) → message text, sender, date, webUrl |
| Outlook email | ✅ | `outlook_email_search` + `read_resource mail:///…`; relevance-ranked, so sort by date yourself |
| SharePoint / OneDrive files | ✅ | `sharepoint_search` (content/filename, fileType, folder) + `read_resource file:///…` (docx → text) |
| OneNote | ⚠ not tested directly | There's no OneNote tool. It may be reachable through the notebook files; treat it as unsupported for now |

**Granted Graph scopes include writes** (`Mail.Send`, `ChatMessage.Send`,
`Files.ReadWrite.All`, `Calendars.ReadWrite`). So the guardrail hook must also cover
the M365 write tools (send, reply, forward, upload, create/delete event, and so on).
The only allowed write is the SharePoint upload in the publish step, and it always asks.

**Plan store:** no existing team account-plan folder was found. The only hits were other
teams' templates and notes, which confirms "no plans exist yet". → **Tony to pick or
create the SharePoint folder** (open item). OneDrive is fine until then.

## C1 → Salesforce
- 28 granted tools, all reads: 25 `salesforce_get_*` plus `salesforce_soql_query`,
  `salesforce_soql_query_all` and `salesforce_soql_query_next`. The SOQL input is `{q}`.
- **Field history works through SOQL:** `OpportunityFieldHistory`, `AccountHistory`
  and `ContractHistory` return Field / OldValue / NewValue / CreatedDate. That gives the
  per-field **as-of date** the freshness rule needs. It only covers fields with history
  tracking turned on; for anything else, fall back to the record's `LastModifiedDate`,
  marked low-confidence.
- Opportunity `Amount` changes often (several edits within a single day were
  observed), so the plan should cite the value together with its history date.

## Consequences for the design
1. **Gather order per account:**
   - Salesforce records plus field history.
   - Calendar events in the review window.
   - Transcripts for the meetings Tony attended.
   - Email and Teams chat hits.
   - SharePoint/OneDrive docs.
   - Local notes.
   - The baseline plan.
2. **Missing transcripts** (423-locked organizer storage, or none recorded) are recorded as "no transcript", not
   treated as an error. The meeting still counts as dated evidence of contact, from the
   calendar.
3. **Transcripts are large** (~50 KB/hr). The skill pulls candidate quotes from them;
   `validate` checks each quote verbatim against the saved transcript text.
4. **Redaction still applies:** chats and invites contain meeting passcodes and system
   details, so the secret scan runs over everything the skill saves.

# R0b — SuperDuck + Atlassian (2026-09-30)

## SuperDuck (Black Duck data products)
- **Join works:** `core.customers.sfdc_id` = the Salesforce Account Id (18-char). There's
  one row per product (polaris, continuous_dynamic, sca_phonehome), plus
  `next_renewal_date` and `has_active_contract`.
- **ACV is unusable right now:** `ACV` is NULL for **all** external rows (3,912/3,912).
  The table docs say external customers should show 0.0 or a value, so this is a
  pipeline gap, not something specific to Agilent. Report it to the data team.
- **Health marts miss the test account:** `customer_scan_activity_comparison`,
  `customers_at_risk_scan_inactivity` and `customers_consecutive_scan_decline` return no
  rows for it. These marts are ordered/filtered by ACV, so the NULL ACV probably
  excludes the account. Unconfirmed.
- **Raw scan data is rich and current:** `core.scans` joined through `customer_id`
  gives scan counts and last-scan dates for each product and tool type (DAST, SAST,
  SCA, BLA). → Compute health signals (recent vs. baseline activity, days since last
  scan) **ourselves from `core.scans`**, which is deterministic and needs little code.
  Don't depend on the ACV-ordered marts.
- `next_renewal_date` matched a Salesforce contract end date exactly, which makes it
  a good cross-check.

## Salesforce ACV (replacement ARR source)
- `Account.ACV_Current__c` exists and is populated for the test account. There's also
  `ACV_Pipeline__c` and `ACV_of_Largest_Renewal_of_the_Year__c`.
- **No field history** is tracked for `ACV_Current__c`. Its as-of date is therefore the
  Account's `LastModifiedDate`, which is a weak signal (any edit updates it).
- The Account has several active Contracts with overlapping terms (11, 12 and
  36 months). That makes a TCV ÷ term calculation error-prone, so it's only a
  cross-check.

## Atlassian (Rovo search)
- Confluence has real per-account content: a TPM space page with the account's
  Salesforce Id, older meeting notes, services notes (pricing and partner risks), and
  a product-planning page that lists the account against specific feature requests.
  → This is a good source for **section 3 (ERs / feature requests)** and for risks.
- Rovo search is fuzzy. A plain "Agilent" search also returned unrelated Jira issues
  ("Agile ..."). Use CQL/JQL with exact phrases when building. **Each Rovo search can
  cost up to 10 Rovo credits**, so prefer CQL (`searchConfluenceUsingCql`) in the skill.
- Jira wasn't probed with JQL yet. Do it during R4 when the skill's gather step is
  built.
