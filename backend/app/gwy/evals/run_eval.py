from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.gwy.evals.adapters import normalize_agent_output
from app.gwy.evals.aggregation import aggregate_run_results
from app.gwy.evals.schemas import (
    AgentObservation,
    CaseResult,
    EvalCase,
    EvalConfig,
    ScoreBundle,
)
from app.gwy.evals.scorers import (
    score_answer_quality,
    score_claim_groundedness,
    score_evidence_quality,
    score_efficiency,
    score_job_constraints,
    score_memory,
    score_position_identity,
    score_rag,
    score_task_success,
    score_tool_calls,
)

AgentRunner = Callable[[EvalCase], AgentObservation | dict[str, Any]]


def load_config(path: str | Path) -> EvalConfig:
    """Load a YAML config without making YAML part of the production runtime."""
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load eval config files") from exc
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Eval config must be a mapping: {path}")
    return EvalConfig.model_validate(data)


def load_offline_observations(path: str | Path) -> dict[str, Any]:
    """Load saved observations keyed by case_id for deterministic offline scoring."""
    observations: dict[str, Any] = {}
    source = Path(path)
    for line_number, line in enumerate(
        source.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid offline observation at {source}:{line_number}"
            ) from exc
        if not isinstance(row, dict) or not row.get("case_id"):
            raise ValueError(
                f"Offline observation needs case_id at {source}:{line_number}"
            )
        observations[str(row["case_id"])] = row.get("observation", row)
    return observations


def run_evaluation(
    *,
    dataset_path: str | Path,
    output_dir: str | Path,
    agent_runner: AgentRunner,
    config: EvalConfig | None = None,
    experiment_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    eval_config = config or EvalConfig()
    if experiment_overrides:
        eval_config = eval_config.model_copy(update=experiment_overrides)

    cases = [
        case
        for case in load_cases(dataset_path)
        if case.split == eval_config.dataset_split
    ]
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[CaseResult] = []
    for case in cases:
        try:
            raw_observation = agent_runner(case)
            observation = normalize_agent_output(raw_observation)
        except Exception as exc:  # Keep one broken case from aborting the experiment.
            observation = AgentObservation(
                status="error",
                raw_output={"error_type": exc.__class__.__name__, "error": str(exc)},
            )
        scores = score_case(case, observation, top_k=eval_config.top_k)
        failures = [reason for score in scores for reason in score.failure_reasons]
        results.append(
            CaseResult(
                case_id=case.case_id,
                task_type=case.task_type,
                passed=not failures,
                scores=scores,
                observation=observation,
                failure_reasons=failures,
                config=eval_config.model_dump(),
            )
        )

    summary = build_summary(results, eval_config)
    write_outputs(output_root, results, summary)
    return summary


def load_cases(dataset_path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    path = Path(dataset_path)
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            cases.append(EvalCase.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(
                f"Invalid eval case at {path}:{line_number}: {exc}"
            ) from exc
    return cases


def score_case(
    case: EvalCase,
    observation: AgentObservation,
    *,
    top_k: int = 5,
) -> list[ScoreBundle]:
    scores = [score_task_success(case, observation)]
    if case.expected.expected_position or observation.resolved_position or observation.returned_jobs:
        scores.append(score_position_identity(case, observation).bundle())
    if (
        case.expected.required_tools
        or case.expected.forbidden_tools
        or case.expected.tool_arguments
    ):
        scores.append(score_tool_calls(case, observation).bundle())
    if (
        case.task_type == "job_filter"
        or case.expected.job_ids
        or case.expected.forbidden_job_ids
    ):
        scores.append(score_job_constraints(case, observation).bundle())
    if case.expected.gold_doc_ids or case.expected.gold_chunk_ids or case.expected.gold_answer_points:
        scores.append(score_rag(case, observation, top_k=top_k).bundle())
    if (
        observation.citations
        or observation.retrieved_documents
        or case.expected.gold_doc_ids
        or case.expected.gold_chunk_ids
        or case.expected.expected_position
    ):
        scores.append(score_evidence_quality(case, observation).bundle())
    if case.task_type == "memory" or case.expected.memory_after:
        scores.append(score_memory(case, observation).bundle())
    scores.append(score_claim_groundedness(case, observation).bundle())
    scores.append(score_answer_quality(case, observation).bundle())
    scores.append(score_efficiency(case, observation))
    return scores


def build_summary(results: list[CaseResult], config: EvalConfig) -> dict[str, Any]:
    return aggregate_run_results(results, config=config.model_dump())


def write_outputs(
    output_dir: Path,
    results: list[CaseResult],
    summary: dict[str, Any],
) -> None:
    _write_jsonl(
        output_dir / "results.jsonl", [result.model_dump() for result in results]
    )
    _write_jsonl(
        output_dir / "failures.jsonl",
        [result.model_dump() for result in results if not result.passed],
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _write_summary_csv(output_dir / "summary.csv", summary)
    (output_dir / "report.md").write_text(_build_report(summary), encoding="utf-8")
    _write_config_snapshot(
        output_dir / "config.snapshot.yaml", summary.get("config") or {}
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows),
        encoding="utf-8",
    )


def _write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for key in (
            "experiment_name",
            "dataset_split",
            "case_count",
            "passed_count",
            "failed_count",
            "task_success_rate",
        ):
            writer.writerow([key, summary.get(key)])
        for key, value in dict(summary.get("metrics") or {}).items():
            writer.writerow([key, value])


def _write_config_snapshot(path: Path, config: dict[str, Any]) -> None:
    try:
        import yaml

        content = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    except ImportError:  # Keep the evaluator usable in a minimal offline environment.
        content = json.dumps(config, ensure_ascii=False, indent=2, default=str)
    path.write_text(content, encoding="utf-8")


def _build_report(summary: dict[str, Any]) -> str:
    metrics = dict(summary.get("metrics") or {})
    return "\n".join(
        [
            "# GwyPilot Agent Evaluation Report",
            "",
            f"- Experiment: {summary.get('experiment_name')}",
            f"- Split: {summary.get('dataset_split')}",
            f"- Cases: {summary.get('case_count')}",
            f"- Passed: {summary.get('passed_count')}",
            f"- Failed: {summary.get('failed_count')}",
            f"- Task success rate: {summary.get('task_success_rate')}",
            "",
            "| Metric | Value |",
            "|---|---:|",
            *[f"| {name} | {value} |" for name, value in metrics.items()],
            "",
        ]
    )


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Run isolated GwyPilot agent evaluation"
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--config")
    parser.add_argument("--offline-observations")
    args = parser.parse_args()
    config = load_config(args.config) if args.config else EvalConfig()
    if config.git_commit == "unavailable":
        config = config.model_copy(update={"git_commit": _git_commit()})
    if not args.offline_observations:
        raise SystemExit(
            "--offline-observations is required for the first isolated runner"
        )
    observations = load_offline_observations(args.offline_observations)
    run_evaluation(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        config=config,
        agent_runner=lambda case: observations.get(
            case.case_id,
            {"status": "error", "error": "missing offline observation"},
        ),
    )


if __name__ == "__main__":
    _main()
