# Connector discovery findings

This page records what the connectors returned during discovery on 2026-09-30. Tony ran
read-only probes from Claude Code, with his own account, against one real account. No
customer data is recorded here.

## Microsoft 365

| Source | Works | How to read it |
|---|---|---|
| Calendar | Yes | `outlook_calendar_search` with the account name and `order: newest` returns attendees, dates, and the organizer. |
| Teams transcripts | Yes, for meetings Tony attended. One series was blocked. | See [Teams transcripts](#teams-transcripts). |
| Teams chats and channels | Yes | `chat_message_search` with KQL and a date filter returns message text, sender, date, and `webUrl`. |
| Outlook email | Yes | `outlook_email_search`, then `read_resource mail:///…`. Results are ranked by relevance, so sort them by date yourself. |
| SharePoint and OneDrive files | Yes | `sharepoint_search` by content, file name, file type, or folder, then `read_resource file:///…`, which converts .docx to text. |
| OneNote | Not tested | There is no OneNote tool. The notebook files may be readable. Treat OneNote as unsupported. |

### Teams transcripts

- Read the calendar event with `read_resource calendar:///…`. The event has a
  `meetingTranscriptUrl`. Reading that URL with `read_resource` returns WEBVTT with
  speakers and timestamps, about 50 KB an hour.
- It worked for a meeting Tony organized and for a meeting a colleague organized.
  Reading the series returned every transcript in the series.
- Read the series URL without `start` and `end`, and match the occurrence by the
  transcript's `createdDateTime`. The query for one occurrence's time window missed a
  transcript that existed.
- One recurring series returned HTTP 423, "Access to this site has been blocked". That
  is a lock on the organizer's storage, from an admin or retention lock or a
  deprovisioned account. It isn't a restriction on attendees.

### Write scopes

The granted Graph scopes include writes: `Mail.Send`, `ChatMessage.Send`,
`Files.ReadWrite.All`, and `Calendars.ReadWrite`. So the write-guard hook covers the
M365 write tools as well as C1. Send, reply, forward, and delete are denied. Upload asks
first.

### Plan store

Search found no team folder of account plans, only other teams' templates and notes.
This confirms that no plans existed yet. Tony still needs to pick or create the
SharePoint folder. OneDrive works until then.

## C1 and Salesforce

- C1 grants 28 Salesforce tools, all reads: 25 `salesforce_get_*` tools plus
  `salesforce_soql_query`, `salesforce_soql_query_all`, and `salesforce_soql_query_next`.
  The SOQL input is `{q}`.
- Field history works through SOQL. `OpportunityFieldHistory`, `AccountHistory`, and
  `ContractHistory` return `Field`, `OldValue`, `NewValue`, and `CreatedDate`. That gives
  the as-of date that the freshness rule needs. History covers only fields with history
  tracking turned on. For other fields, use the record's `LastModifiedDate` and mark it
  weak.
- Opportunity `Amount` changes often. One opportunity had several edits in a single day.
  Cite the value with its history date.

## What this changed in the design

- The skill gathers in this order: Salesforce records and field history, calendar events,
  transcripts, email and Teams chat, SharePoint files, local notes, and the baseline plan.
- A missing transcript is recorded as "no transcript", not as an error. The calendar
  still shows the meeting as dated contact.
- Transcripts are large, so the skill pulls quotes from them instead of passing them
  whole. `validate` checks each quote against the saved transcript text.
- Chats and meeting invites contain passcodes, so `atb-tools redact` runs over every
  saved source.

## SuperDuck (Black Duck data products)

- The join works. `core.customers.sfdc_id` is the 18-character Salesforce Account Id.
  There is one row per product (`polaris`, `continuous_dynamic`, `sca_phonehome`), with
  `next_renewal_date` and `has_active_contract`.
- `ACV` is NULL for all 3,912 external rows. The table docs say external customers should
  show 0.0 or a value, so this is a pipeline gap, not a problem with one account. Report
  it to the data team.
- The health tables `customer_scan_activity_comparison`,
  `customers_at_risk_scan_inactivity`, and `customers_consecutive_scan_decline` return no
  rows for the test account. They sort or filter by ACV, so the NULL ACV probably excludes
  it. This is unconfirmed.
- `core.scans`, joined through `customer_id`, has current scan counts and last-scan dates
  for each product and tool type (DAST, SAST, SCA, BLA). Health signals, such as recent
  activity compared with a baseline or days since the last scan, can be computed from it
  directly.
- `next_renewal_date` matched a Salesforce contract end date exactly, so it works as a
  cross-check.

SuperDuck is parked until the first version is done.

## Salesforce ACV

- `Account.ACV_Current__c` exists and is filled in for the test account. Tony confirmed it
  as the Current ARR source on 2026-09-30. `ACV_Pipeline__c` and
  `ACV_of_Largest_Renewal_of_the_Year__c` also exist.
- `ACV_Current__c` has no field history, so its as-of date is the Account's
  `LastModifiedDate`. Any edit to the Account changes that date.
- The test account has several active contracts with overlapping terms of 11, 12, and
  36 months. Dividing contract value by term would give the wrong ARR, so the bot doesn't
  do it.

## Atlassian

- Confluence has real content for the account: a TPM space page with the Salesforce Id,
  older meeting notes, services notes about pricing and partner risks, and a
  product-planning page that lists the account against feature requests. It is a good
  source for section 3 and for risks.
- Rovo search is fuzzy. A search for "Agilent" also returned unrelated Jira issues that
  matched "Agile". Each Rovo search can cost up to 10 Rovo credits. Use CQL through
  `searchConfluenceUsingCql` with exact phrases instead.
- Jira wasn't probed with JQL.

Atlassian is parked until the first version is done.
