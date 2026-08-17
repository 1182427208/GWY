from __future__ import annotations

import json
from pathlib import Path

from app.gwy.evals.run_eval import (
    load_config,
    load_offline_observations,
    run_evaluation,
)
from app.gwy.evals.schemas import AgentObservation


def test_run_evaluation_writes_results_summary_and_failures(tmp_path: Path) -> None:
    dataset = tmp_path / "dev.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "tool_001",
                        "task_type": "tool_call",
                        "query": "查政策",
                        "expected": {
                            "required_tools": ["search_policy_knowledge"],
                            "forbidden_tools": ["search_positions_pg"],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "case_id": "job_001",
                        "task_type": "job_filter",
                        "query": "推荐岗位",
                        "expected": {"forbidden_job_ids": ["bad-job"]},
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"

    observations = {
        "tool_001": AgentObservation(
            final_answer="done",
            tool_calls=[
                {
                    "tool": "search_policy_knowledge",
                    "arguments": {"query": "查政策"},
                    "success": True,
                }
            ],
        ),
        "job_001": AgentObservation(
            final_answer="done",
            returned_job_ids=["bad-job"],
        ),
    }

    summary = run_evaluation(
        dataset_path=dataset,
        output_dir=output_dir,
        agent_runner=lambda case: observations[case.case_id],
        experiment_overrides={"experiment_name": "unit"},
    )

    assert summary["case_count"] == 2
    assert summary["failed_count"] == 1
    assert (output_dir / "results.jsonl").exists()
    assert (output_dir / "summary.json").exists()
    assert (output_dir / "summary.csv").exists()
    assert (output_dir / "failures.jsonl").exists()
    assert (output_dir / "report.md").exists()


def test_run_evaluation_records_runner_errors_and_config_snapshot(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dev.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "broken",
                "task_type": "e2e",
                "query": "测试",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"

    summary = run_evaluation(
        dataset_path=dataset,
        output_dir=output_dir,
        agent_runner=lambda case: (_ for _ in ()).throw(RuntimeError("runner down")),
    )

    assert summary["failed_count"] == 1
    result = json.loads((output_dir / "results.jsonl").read_text(encoding="utf-8"))
    assert result["observation"]["status"] == "error"
    assert "runner down" in result["failure_reasons"][0]
    assert (output_dir / "config.snapshot.yaml").exists()


def test_load_config_and_offline_observations(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("experiment_name: smoke\ntop_k: 3\n", encoding="utf-8")
    observations_path = tmp_path / "observations.jsonl"
    observations_path.write_text(
        json.dumps(
            {"case_id": "c1", "observation": {"answer": "ok"}}, ensure_ascii=False
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    observations = load_offline_observations(observations_path)

    assert config.experiment_name == "smoke"
    assert config.top_k == 3
    assert observations["c1"]["answer"] == "ok"


def test_run_evaluation_builds_layered_summary(tmp_path: Path) -> None:
    dataset = tmp_path / "dev.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "case_id": "layered_001",
                "task_type": "job_filter",
                "query": "查询岗位",
                "expected": {
                    "job_ids": ["job-1"],
                    "expected_position": {
                        "department": "国家税务总局",
                        "position_code": "A001",
                        "year": 2026,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "results"

    summary = run_evaluation(
        dataset_path=dataset,
        output_dir=output_dir,
        agent_runner=lambda case: AgentObservation(
            final_answer="done",
            returned_job_ids=["job-1"],
            returned_jobs=[
                {
                    "id": "job-1",
                    "department": "国家税务总局",
                    "position_code": "A001",
                    "year": 2026,
                }
            ],
            raw_output={
                "resolved_position": {
                    "department": "国家税务总局",
                    "position_code": "A001",
                    "year": 2026,
                },
                "claims": [{"text": "done", "supported": True}],
            },
            citations=[{"doc_id": "doc-1", "source_type": "official"}],
        ),
    )

    assert summary["overall_status"] == "PASS"
    assert summary["critical_gate"]["passed_rate"] == 1.0
    assert summary["quality_overview"]["task"]["completion_rate"] == 1.0
    assert "position_identity" in summary["score_cards"]
    assert "execution" in summary["quality_overview"]
    assert (output_dir / "summary.json").exists()
