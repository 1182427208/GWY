from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _load_env_file() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


_load_env_file()

backend_root = Path(__file__).resolve().parents[1]
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.core.config import settings
from app.gwy.document_processing.guards import is_placeholder_noise_chunk
from app.gwy.vectorstores.milvus_store import MilvusPolicyStore


NUMERIC_QA_RE = re.compile(
    r"^(?:问|问题|Q)\s*[:：]?\s*\d+\s*(?:答|回答|A)\s*[:：]?\s*\d+\s*$"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete obvious noise chunks from the Milvus policy collection."
    )
    parser.add_argument(
        "--collection",
        default=settings.MILVUS_COLLECTION_POLICY_RAG,
        help="Milvus collection name to clean.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum number of records to inspect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report matching chunks without deleting anything.",
    )
    args = parser.parse_args()

    store = MilvusPolicyStore(collection_name=args.collection)
    records = store.query_documents(filter_expr='id != ""', limit=args.limit)
    if not records:
        print(f"No records found in collection: {args.collection}")
        return 0

    noisy_records = [record for record in records if _is_noise_record(record)]
    reason_counter = Counter(_noise_reason(record) for record in noisy_records)
    source_counter = Counter(
        str(record.get("source_file") or "") for record in noisy_records
    )

    print(f"collection={args.collection}")
    print(f"scanned={len(records)}")
    print(f"matched_noise={len(noisy_records)}")
    print(f"reasons={dict(reason_counter)}")
    print(f"top_sources={source_counter.most_common(10)}")

    if args.dry_run:
        for record in noisy_records[:20]:
            print(
                {
                    "id": record.get("id"),
                    "chunk_type": record.get("metadata", {}).get("chunk_type"),
                    "source_file": record.get("source_file"),
                    "content": _preview(record.get("content", "")),
                }
            )
        return 0

    deleted = store.delete_chunks_by_ids(
        [str(record.get("id") or "") for record in noisy_records if record.get("id")]
    )
    print(f"deleted={deleted}")
    return 0


def _is_noise_record(record: dict[str, Any]) -> bool:
    chunk = _as_chunk(record)
    if is_placeholder_noise_chunk(chunk):
        return True
    return _is_numeric_qa_noise(record)


def _is_numeric_qa_noise(record: dict[str, Any]) -> bool:
    content = _normalize_compact(str(record.get("content") or ""))
    if not content:
        return False
    if NUMERIC_QA_RE.match(content):
        return True

    question = _normalize_compact(str(record.get("question") or ""))
    chunk_type = str(
        record.get("metadata", {}).get("chunk_type") or record.get("asset_type") or ""
    )
    if chunk_type == "policy_qa" and question.isdigit():
        return bool(re.search(r"(?:答|回答|A)\s*[:：]?\s*\d+", content))
    return False


def _noise_reason(record: dict[str, Any]) -> str:
    if _is_numeric_qa_noise(record):
        return "numeric_qa"
    if is_placeholder_noise_chunk(_as_chunk(record)):
        return "placeholder_noise"
    return "unknown"


def _as_chunk(record: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(record.get("metadata") or {})
    chunk_type = str(metadata.get("chunk_type") or record.get("asset_type") or "")
    return {
        "chunk_type": chunk_type,
        "content": record.get("content", ""),
        "question": record.get("question", ""),
        "answer": metadata.get("answer", ""),
        "metadata": metadata,
    }


def _normalize_compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _preview(text: str, limit: int = 140) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


if __name__ == "__main__":
    raise SystemExit(main())
