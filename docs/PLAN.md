# Account Team Bot — Plan (source of truth, adopted 2026-09-30; supersedes the 2026-09-28 pipeline plan, see git history)

## Context
The current `docs/PLAN.md` (2026-09-28) builds a Python pipeline that ingests notes,
makes its own LLM calls, stores facts in local SQLite, and reaches Salesforce and the
team through later phases: G (C1 snapshots), H (Copilot agent), H-fallback (Cloudflare)
and J (FastAPI). With Claude Enterprise we now have:
- **C1 connector:** live Salesforce (28 read tools) plus ZoomInfo.
- **M365 connector:** Outlook mail and calendar, Teams chats and channels, SharePoint
  search and upload.
- **Teammates:** no Claude access, but they have C1 through M365 Copilot (Salesforce
  only; it can't see our M365-derived notes).

`scripts/fill_agilent_plan.py` (untracked) is the proof: one Claude session pulled
Salesforce through C1, read the notes and filled the real template. Tony's decisions
(2026-09-30):
- **Runtime:** Claude-native. Skills do the gathering and judgement; Python becomes a
  small deterministic toolkit.
- **Note sources:** local Markdown/Obsidian, Teams transcripts/recaps, Outlook email,
  SharePoint/OneNote. All four count.
- **Transcripts replace manual recap copying (Tony, 2026-09-30):** R0 showed the skill
  can read transcripts for any meeting Tony attended.
  - Obsidian becomes Tony's *side notes*: his own observations and context typed during
    or after a meeting.
  - Older Obsidian notes may hold pasted recaps. When a note and a transcript cover the
    same meeting (same account, same date), reconcile treats them as **one meeting**,
    not two sources that independently confirm each other. The transcript is the
    primary text to quote.
  - A side note's date ties it to that day's meeting, so its quotes sit next to the
    transcript's in the evidence file.
- **Plan store:** a versioned .docx plus an evidence file in a team SharePoint folder.
  The latest approved plan is the baseline for the next refresh. Tony uploads to
  Salesforce by hand.

## What carries over vs. what's retired
**Keep (the real value):** the MVP scope (sections 1, 4, 5, 10, 11 plus trigger
alerts); `config/account_plan_fields.yaml` and `docs/ACCOUNT_PLAN_MAPPING.md`; the
Salesforce-object → section table; the ARR derivation rule (TCV ÷ term, needs
approval); renewal cross-check; review cadence (≥$150k quarterly, otherwise
semiannual); triggers; the human approval rule; "Claude fetches, code decides"; the C1
write-safety allowlist hook; redaction of secrets.

**Retire / freeze:** Phases B, C (the LLM extraction redesign), G0/G1 snapshot
pipeline, H, H-fallback, J; the ingest connectors (folder, IMAP, Obsidian); SQLite
AccountFact; `qa/` Q&A (Claude with connectors answers team questions directly). The
existing `src/atb` code stays in git history and is moved under `legacy/` or tagged
`v0-pipeline`, not maintained.

## New architecture
```
Tony in Claude Code (laptop) — sole operator for now
  └─ project skill: /account-plan <account>   (.claude/skills/ in this repo)
       1. Gather   C1 → Salesforce (Account, Contract, Opp, Contact, OCR, Case, Task/Event)
                   M365 → Outlook threads, Teams recaps/chats, SharePoint/OneNote notes
                   local notes (Claude Code only) ; ZoomInfo list_* (enrich = ask)
                   SharePoint → last approved plan (baseline)
       2. Draft    candidates.json: per field, ALL candidate values with source, as_of
                   date, SF record ID+field or doc URL + verbatim quote
       2b. Reconcile  atb-tools reconcile → plan.json (freshness rule) + sf_drift.md
       3. Check    atb-tools validate plan.json  (deterministic Python)
       4. Render   atb-tools render → <acct>_<date>.docx + <acct>_evidence.md
       5. Publish  SharePoint upload to team folder (asks first); diff vs. baseline shown
```
Other skills: `/plan-due` (cadence + triggers across accounts the user owns, ranked by
ARR and renewal), `/plan-review <account>` (walk through the values that need approval
and record the decisions in plan.json → re-render).

## Goal and freshness rule (Tony, 2026-09-30)
**The goal** is to fill `data/templates/account_plan.docx.docx` for any account with
the most accurate information available.

**Salesforce is not automatically the truth.** It goes stale when nobody types in what
was said in a meeting or an email. So:
- **Every evidence item carries an as-of date:**
  - Salesforce: the field's history date (`*History` / `LastModifiedDate` on the
    record).
  - Email: the sent date.
  - Teams transcript/recap: the meeting date.
  - Note: the frontmatter or file date.
  - Baseline plan: the date it was approved.
- **Per field, the newest credible evidence wins, whatever the source.** The chain
  is: human-approved override > newest dated evidence > older evidence. Older values
  are kept as history in the evidence file, not discarded.
- **Newer non-Salesforce evidence contradicting Salesforce** (for example, the renewal
  slipped, the champion left, or the deal size changed on a call) means:
  - The newer value goes in the plan.
  - It is marked `needs_approval`.
  - The evidence file shows both values with their dates.
  - The value is listed in a **"Salesforce drift" report** (`<acct>_sf_drift.md`) so
    Tony can update Salesforce by hand. The bot still never writes to Salesforce.
- **Contractual and system-of-record fields** (ACV/ARR, contract end date, contract
  amount/TCV, products purchased) are different. A conversation can only *flag* them ("customer
  says renewal moves to Q2"), not replace them. The plan shows the Salesforce value
  plus the flagged change, marked ⚠.
- **Where the rule lives:** the `validate`/`reconcile` code applies it
  deterministically from the dated evidence the skill collects. The skill's job is to
  gather candidate values with dates and quotes, not to decide which one wins.

## Transcript handling: filtering out the noise (Tony, 2026-09-30)
Transcripts cover the whole meeting (~12k tokens/hr). The skill **extracts evidence for
each plan field; it never summarizes the meeting.**
1. **Preprocess (deterministic, `atb-tools transcript clean`):** parse the WEBVTT; drop
   filler turns (short acknowledgements, greetings); merge consecutive turns by the same
   speaker; tag each speaker `customer` or `internal`, using the Teams org label (e.g.
   "(Agilent USA)") or the email domain from the calendar attendees; keep timestamps.
   Save the cleaned text, because it is what `validate` checks quotes against.
2. **Extract by field (Claude, in the skill):**
   - Input is the cleaned transcript plus the field catalog: MEDDPICC elements,
     stakeholders/roles, risks, actions (owner + due date), competition, commercial
     terms, and trigger events.
   - Output is a list of candidates: field, value, verbatim quote, timestamp, speaker,
     speaker side and confidence.
   - Anything that maps to no field (small talk, demo narration, scheduling chatter) is
     dropped.
3. **Speaker weighting (in reconcile code):** customer statements are the evidence for
   pain, metrics, decision criteria, decision process and competition. Internal
   statements are the evidence for our commitments and actions. Internal pitch or
   opinion is never evidence of what the customer believes, so such candidates are
   capped at low confidence and flagged `needs_approval`.
4. **Cache:** candidates are stored per transcript ID
   (`data/cache/transcripts/<id>.json`, gitignored). A refresh only extracts transcripts
   newer than the baseline plan, or ones not in the cache yet.
5. **Checks:** every quote must appear verbatim in the cleaned transcript, and its
   timestamp must fall inside the meeting. The evidence file shows the meeting, the
   timestamp and the speaker for each quote.

Tests (R2/R3): VTT parsing and filler removal on a synthetic transcript; speaker-side
tagging; cache hits and misses; the quote-verbatim check fails on a paraphrased quote;
an internal-speaker candidate for a customer-belief field gets downgraded.

## Accelerators: use before building (Tony, 2026-09-30)
- **ARR = Salesforce `Account.ACV_Current__c`** (confirmed by Tony, 2026-09-30).
  - Commercial fields in Salesforce are reliable. Contacts and notes are the fields
    that go stale.
  - ACV/ARR is treated as a **system-of-record field**: it is trusted without
    needing approval just because its as-of date is weak. A conversation can only
    *flag* a change to it, never replace it.
  - Cross-checks (flag only): the SuperDuck renewal date against the Salesforce
    contract end dates.
  - SuperDuck ACV is not used, and nobody needs to be told about the gap.
- **Health and adoption:** compute from SuperDuck `core.scans` (joined via
  `sfdc_id`), because the enterprise marts below miss accounts with NULL ACV. They
  stay useful for checking a portfolio-wide at-risk list:
  - Tables: `customers_at_risk_scan_inactivity`,
    `customers_consecutive_scan_decline`, `customer_scan_activity_comparison`,
    `customers_without_scans`.
  - These feed Snapshot R/A/G, section 3, risks and churn triggers.
  - Open findings by severity over time is the value metric for MEDDPICC Metrics.
  - Limitation: there is no scan-level data for on-prem SCA/Hub customers.
- **ZoomInfo** (through C1, `list_*` only): company size, funding and reorgs for
  triggers; contact titles and reporting lines for sections 5 and 6.
- **Atlassian (Jira/Confluence):** customer feature requests and escalations for
  section 3 and product-gap risks, if they are tracked there (probed in R0b).
- **docx skill:** does the Word manipulation. Our `render` shrinks to a field → cell
  map, the ⚠ markers, and a layout check.
- **Scheduled tasks:** a weekly `/plan-due` run with an alert when an account is due or
  a trigger fires. Nothing to host.
- **Artifacts** (optional, decide before R5): a private approval page instead of the
  `/plan-review` CLI. Customer data would be hosted on claude.ai.
- **Not available:** Gong, Gainsight and Zoom are not in the registry, and C1 exposes
  only Salesforce and ZoomInfo as business apps.

## Deterministic toolkit (`atb-tools`, the slimmed Python package)
All pure functions, unit-tested, and none of them call an LLM:
- `schema/plan.schema.json`: the plan.json contract generated from
  `account_plan_fields.yaml` (scalar fields plus repeating rows for Stakeholder, Risk
  and Action).
- `validate`: every non-empty value has ≥1 source; quotes must appear verbatim in the
  cited text (the skill saves fetched source text alongside the plan); the approval
  rule is applied in code (low confidence / `llm_draft` / sources disagree / stale
  ⇒ `needs_approval`); only a human can set `approved`, which means the value carries
  forward from the baseline or was changed in `/plan-review`; a secret-pattern scan
  reuses `src/atb/redact.py`.
- `derive`: ARR = Salesforce ACV_Current__c with cross-checks; scan-activity health from core.scans; renewal date + cross-check against the open renewal
  opp, 30/60/90 bucketing, review-due date, the "renewal in final two quarters" trigger.
- `render`: fills the template .docx. Generalize `scripts/fill_agilent_plan.py` into a
  heading-located table filler and add a visible ⚠ marker on unapproved values. Also
  writes the evidence .md.
- `reconcile`: for each field, takes the candidate values (value, source, as_of,
  quote/record) and applies the freshness rule. It picks the winner, marks
  `needs_approval` when sources disagree, and writes the Salesforce drift report.
- `diff`: plan.json vs. the baseline plan.json, for the change summary and the
  supersession history.
- CLI: `atb-tools validate|derive|render|diff|due`. Skills call it through Bash in
  Claude Code. For claude.ai (no local Python), see the open item below.

## Guardrails
- C1 `execute` allowlist hook (from the old Phase G) is still required before any
  teammate rollout. M365 writes (SharePoint upload, drafts, sending) are always "ask",
  and email/Teams sends are never allowed.
- The template and customer data never get committed. `data/` stays gitignored, and
  plans live in SharePoint.

## New phases
| # | Deliverable | Notes |
|---|---|---|
| R0 | Discovery: confirm through M365 whether Teams meeting transcripts/recaps and OneNote are actually reachable (tool list shows chats/channels/SharePoint search, not transcripts); pick the SharePoint team folder; confirm C1 tool names | read-only; decides step 1's source list |
| R1 | Rewrite `docs/PLAN.md`, `CHECKPOINT.md`, `CLAUDE.md`, agents' invariants; move old pipeline to `legacy/` | docs + move only |
| R2 | `plan.schema.json` + `validate` + `derive` + tests | architect (O5) designs schema |
| R3 | `render` (generalized from fill_agilent_plan.py, synthetic fixture docx in tests) + evidence file + `diff` | |
| R4 | `/account-plan` skill (Claude Code first) + C1 allowlist hook; run on Agilent and compare with the hand-made Agilent plan | live run, ask Tony |
| R5 | `/plan-review`, `/plan-due` (cadence + triggers) | |
| R6 | Team access *without* Claude seats (later): plans + evidence + a per-account "brief.md" published to the SharePoint folder, so teammates' **M365 Copilot** (which already has C1 → Salesforce) can ground on the curated M365-derived content. Revisit Claude seats / querying via Tony later | IT/Copilot check |

## Open items for Tony
- ARR definition: decided (SuperDuck ACV). Still open: the SharePoint folder for the plan store.
- **Single operator for now (Tony, 2026-09-30):** teammates have no Claude access. Only
  Tony runs the skills, in Claude Code on the laptop, so the local Python toolkit and
  the Obsidian notes both work as they are. Teammates get the published SharePoint
  outputs and ask Tony. Claude seats for them, or queries through Tony's account,
  are a later decision.
- Teammates' Copilot + C1 already covers Salesforce. What it lacks is the M365-derived
  facts (notes, emails, Teams), and the published plan, evidence file and brief.md
  fill that gap (R6).

## Verification
- `uv run pytest` / `ruff` green. Tests cover the approval rule, quote-verbatim
  checks, ARR/renewal derivation, 30/60/90 buckets, due dates, docx fill against a
  synthetic fixture, and the secret scan.
- R4: `/account-plan Agilent` produces a docx that opens in Word with the layout
  intact. Every MVP value has an evidence line whose source resolves (SF record ID or
  M365 URL + quote). Unapproved values show ⚠. The C1 hook blocks a non-allowlisted
  `execute`. Nothing gets uploaded without a prompt.
- Freshness tests:
  - An email dated after the Salesforce field's last change overrides a
    non-contractual field and appears in `sf_drift.md`.
  - An older email loses to Salesforce.
  - A conversation that contradicts the contract end date flags the field but doesn't
    replace it.
- R4 live check: find at least one real Agilent field where Teams/email is newer than
  Salesforce and confirm the plan uses it and flags it.
- R5: `/plan-due` lists an account with no plan and a ≥$150k account overdue.
