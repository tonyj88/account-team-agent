# R0 — Connector discovery (2026-09-30)

Read-only probes, run from Claude Code with Tony's account, against one real account.
No customer data is recorded here.

## M365 connector
| Source | Result | How |
|---|---|---|
| Calendar | ✅ | `outlook_calendar_search` (query = account name, `order: newest`) → attendees, dates, organizer |
| **Teams transcripts** | ✅ **for meetings Tony organizes** · ❌ others' meetings | Read the event (`read_resource calendar:///…`) → its `meetingTranscriptUrl` → `read_resource` returns WEBVTT with speakers + timestamps (~50 KB/hr). On a recurring series organized by someone else, Graph lists the transcript but returns **HTTP 423 Locked**, and some occurrences have no transcript at all. |
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
   - Transcripts for the meetings Tony organized.
   - Email and Teams chat hits.
   - SharePoint/OneDrive docs.
   - Local notes.
   - The baseline plan.
2. **Missing transcripts** (423 or none recorded) are recorded as "no transcript", not
   treated as an error. The meeting still counts as dated evidence of contact, from the
   calendar.
3. **Transcripts are large** (~50 KB/hr). The skill pulls candidate quotes from them;
   `validate` checks each quote verbatim against the saved transcript text.
4. **Redaction still applies:** chats and invites contain meeting passcodes and system
   details, so the secret scan runs over everything the skill saves.
