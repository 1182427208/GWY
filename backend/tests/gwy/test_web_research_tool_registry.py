from __future__ import annotations

from pathlib import Path

from app.gwy.agent_runtime.skills import SkillRegistry
from app.gwy.services.autonomous_chat_agent_service import AutonomousChatAgentService


def test_web_research_runtime_skill_is_discoverable() -> None:
    registry = SkillRegistry(
        base_dir=Path(__file__).parents[2] / "app" / "gwy" / "runtime_skills"
    )

    skill = registry.load("web-research")

    assert skill is not None
    assert "网页检索" in skill.content
    assert "PostgreSQL" in skill.content


def test_autonomous_registry_contains_web_research_tools() -> None:
    service = object.__new__(AutonomousChatAgentService)

    registry = service._build_tool_registry()

    assert registry.get("search_web") is not None
    assert registry.get("fetch_web_page") is not None
    assert registry.get("read_web_page") is not None
    assert registry.get("verify_web_evidence") is not None
