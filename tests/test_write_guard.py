"""Synthetic connector calls exercise the write guard without network access."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/hooks/write_guard.py"
SPEC = importlib.util.spec_from_file_location("write_guard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
GUARD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUARD)


def call(tool: str, tool_input: object = None, server: str = "C1-install") -> dict:
    return {
        "tool_name": f"mcp__{server}__{tool}",
        "tool_input": {} if tool_input is None else tool_input,
    }


@pytest.mark.parametrize("key", ["tool_name", "tool", "name", "toolName", "function"])
@pytest.mark.parametrize("nested", [False, True])
def test_app_name_keys(key: str, nested: bool) -> None:
    payload = {key: "salesforce_get_account"}
    result = GUARD.decide(call("execute", {"request": payload} if nested else payload))
    assert result[0] == "allow"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("salesforce_get_account", "allow"), ("ZOOMINFO_LIST_COMPANIES", "allow"),
        ("list_companies", "allow"), ("list_contacts", "allow"),
        ("enrich_company", "ask"), ("enrich_contact", "ask"),
        ("zoominfo_enrich_contact", "ask"), ("salesforce_update_account", "deny"),
        ("zoominfo_delete_contact", "deny"), ("unknown", "deny"),
    ],
)
def test_execute_allowlist(name: str, expected: str) -> None:
    decision, reason = GUARD.decide(call("execute", {"tool_name": name}))
    assert decision == expected
    assert name.lower() in reason


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT Id FROM Account WHERE Name = 'delete me'", "allow"),
        (" \nselect Id FROM Account WHERE Name = 'Acme Corp'", "allow"),
        ("SELECT Id FROM Account WHERE Name = 'Jane\\'s delete'", "allow"),
        ("SELECT Id FROM Account WHERE Name = 'Jane''s update'", "allow"),
        ('SELECT Id FROM Account WHERE Name = "delete me"', "allow"),
        ("SELECT UpdatedDate FROM Account", "allow"),
        ("DELETE FROM Account", "deny"), ("UPDATE Account", "deny"),
        ("FROM Account", "deny"), ("SELECT Id FROM Account; INSERT Account", "deny"),
        ("SELECT Id FROM Account UPSERT Account", "deny"),
        ("SELECT Id FROM Account MERGE Account", "deny"),
        ("SELECT Id FROM Account DELETE Account", "deny"),
        ("SELECT Id FROM Account UPDATE Account", "deny"),
        ("SELECT Id FROM Account WHERE Name = 'unterminated", "deny"),
        (None, "deny"), (123, "deny"), ("", "deny"),
    ],
)
@pytest.mark.parametrize("name", ["salesforce_soql_query", "salesforce_soql_query_all",
                                 "salesforce_soql_query_next"])
def test_soql(name: str, query: object, expected: str) -> None:
    payload = {"tool": name, "arguments": {"deep": [{"q": query}]}}
    assert GUARD.decide(call("execute", payload))[0] == expected


@pytest.mark.parametrize("key", ["q", "query", "soql", "SOQL"])
def test_every_query_must_be_safe(key: str) -> None:
    payload = {"tool": "salesforce_soql_query", "q": "SELECT Id FROM Account",
               "args": [{key: "DELETE FROM Account"}]}
    assert GUARD.decide(call("execute", payload))[0] == "deny"


@pytest.mark.parametrize("payload", [{}, {"tool": "salesforce_soql_query"},
                                      {"tool": 123}, {"tool": " "},
                                      {"tool": "salesforce_get_account", "name": "delete"}])
def test_missing_or_ambiguous_name_and_query(payload: dict) -> None:
    assert GUARD.decide(call("execute", payload))[0] == "deny"


@pytest.mark.parametrize("tool", sorted(GUARD._READ_C1))
def test_c1_helpers(tool: str) -> None:
    assert GUARD.decide(call(tool))[0] == "allow"


@pytest.mark.parametrize("tool", ["create_vfs", "create_vfs_file", "get_vfs_download_url",
                                  "unknown_tool"])
def test_c1_approval(tool: str) -> None:
    assert GUARD.decide(call(tool))[0] == "ask"


@pytest.mark.parametrize(
    ("tool", "expected"),
    [(f"get_{action}", "deny") for action in GUARD._DENY_M365]
    + [(f"get_{action}_file", "ask") for action in GUARD._ASK_M365]
    + [(f"resource_{action}", "allow") for action in ("search", "read", "get", "list")]
    + [("unknown_tool", "ask"), ("outlook_email_search", "allow"),
       ("outlook_calendar_search", "allow"), ("chat_message_search", "allow"),
       ("sharepoint_search", "allow"), ("sharepoint_share_file", "ask"),
       ("sharepoint_upload_file", "ask"), ("read_resource", "allow"),
       ("upload_and_send", "deny")],
)
def test_m365_precedence(tool: str, expected: str) -> None:
    assert GUARD.decide(call(tool, server="M365-install"))[0] == expected


@pytest.mark.parametrize("server", ["c1", "ConductorOne-install"])
def test_c1_server_matching(server: str) -> None:
    assert GUARD.decide(call("unknown_tool", server=server))[0] == "ask"


@pytest.mark.parametrize("server", GUARD._M365_SERVERS)
def test_m365_server_matching(server: str) -> None:
    assert GUARD.decide(call("send_mail", server=server.upper()))[0] == "deny"


@pytest.mark.parametrize("tool", ["execute", "search_tools", "create_vfs_file",
                                  "outlook_email_search", "chat_message_search",
                                  "sharepoint_search", "teams_send_message", "read_resource"])
def test_tool_matching_on_unfamiliar_server(tool: str) -> None:
    assert GUARD.decide(call(tool, server="unfamiliar")) is not None


@pytest.mark.parametrize("payload", [None, [], {}, {"tool_name": 3},
                                      call("execute", tool_input=[]),
                                      {"tool_name": "mcp__c1__execute"}])
def test_malformed_payload(payload: object) -> None:
    assert GUARD.decide(payload) == ("deny", "write_guard could not parse the tool call")


@pytest.mark.parametrize("tool", ["Bash", "Read", "mcp__other__lookup", "mcp__bad"])
def test_unrelated_tools(tool: str) -> None:
    assert GUARD.decide({"tool_name": tool, "tool_input": {}}) is None


@pytest.mark.parametrize(
    ("stdin", "expected"),
    [(json.dumps(call("outlook_email_search", server="microsoft")), "allow"),
     (json.dumps({"tool_name": "Bash", "tool_input": {}}), None),
     ("not JSON", "deny"), ("[]", "deny"), ("", "deny")],
)
def test_script(stdin: str, expected: str | None) -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], input=stdin, text=True,
                            capture_output=True, check=False)
    assert result.returncode == 0
    assert result.stderr == ""
    if expected is None:
        assert result.stdout == ""
    else:
        response = json.loads(result.stdout)["hookSpecificOutput"]
        assert response["hookEventName"] == "PreToolUse"
        assert response["permissionDecision"] == expected
        if expected == "deny":
            assert response["permissionDecisionReason"] == (
                "write_guard could not parse the tool call"
            )


def test_settings() -> None:
    settings = json.loads((SCRIPT.parent.parent / "settings.json").read_text())
    assert settings == {"hooks": {"PreToolUse": [{"matcher": "mcp__.*", "hooks": [{
        "type": "command",
        "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/write_guard.py"',
    }]}]}}


def test_app_arguments_named_name_do_not_block() -> None:
    payload = {"tool_name": "salesforce_get_account", "arguments": {"name": "Acme Corp"}}
    assert GUARD.decide(call("execute", payload))[0] == "allow"


def test_nested_name_still_checked_when_top_level_has_none() -> None:
    payload = {"call": {"tool": "salesforce_update_account"}}
    assert GUARD.decide(call("execute", payload))[0] == "deny"
