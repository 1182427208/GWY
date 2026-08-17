from __future__ import annotations

from app.gwy.evals.adapters import normalize_agent_output
from app.gwy.evals.schemas import AgentObservation, EvalCase, ExpectedOutcome, ToolCall
from app.gwy.evals.scorers.claim_groundedness import score_claim_groundedness
from app.gwy.evals.scorers.evidence_quality import score_evidence_quality
from app.gwy.evals.scorers.position_identity import score_position_identity
from app.gwy.evals.scorers.job_constraint import score_job_constraints
from app.gwy.evals.scorers.memory import score_memory
from app.gwy.evals.scorers.rag import score_rag
from app.gwy.evals.scorers.tool_call import score_tool_calls


def test_tool_call_scorer_normalizes_required_tools_and_arguments() -> None:
    case = EvalCase(
        case_id="tool_001",
        task_type="tool_call",
        query="推荐四川计算机硕士岗位",
        expected=ExpectedOutcome(
            required_tools=["search_positions_pg"],
            forbidden_tools=["search_policy_knowledge"],
            tool_arguments={
                "search_positions_pg": {
                    "top_k": 5,
                    "filters": {"degree": "硕士研究生", "regions": ["四川", "成都"]},
                }
            },
        ),
    )
    observation = AgentObservation(
        final_answer="done",
        tool_calls=[
            ToolCall(
                tool="todo_write",
                arguments={"todos": []},
                success=True,
            ),
            ToolCall(
                tool="search_positions_pg",
                arguments={
                    "top_k": "5",
                    "filters": {"degree": "硕士", "regions": ["成都", "四川"]},
                },
                success=True,
            ),
        ],
    )

    score = score_tool_calls(case, observation)

    assert score.required_tool_recall == 1.0
    assert score.forbidden_tool_violation_rate == 0.0
    assert score.argument_accuracy == 1.0
    assert score.passed is True


def test_job_constraint_scorer_reports_forbidden_and_hard_filter_violations() -> None:
    case = EvalCase(
        case_id="job_001",
        task_type="job_filter",
        query="我是计算机硕士，群众，想去四川",
        profile={
            "major": "计算机科学与技术",
            "education": "硕士研究生",
            "degree": "硕士",
            "political_status": "群众",
            "target_regions": ["四川"],
        },
        expected=ExpectedOutcome(
            job_ids=["pass-1"],
            forbidden_job_ids=["forbidden-1"],
        ),
    )
    observation = AgentObservation(
        final_answer="done",
        returned_job_ids=["pass-1", "forbidden-1", "party-only"],
        returned_jobs=[
            {
                "id": "pass-1",
                "major_requirement": "计算机类",
                "education_requirement": "硕士研究生及以上",
                "degree_requirement": "硕士",
                "political_status_requirement": "不限",
                "work_location": "四川",
            },
            {
                "id": "party-only",
                "major_requirement": "计算机类",
                "education_requirement": "硕士研究生及以上",
                "degree_requirement": "硕士",
                "political_status_requirement": "中共党员",
                "work_location": "四川",
            },
        ],
    )

    score = score_job_constraints(case, observation)

    assert score.job_precision == 1 / 3
    assert score.constraint_violation_rate == 2 / 3
    assert {item["job_id"] for item in score.violations} == {
        "forbidden-1",
        "party-only",
    }
    assert score.passed is False


def test_rag_scorer_uses_doc_or_chunk_ids_and_answer_points() -> None:
    case = EvalCase(
        case_id="rag_001",
        task_type="policy_qa",
        query="报名确认时间是什么？",
        expected=ExpectedOutcome(
            gold_doc_ids=["guide-2026"],
            gold_chunk_ids=["chunk-2"],
            gold_answer_points=["报名确认", "准考证"],
        ),
    )
    observation = AgentObservation(
        final_answer="需要完成报名确认，并按时打印准考证。",
        retrieved_documents=[
            {"doc_id": "other", "chunk_id": "chunk-1"},
            {"doc_id": "guide-2026", "chunk_id": "chunk-2"},
        ],
        citations=[{"doc_id": "guide-2026", "chunk_id": "chunk-2"}],
    )

    score = score_rag(case, observation, top_k=5)

    assert score.recall_at_k == 1.0
    assert score.answer_point_coverage == 1.0
    assert score.citation_support_rate == 1.0
    assert score.passed is True


def test_memory_scorer_counts_expected_fields_and_leakage() -> None:
    case = EvalCase(
        case_id="mem_001",
        task_type="memory",
        query="记住我的专业",
        expected=ExpectedOutcome(
            memory_after={"major": "法学", "target_regions": ["浙江"]},
        ),
    )
    observation = AgentObservation(
        final_answer="done",
        memory_after={"major": "法学", "target_regions": ["浙江", "杭州"]},
        memory_leakage_count=1,
    )

    score = score_memory(case, observation)

    assert score.memory_field_accuracy == 1.0
    assert score.leakage_count == 1
    assert score.passed is False


def test_job_constraint_scorer_checks_education_degree_and_experience() -> None:
    case = EvalCase(
        case_id="job_002",
        task_type="job_filter",
        query="匹配岗位",
        profile={
            "education": "本科",
            "degree": "学士",
            "political_status": "群众",
            "grassroots_years": 0,
            "grassroots_project_experience": False,
        },
    )
    observation = AgentObservation(
        returned_job_ids=["job-1"],
        returned_jobs=[
            {
                "id": "job-1",
                "education_requirement": "硕士研究生",
                "degree_requirement": "硕士",
                "grassroots_years_requirement": "2年",
                "grassroots_project_experience": "三支一扶",
            }
        ],
    )

    score = score_job_constraints(case, observation)

    assert {item["field"] for item in score.violations} == {
        "education_requirement",
        "degree_requirement",
        "grassroots_years_requirement",
        "grassroots_project_experience",
    }
    assert score.passed is False


def test_rag_scorer_uses_fraction_of_all_gold_evidence() -> None:
    case = EvalCase(
        case_id="rag_002",
        task_type="policy_qa",
        query="政策问题",
        expected=ExpectedOutcome(
            gold_doc_ids=["doc-1", "doc-2"],
            gold_answer_points=["报名", "确认"],
        ),
    )
    observation = AgentObservation(
        final_answer="报名后需要确认",
        retrieved_documents=[{"doc_id": "doc-1"}],
        citations=[{"doc_id": "doc-1"}],
    )

    score = score_rag(case, observation, top_k=5)

    assert score.recall_at_k == 0.5
    assert score.citation_support_rate == 1.0
    assert score.passed is False


def test_position_identity_scorer_matches_expected_position_fields() -> None:
    case = EvalCase(
        case_id="position_001",
        task_type="job_filter",
        query="查询岗位身份",
        expected=ExpectedOutcome(
            expected_position={
                "department": "国家税务总局",
                "position_name": "法务管理一级主任科员及以下",
                "position_code": "A001",
                "year": 2026,
            }
        ),
    )
    observation = AgentObservation(
        final_answer="done",
        raw_output={
            "resolved_position": {
                "department": "国家税务总局",
                "position_name": "法务管理一级主任科员及以下",
                "position_code": "A001",
                "year": 2026,
            }
        },
    )

    score = score_position_identity(case, observation)

    assert score.passed is True
    assert score.metrics["position_identity_accuracy"] == 1.0
    assert score.metrics["position_code_match"] == 1.0


def test_evidence_quality_scorer_uses_authority_and_position_match() -> None:
    case = EvalCase(
        case_id="evidence_001",
        task_type="policy_qa",
        query="政策证据",
        expected=ExpectedOutcome(
            expected_position={"position_code": "A001", "year": 2026},
        ),
    )
    observation = AgentObservation(
        final_answer="done",
        citations=[
            {
                "source_type": "official",
                "source_url": "https://example.gov.cn",
                "year": 2026,
                "position_code": "A001",
            },
            {
                "source_type": "forum",
                "source_url": "https://example.com",
                "year": 2025,
                "position_code": "A001",
            },
        ],
        retrieved_documents=[
            {"doc_id": "doc-1", "position_code": "A001"},
            {"doc_id": "doc-2", "position_code": "A001"},
        ],
    )

    score = score_evidence_quality(case, observation)

    assert score.metrics["evidence_coverage"] == 1.0
    assert score.metrics["source_authority_score"] == 0.5
    assert score.metrics["evidence_position_match_rate"] == 1.0
    assert score.passed is True


def test_claim_groundedness_flags_unsupported_claims() -> None:
    case = EvalCase(
        case_id="claim_001",
        task_type="policy_qa",
        query="政策结论",
    )
    observation = AgentObservation(
        final_answer="该岗位招录 2 人，竞争较强。",
        citations=[{"doc_id": "doc-1"}],
        raw_output={
            "claims": [
                {"text": "该岗位招录 2 人", "supported": True},
                {"text": "竞争较强", "supported": False},
            ]
        },
    )

    score = score_claim_groundedness(case, observation)

    assert score.metrics["unsupported_claim_rate"] == 0.5
    assert score.passed is False


def test_adapter_normalizes_runtime_result_and_trace_events() -> None:
    class RuntimeResult:
        answer = "报告"
        trace = [
            {
                "event": "ToolUse",
                "tool": "search_positions_pg",
                "input": {"top_k": "5"},
            },
            {
                "event": "PostToolUse",
                "tool": "search_positions_pg",
                "status": "done",
                "elapsed_ms": 12,
            },
        ]
        state = {
            "recommendations": [{"position_id": "job-1"}],
            "task_contract": {"todos": [{"content": "先规划", "status": "pending"}]},
            "validation": {"passed": True, "missing_requirements": []},
        }

    observation = normalize_agent_output(RuntimeResult())

    assert observation.final_answer == "报告"
    assert observation.returned_job_ids == ["job-1"]
    assert observation.tool_calls[0].tool == "search_positions_pg"
    assert observation.tool_calls[0].arguments == {"top_k": "5"}
    assert observation.tool_calls[0].latency_ms == 12
    assert observation.task_contract["todos"][0]["content"] == "先规划"
    assert observation.validation["passed"] is True
