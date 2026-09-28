# C1 → Salesforce/ZoomInfo access test (Phase G0)

Goal: find out whether Claude Code on Tony's laptop can read Salesforce, Zendesk and
ZoomInfo through C1-governed MCP access, and if not, get a **specific** ask for the C1
admin. Run on the laptop (needs company SSO); this cloud session can't reach C1.

Rules for the test:
- Read-only. Only list tools and run one lookup on a single account you own.
- Don't paste customer data into any chat outside the company gateway. Record only
  pass/fail and error messages in the results table at the bottom.

Docs used: c1.ai/docs/product/how-to/ai-tools and
c1.ai/docs/product/how-to/connect-mcp-client (checked 2026-09-28).

C1 documents two ways in. Try **Path A first** (simpler, no admin-issued secrets).

---

## Path A — C1's own MCP URL (C1 acts as the tool gateway)

**A1. Does your C1 tenant expose AI connections?**
In the C1 web app: profile menu → **AI & API** → **AI connections** tab.
- ✅ You see an **MCP server URL** → copy it, go to A2.
- ❌ No "AI & API" menu or no "AI connections" tab →
  **Ask admin:** "Please enable AI connections (MCP) in C1 for my user so I can connect
  Claude Code to C1-governed tools."

**A2. Is Claude Code allowed to add it?**
```bash
claude mcp add --transport http c1 <MCP server URL from A1>
claude mcp list
```
- ✅ `c1` listed → go to A3.
- ❌ Error about policy/managed settings/blocked server →
  **Ask IT (Claude Code admin, not C1):** "Please allow the C1 MCP server
  `<URL>` in our managed Claude Code settings."

**A3. Can you sign in?**
Start `claude`, run `/mcp`, select `c1`, authenticate in the browser.
- ✅ Shows connected → go to A4.
- ❌ Auth error / redirect refused →
  **Ask admin:** "Claude Code's OAuth sign-in to C1's MCP URL fails with `<error>`;
  please allow Claude Code as an MCP client (loopback redirect) in C1."

**A4. Which tools do you already have?**
In `/mcp`, open `c1` and look at its tool list (or ask Claude: "list the tools the c1
MCP server gives you").
- Note any tool whose name mentions **salesforce**, **zendesk** or **zoominfo**.
- ✅ Present → go to A6.
- ❌ Missing → go to A5.

**A5. Can you request them?**
C1 web app → **Requests** → search the catalog for Salesforce / Zendesk / ZoomInfo
**toolsets** (AI tool access profiles, not the normal app access you already have).
- ✅ Toolset exists → request it (justification: "read-only account data for account
  plans"), wait for approval, reconnect (`/mcp` → re-authenticate), repeat A4.
- ❌ No toolset in the catalog →
  **Ask admin:** "Please register a read-only MCP toolset for Salesforce (and Zendesk,
  ZoomInfo) in C1 and make it requestable. Use case: filling our Account Plan template
  from account, opportunity, ticket and contact data."

**A6. Does a read-only lookup work?**
Ask Claude Code, e.g.: "Using the salesforce tool, return the Account Owner, ARR and
renewal date for account `<one account you own>`. Don't show anything else."
- ✅ Returns data → **G0 is viable.** Record which tool names worked.
- ❌ `Access denied: tool ... is not in your current tool list` → toolset not approved
  or session expired: re-authenticate; if it persists, **ask admin** to check the
  approval.
- ❌ Tool runs but returns permission/field errors →
  **Ask admin / Salesforce owner:** "The C1 Salesforce toolset lacks read access to
  `<object/field>` (Account, Opportunity, Asset/Product)."

---

## Path B — Enterprise-managed authorization (XAA), only if Path A isn't offered

Needs admin-issued values up front, so it's mainly useful as a precise ask.
Claude Code support is **experimental**.

**B1. Collect from the C1 admin** (this list *is* the ask):
- C1 issuer URL
- Agent client ID + secret at C1 for Claude Code
- For each server (Salesforce / Zendesk / ZoomInfo MCP): server URL, client ID + secret
  at that server's authorization server, and confirmation that the server trusts C1 as
  a token issuer
- Confirmation your access to each server is granted in C1

**B2. Run the setup:**
```bash
export CLAUDE_CODE_ENABLE_XAA=1
export MCP_XAA_IDP_CLIENT_SECRET='<C1 agent client secret>'
claude mcp xaa setup --issuer <C1 issuer URL> --client-id <C1 agent client ID> --client-secret
claude mcp xaa login
claude mcp add --xaa --transport http salesforce <server URL> --client-id <server client ID> --client-secret
claude mcp xaa show
```
Then repeat A4 and A6 with the `salesforce` server. Useful resets:
`claude mcp xaa login --force`, `claude mcp xaa clear`.

Don't commit any of these secrets or paste them into chat.

---

## Also check (applies to both paths)
- **Company Claude Code setup:** you run Claude Code through the company LiteLLM
  gateway. MCP tools run on your laptop, independent of the model gateway, but managed
  settings can still block MCP servers (see A2).
- **Allowed data use:** confirm with your manager/IT that pulling CRM data into a local
  tool is allowed (it stays on the laptop; redaction runs at ingest).

## A7 — Which apps can C1 reach? (discovery, read-only)

C1 shows a small set of meta-tools (`search_tools`, `execute`, `find_api_objects`,
`list_guides`, …), not one tool per app. Ask Claude Code:

> Using the c1 MCP server, call `list_guides`, then `search_tools` for "salesforce",
> "zendesk" and "zoominfo". Show only the tool names and descriptions you find, and
> whether each is read-only. Do not call `execute`.

- ✅ Zendesk / ZoomInfo tools listed → note the names; they plug into the same
  `/pull-account` skill.
- ❌ Not listed → **ask admin:** "Please add read-only Zendesk (tickets) and ZoomInfo
  (company + contacts) toolsets to C1's AI connections for my user."

When Claude asks to run `execute`, approve only reads — never an update, create or
delete.

## Results (fill in, then paste this table — no customer data — into CHECKPOINT)

| Step | Result (✅/❌) | Error message / notes |
|---|---|---|
| A1 AI connections visible | ✅ | 2026-09-28: "Connect AI assistants to C1" section shows an MCP server URL (copy it from the C1 UI; not stored in the repo) |
| A2 Claude Code can add URL | ✅ | |
| A3 Sign-in works | ✅ | |
| A4 Tools present (which?) | ✅ | Meta-tools: search_tools, execute (destructive), find_api_objects, count_api_objects, get_execution, list/load_guide, vfs tools. App tools are found via search_tools (A7) |
| A5 Toolsets requestable | n/a | Salesforce already granted |
| A6 Read-only lookup works | ✅ | 2026-09-28: owner, active contract, renewal returned (7 tool calls). No ARR field — Amount is TCV |
| A7 App tools found | ✅ | Salesforce: 28 read tools + `salesforce/quirks` guide. ZoomInfo: 4 (list/enrich company, contact). Zendesk: not connected — not needed (internal IT only) |
| B (if used) | | |
