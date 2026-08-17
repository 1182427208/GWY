# GwyPilot Agent Evaluation

This package is a lightweight, isolated evaluation harness for the existing GwyPilot agent implementation.

It does not define a new evaluation agent and does not replace production flows. It normalizes existing agent outputs into `AgentObservation`, runs deterministic scorers, and writes reproducible result files.

Outputs:

- `results.jsonl`
- `summary.json`
- `summary.csv`
- `failures.jsonl`
- `report.md`
- `config.snapshot.yaml`

The included `datasets/dev.jsonl` contains templates only. Before treating a case as ground truth, bind `job_ids`, `forbidden_job_ids`, `gold_doc_ids`, and `gold_chunk_ids` to real PostgreSQL/Milvus data.

## Offline run

The first runner is intentionally offline. Save one JSON object per line in an
observation file:

```json
{"case_id":"policy_001","observation":{"answer":"...","citations":[],"rerank_results":[],"retrieval_trace":[]}}
```

Run it from `backend`:

```bash
uv run python -m app.gwy.evals.run_eval \
  --dataset app/gwy/evals/datasets/dev.jsonl \
  --offline-observations path/to/observations.jsonl \
  --output-dir app/gwy/evals/results/smoke
```

The evaluator catches a runner error as a failed case and continues the batch.
It never estimates missing token or cost data, and it never sends Feishu or
other external requests by itself. The production service can be connected by
passing a callable runner to `run_evaluation` from a separate integration
script; no production route imports this package.
