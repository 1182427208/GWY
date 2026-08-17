from app.gwy.agent_runtime.permissions import check_permission


def test_compose_policy_answer_is_allowed_in_web_agent_runtime() -> None:
    decision = check_permission("compose_policy_answer", {})

    assert decision.behavior == "allow"
    assert decision.gate == "allow_list"

