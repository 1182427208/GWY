from __future__ import annotations

from uuid import uuid4

from app.gwy.agent_runtime import ToolContext
from app.gwy.services.position_snapshot_runtime_service import (
    PositionSnapshotRuntimeService,
)


class RuntimeResult:
    answer = "# 岗位分析报告\n\n模型生成内容"
    trace = [{"event": "Stop", "status": "done", "step": "agent_loop"}]
    state = {
        "recommendations": [{"position_id": "p1", "job_title": "综合管理"}],
        "risk_review": {"risk_level": "low"},
        "report": "# 岗位分析报告\n\n模型生成内容",
    }
    messages = []


class FakeRuntime:
    def run(self, *, user_prompt: str, context: dict):
        assert "测试快照" in user_prompt
        assert context["snapshot"]["title"] == "测试快照"
        return RuntimeResult()


def test_snapshot_runtime_returns_position_analysis_shape() -> None:
    service = PositionSnapshotRuntimeService(
        session=None,
        runtime_factory=lambda **kwargs: FakeRuntime(),
    )

    result = service.run(
        snapshot={
            "title": "测试快照",
            "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
            "filters_json": {"year": 2026, "exam_type": "national"},
        },
        user_id=uuid4(),
        user_profile={"major": "法学", "education": "本科"},
    )

    assert result["status"] == "completed"
    assert result["stage"] == "position_snapshot_runtime"
    assert "岗位分析报告" in result["report"]
    assert result["recommendations"][0]["job_title"] == "综合管理"
    assert result["risk_review"]["risk_level"] == "low"
    assert result["output_json"]["runtime_state"]["risk_review"]["risk_level"] == "low"


def test_snapshot_runtime_registers_position_tools() -> None:
    service = PositionSnapshotRuntimeService(session=None)

    names = set(service._build_tool_registry().names())

    assert "todo_tasks" in names
    assert "todo_write" in names
    assert "load_snapshot" in names
    assert "analyze_snapshot_positions" in names
    assert "research_position_history" in names
    assert "retrieve_position_policy_evidence" in names
    assert "verify_position_hidden_requirements" in names
    assert "review_position_risks" in names
    assert "build_position_decision_matrix" in names
    assert "validate_report_requirements" in names
    assert "generate_study_plan" in names
    assert "compose_snapshot_report" in names
    assert "web_search" in names
    assert "web_fetch" in names
    assert "browser_retrieve" in names
    assert "list_tables" in names
    assert "query_sql" in names


class FakeCatalog:
    def analyze_positions(self, *, position_ids, query, profile, top_k):
        return {
            "summary": {"recommendation_count": 1},
            "recommendations": [{"position_id": "p1", "job_title": "综合管理"}],
            "selected_positions": [{"position_id": "p1", "job_title": "综合管理"}],
            "retrieval_trace": [{"step": "pg", "status": "done"}],
        }


class FakeRisk:
    def run(self, *, query, recommendations):
        return {"risk_level": "low", "risk_items": [], "trace": []}


class FakeStudy:
    def generate(self, **kwargs):
        return {"markdown": "# 复习计划", "plan": {"title": "计划"}}


class FakeReport:
    def run(
        self,
        *,
        title,
        recommendations,
        risk_review,
        decision_matrix=None,
        evidence_inventory=None,
        verification_tasks=None,
    ):
        return {
            "report": "# 深度岗位报告\n\n- 综合管理",
            "report_meta": {"used_llm": False},
            "trace": [],
        }


def test_snapshot_tools_use_existing_collaborator_contracts() -> None:
    service = PositionSnapshotRuntimeService(
        session=None,
        position_catalog_service=FakeCatalog(),
        risk_review_agent=FakeRisk(),
        study_plan_service_factory=lambda session: FakeStudy(),
        report_generator_agent=FakeReport(),
    )
    context = ToolContext(
        state={
            "snapshot": {
                "title": "测试快照",
                "selected_position_ids": ["11111111-1111-1111-1111-111111111111"],
                "filters_json": {"year": 2026, "exam_type": "national"},
            },
            "user_profile": {"major": "法学"},
            "user_id": str(uuid4()),
        }
    )

    facts = service._tool_analyze_snapshot_positions({"query": "法学岗位"}, context)
    risk = service._tool_review_position_risks({"query": "法学岗位"}, context)
    plan = service._tool_generate_study_plan({"study_hours_per_day": 4}, context)
    report = service._tool_compose_snapshot_report({"title": "测试报告"}, context)

    assert facts["recommendations"][0]["job_title"] == "综合管理"
    assert risk["risk_level"] == "low"
    assert plan["markdown"] == "# 复习计划"
    assert "深度岗位报告" in report["report"]
