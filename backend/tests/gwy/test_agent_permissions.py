from app.gwy.agent_runtime.permissions import check_permission


def test_registered_agent_tools_remain_allowed() -> None:
    assert check_permission("search_policy", {}).behavior == "allow"
    assert check_permission("generate_study_plan", {}).behavior == "allow"


def test_destructive_agent_tools_remain_denied() -> None:
    decision = check_permission("bash", {"command": "echo safe"})

    assert decision.behavior == "deny"
    assert decision.gate == "deny_list"


def test_unknown_agent_tools_are_denied_by_default() -> None:
    decision = check_permission("new_unregistered_tool", {})

    assert decision.behavior == "deny"
    assert decision.gate == "default_deny"
    assert "not registered" in decision.reason
