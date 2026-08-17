from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PermissionDecision:
    behavior: str
    reason: str
    gate: str


DENY_TOOLS = {"delete_memory", "write_file", "edit_file", "bash"}
ASK_TOOLS = {"persist_analysis_result", "push_feishu_report"}


def check_permission(tool_name: str, _args: dict[str, Any]) -> PermissionDecision:
    """Three-gate permission pipeline adapted from learn-claude-code s03.

    The current GwyPilot web runtime cannot pause for interactive approval, so
    ask-class tools are recorded as reviewed and allowed only when they are
    explicitly registered as business-safe. Destructive generic tools are denied.
    """
    if tool_name in DENY_TOOLS:
        return PermissionDecision(
            behavior="deny",
            gate="deny_list",
            reason=f"{tool_name} is not allowed in the web agent runtime.",
        )
    if tool_name in ASK_TOOLS:
        return PermissionDecision(
            behavior="allow",
            gate="rule_match",
            reason=f"{tool_name} requires review; approved by server policy.",
        )
    if tool_name.startswith("search_") or tool_name.startswith("review_"):
        return PermissionDecision(
            behavior="allow",
            gate="allow_list",
            reason="Read-only retrieval/review tool.",
        )
    if tool_name in {
        "todo_tasks",
        "todo_write",
        "load_skill",
        "compact",
        "compact_context",
        "load_memory",
        "remember",
        "web_search",
        "web_fetch",
        "browser_retrieve",
        "verify_web_evidence",
        "list_tables",
        "describe_table",
        "sample_rows",
        "query_sql",
        "generate_study_plan",
        "compose_policy_answer",
        "compose_final_report",
    }:
        return PermissionDecision(
            behavior="allow",
            gate="allow_list",
            reason="Agent harness tool allowed by project policy.",
        )
    return PermissionDecision(
        behavior="deny",
        gate="default_deny",
        reason=f"{tool_name} is not registered in the web agent runtime.",
    )
