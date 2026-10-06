"""Decide whether connector calls may proceed before Claude Code executes them."""

from __future__ import annotations

import json
import re
import sys
from typing import Literal

Decision = tuple[Literal["allow", "ask", "deny"], str]
_NAME_KEYS = {"tool_name", "tool", "name", "toolName", "function"}
_READ_C1 = {
    "search_tools", "find_api_objects", "count_api_objects", "get_execution",
    "list_guides", "load_guide", "list_vfs_files",
}
_C1_TOOLS = _READ_C1 | {"execute", "get_vfs_download_url"}
_C1_SERVERS = ("c1", "conductorone")
_M365_SERVERS = ("m365", "microsoft", "outlook", "sharepoint", "teams")
_DENY_M365 = (
    "send", "reply", "forward", "post_message", "send_message", "create_event",
    "update_event", "delete", "cancel_event", "move", "mark",
)
_ASK_M365 = ("upload", "create", "update", "write", "copy", "share")
_WRITE_WORD = re.compile(r"\b(?:INSERT|UPDATE|DELETE|UPSERT|MERGE)\b", re.IGNORECASE)
_LITERAL = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\")*\"")


def _names_in(container: dict) -> set[str]:
    return {
        value.strip().lower()
        for key, value in container.items()
        if key in _NAME_KEYS and isinstance(value, str) and value.strip()
    }


def _app_names(tool_input: dict) -> list[str]:
    # The app tool's own arguments (e.g. {"name": "Acme"}) sit one level down, so a
    # top-level name wins; nested keys are only a fallback.
    names = _names_in(tool_input)
    if not names:
        for value in tool_input.values():
            if isinstance(value, dict):
                names |= _names_in(value)
    return sorted(names)


def _queries(value: object) -> list[object]:
    queries = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {"q", "query", "soql"}:
                queries.append(child)
            queries.extend(_queries(child))
    elif isinstance(value, list):
        for child in value:
            queries.extend(_queries(child))
    return queries


def _safe_soql(query: object) -> bool:
    if not isinstance(query, str) or not re.match(r"\s*SELECT\b", query, re.IGNORECASE):
        return False
    unquoted = _LITERAL.sub(" ", query)
    # Unmatched quotes cannot establish that a write word is safely inside a literal.
    return not any(quote in unquoted for quote in ("'", '"')) and not _WRITE_WORD.search(
        unquoted
    )


def _execute(tool_input: dict) -> Decision:
    names = _app_names(tool_input)
    seen = ", ".join(names) or "no app tool name"
    if len(names) != 1:
        return "deny", f"C1 execute saw {seen}; a single allowlisted app tool is required"
    name = names[0]
    if name.startswith("salesforce_soql_query"):
        queries = _queries(tool_input)
        if queries and all(_safe_soql(query) for query in queries):
            return "allow", f"C1 execute {name}: all SOQL is read-only SELECT"
        return "deny", f"C1 execute {name}: missing or unsafe SOQL"
    if name.startswith(("salesforce_get_", "zoominfo_list_")) or name in {
        "list_companies", "list_contacts",
    }:
        return "allow", f"C1 execute {name}: allowlisted read"
    if name.startswith(("enrich_", "zoominfo_enrich_")):
        return "ask", f"C1 execute {name}: enrichment requires approval"
    return "deny", f"C1 execute {name}: app tool is not allowlisted"


def decide(call: object) -> Decision | None:
    """Return a permission and reason, or no opinion for unrelated tools."""
    if not isinstance(call, dict) or not isinstance(call.get("tool_name"), str):
        return "deny", "write_guard could not parse the tool call"
    name = call["tool_name"].lower()
    parts = name.split("__", 2)
    if len(parts) != 3 or parts[0] != "mcp" or not all(parts[1:]):
        return None
    server, tool = parts[1:]
    is_c1 = (
        any(marker in server for marker in _C1_SERVERS)
        or tool in _C1_TOOLS or tool.startswith("create_vfs")
    )
    is_m365 = any(marker in server for marker in _M365_SERVERS) or tool.startswith(
        ("outlook_", "sharepoint_", "teams_", "chat_message_")
    ) or tool == "read_resource"
    if not is_c1 and not is_m365:
        return None
    tool_input = call.get("tool_input")
    if not isinstance(tool_input, dict):
        return "deny", "write_guard could not parse the tool call"
    if is_c1:
        if tool == "execute":
            return _execute(tool_input)
        if tool in _READ_C1:
            return "allow", f"C1 {tool}: read-only helper"
        return "ask", f"C1 {tool}: requires approval"
    action_name = tool.removeprefix("sharepoint_")
    if any(action in action_name for action in _DENY_M365):
        return "deny", f"M365 {tool}: prohibited send or mutation"
    if any(action in action_name for action in _ASK_M365):
        return "ask", f"M365 {tool}: write requires approval"
    if any(action in tool for action in ("search", "read", "get", "list")):
        return "allow", f"M365 {tool}: read-only tool"
    return "ask", f"M365 {tool}: unknown tool requires approval"


def main() -> None:
    """Read one hook payload and emit Claude Code's permission response."""
    try:
        decision = decide(json.load(sys.stdin))
    except (ValueError, TypeError, RecursionError):
        decision = ("deny", "write_guard could not parse the tool call")
    if decision is not None:
        permission, reason = decision
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission,
            "permissionDecisionReason": reason,
        }}))


if __name__ == "__main__":
    main()
