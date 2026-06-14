from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class ChunkDebugArtifactPaths:
    jsonl_path: Path
    csv_path: Path
    preview_html_path: Path | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "jsonl_path": str(self.jsonl_path),
            "csv_path": str(self.csv_path),
            "preview_html_path": (
                str(self.preview_html_path) if self.preview_html_path else None
            ),
        }


class ChunkDebugService:
    def __init__(
        self,
        *,
        debug_root: Path | None = None,
        preview_root: Path | None = None,
    ) -> None:
        temp_root = Path(tempfile.gettempdir()) / "gwy_pilot_artifacts"
        self.debug_root = debug_root or (temp_root / "chunks_debug")
        self.preview_root = preview_root or (temp_root / "chunks_preview")
        if debug_root is not None:
            self.document_debug_root = debug_root.parent / "debug"
        else:
            self.document_debug_root = temp_root / "debug"

    def export_pdf_chunks(
        self,
        *,
        source_file: str,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
        create_preview: bool = True,
    ) -> dict[str, Any]:
        records = self._build_records(
            source_file=source_file,
            chunks=chunks,
            metadata=metadata,
        )
        stats = self._compute_stats(records, metadata)
        warnings = self._build_warnings(records, metadata, stats)
        paths = self._write_artifacts(
            source_file=source_file,
            records=records,
            stats=stats,
            create_preview=create_preview,
        )
        return {
            "source_file": source_file,
            "artifact_paths": paths.as_dict(),
            "chunk_stats": stats,
            "warnings": warnings,
            "records": records,
        }

    def export_document_debug(
        self,
        *,
        source_file: str,
        layout_blocks: list[dict[str, Any]] | None = None,
        image_assets: list[dict[str, Any]] | None = None,
        tables: list[dict[str, Any]] | None = None,
        table_rows: list[dict[str, Any]] | None = None,
        chunks_with_assets: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.document_debug_root.mkdir(parents=True, exist_ok=True)
        layout_blocks = layout_blocks or []
        image_assets = image_assets or []
        tables = tables or []
        table_rows = table_rows or []
        chunks_with_assets = chunks_with_assets or []

        layout_path = self.document_debug_root / "layout_blocks.jsonl"
        image_path = self.document_debug_root / "image_assets.jsonl"
        tables_path = self.document_debug_root / "tables_debug.jsonl"
        table_rows_path = self.document_debug_root / "table_rows_debug.csv"
        chunks_path = self.document_debug_root / "chunks_with_assets.jsonl"

        self._write_jsonl(layout_path, layout_blocks)
        self._write_jsonl(image_path, image_assets)
        self._write_jsonl(tables_path, tables)
        self._write_jsonl(chunks_path, chunks_with_assets)
        self._write_table_rows_csv(table_rows_path, table_rows)

        stats = {
            "source_file": source_file,
            "page_count": self._count_pages(layout_blocks),
            "text_block_count": sum(
                1 for block in layout_blocks if str(block.get("block_type")) in {"text", "title"}
            ),
            "image_count": len(image_assets),
            "table_count": len(tables),
            "cross_page_table_count": sum(
                1 for table in tables if bool(table.get("is_cross_page"))
            ),
            "table_extraction_failed_count": sum(
                1
                for table in tables
                if str(table.get("extraction_status")) == "failed"
            ),
            "image_summary_pending_count": sum(
                1
                for asset in image_assets
                if str(asset.get("extraction_status")) == "pending_multimodal_summary"
            ),
            "chunks_count": len(chunks_with_assets),
        }
        return {
            "source_file": source_file,
            "artifact_paths": {
                "layout_blocks_path": str(layout_path),
                "image_assets_path": str(image_path),
                "tables_debug_path": str(tables_path),
                "table_rows_debug_path": str(table_rows_path),
                "chunks_with_assets_path": str(chunks_path),
            },
            "stats": stats,
        }

    def list_chunks(
        self,
        *,
        source_file: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = list(self._iter_chunk_records(source_file=source_file))
        if offset:
            records = records[offset:]
        if limit is not None:
            records = records[:limit]
        return records

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        for record in self._iter_chunk_records():
            if str(record.get("chunk_id")) == chunk_id:
                return record
        return None

    def get_chunk_stats(
        self,
        *,
        source_file: str | None = None,
    ) -> dict[str, Any]:
        records = list(self._iter_chunk_records(source_file=source_file))
        metadata = self._load_first_metadata(source_file=source_file)
        return self._compute_stats(records, metadata)

    def combine_chunk_stats(
        self,
        stats_list: list[dict[str, Any]],
        *,
        source_file: str | None = None,
        doc_group: str | None = None,
        doc_type: str | None = None,
    ) -> dict[str, Any]:
        if not stats_list:
            return {
                "source_file": source_file,
                "doc_group": doc_group,
                "doc_type": doc_type,
                "total_chunks": 0,
                "chunk_type_count": {},
                "avg_char_count": 0.0,
                "min_char_count": 0,
                "max_char_count": 0,
                "missing_question_count": 0,
                "missing_section_count": 0,
                "missing_page_count": 0,
                "fallback_count": 0,
                "fallback_ratio": 0.0,
            }

        total_chunks = sum(int(item.get("total_chunks", 0)) for item in stats_list)
        weighted_sum = sum(
            float(item.get("avg_char_count", 0.0)) * int(item.get("total_chunks", 0))
            for item in stats_list
        )
        chunk_type_counter: Counter[str] = Counter()
        for item in stats_list:
            chunk_type_counter.update(
                {str(key): int(value) for key, value in item.get("chunk_type_count", {}).items()}
            )

        non_empty_stats = [
            item for item in stats_list if int(item.get("total_chunks", 0)) > 0
        ]
        min_char_count = min(
            int(item.get("min_char_count", 0)) for item in non_empty_stats
        ) if non_empty_stats else 0
        max_char_count = max(
            int(item.get("max_char_count", 0)) for item in non_empty_stats
        ) if non_empty_stats else 0
        total_fallback = sum(int(item.get("fallback_count", 0)) for item in stats_list)
        return {
            "source_file": source_file,
            "doc_group": doc_group,
            "doc_type": doc_type,
            "total_chunks": total_chunks,
            "chunk_type_count": dict(chunk_type_counter),
            "avg_char_count": round(weighted_sum / total_chunks, 2)
            if total_chunks
            else 0.0,
            "min_char_count": min_char_count if total_chunks else 0,
            "max_char_count": max_char_count if total_chunks else 0,
            "missing_question_count": sum(
                int(item.get("missing_question_count", 0)) for item in stats_list
            ),
            "missing_section_count": sum(
                int(item.get("missing_section_count", 0)) for item in stats_list
            ),
            "missing_page_count": sum(
                int(item.get("missing_page_count", 0)) for item in stats_list
            ),
            "fallback_count": total_fallback,
            "fallback_ratio": round(total_fallback / total_chunks, 4)
            if total_chunks
            else 0.0,
        }

    def _build_records(
        self,
        *,
        source_file: str,
        chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk_metadata = dict(metadata)
            chunk_metadata.update(dict(chunk.get("metadata") or {}))
            chunk_metadata.setdefault("source_file", source_file)
            chunk_metadata.setdefault("chunk_type", str(chunk.get("chunk_type", "")))
            content = str(chunk.get("content", ""))
            record = {
                "chunk_id": str(chunk.get("chunk_id", "")),
                "source_file": str(chunk_metadata.get("source_file", source_file)),
                "doc_group": str(chunk_metadata.get("doc_group", "")),
                "doc_type": str(chunk_metadata.get("doc_type", "")),
                "chunk_type": str(chunk.get("chunk_type", "")),
                "section": str(chunk.get("section", "")),
                "question": str(chunk.get("question", "")),
                "page_start": int(chunk.get("page_start", 0) or 0),
                "page_end": int(chunk.get("page_end", 0) or 0),
                "char_count": len(content),
                "content": content,
                "metadata": chunk_metadata,
            }
            records.append(record)
        return records

    def _compute_stats(
        self,
        records: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        total_chunks = len(records)
        char_counts = [int(record.get("char_count", 0)) for record in records]
        chunk_type_count = Counter(
            str(record.get("chunk_type") or "fallback_segment") for record in records
        )
        missing_question_count = sum(
            1 for record in records if not str(record.get("question", "")).strip()
        )
        missing_section_count = sum(
            1 for record in records if not str(record.get("section", "")).strip()
        )
        missing_page_count = sum(
            1
            for record in records
            if int(record.get("page_start", 0) or 0) <= 0
            or int(record.get("page_end", 0) or 0) <= 0
            or int(record.get("page_end", 0) or 0)
            < int(record.get("page_start", 0) or 0)
        )
        fallback_count = sum(
            1
            for record in records
            if self._is_fallback_chunk_type(str(record.get("chunk_type", "")))
        )

        avg_char_count = (
            round(sum(char_counts) / total_chunks, 2) if total_chunks else 0.0
        )
        return {
            "source_file": metadata.get("source_file") if metadata else None,
            "doc_group": metadata.get("doc_group") if metadata else None,
            "doc_type": metadata.get("doc_type") if metadata else None,
            "total_chunks": total_chunks,
            "chunk_type_count": dict(chunk_type_count),
            "avg_char_count": avg_char_count,
            "min_char_count": min(char_counts) if char_counts else 0,
            "max_char_count": max(char_counts) if char_counts else 0,
            "missing_question_count": missing_question_count,
            "missing_section_count": missing_section_count,
            "missing_page_count": missing_page_count,
            "fallback_count": fallback_count,
            "fallback_ratio": round(
                fallback_count / total_chunks, 4
            )
            if total_chunks
            else 0.0,
        }

    def _build_warnings(
        self,
        records: list[dict[str, Any]],
        metadata: dict[str, Any],
        stats: dict[str, Any],
    ) -> list[str]:
        warnings: list[str] = []
        total_chunks = int(stats.get("total_chunks", 0))
        fallback_ratio = float(stats.get("fallback_ratio", 0.0))
        missing_section_count = int(stats.get("missing_section_count", 0))
        doc_group = str(metadata.get("doc_group") or "")

        if doc_group in {"technical_qa", "exam_affairs_qa", "policy_qa"} and fallback_ratio > 0.3:
            warnings.append(
                f"Fallback ratio is high for QA document: {fallback_ratio:.2%}."
            )
        if doc_group == "announcement" and total_chunks:
            threshold = max(1, int(total_chunks * 0.2))
            if missing_section_count > threshold:
                warnings.append(
                    "Announcement document has a high missing_section_count."
                )

        for record in records:
            char_count = int(record.get("char_count", 0))
            if char_count > 2500:
                warnings.append(
                    f"Chunk {record.get('chunk_id')} is too long ({char_count} chars)."
                )
            if char_count and char_count < 30:
                warnings.append(
                    f"Chunk {record.get('chunk_id')} is too short ({char_count} chars)."
                )
        return self._deduplicate(warnings)

    def _write_artifacts(
        self,
        *,
        source_file: str,
        records: list[dict[str, Any]],
        stats: dict[str, Any],
        create_preview: bool,
    ) -> ChunkDebugArtifactPaths:
        artifact_stem = self._artifact_stem(source_file)
        self.debug_root.mkdir(parents=True, exist_ok=True)
        self.preview_root.mkdir(parents=True, exist_ok=True)

        jsonl_path = self.debug_root / f"{artifact_stem}.chunks.jsonl"
        csv_path = self.debug_root / f"{artifact_stem}.chunks.csv"
        preview_html_path: Path | None = None

        with jsonl_path.open("w", encoding="utf-8") as jsonl_file:
            for record in records:
                jsonl_file.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True)
                )
                jsonl_file.write("\n")

        with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=[
                    "chunk_id",
                    "source_file",
                    "doc_group",
                    "doc_type",
                    "chunk_type",
                    "section",
                    "question",
                    "page_start",
                    "page_end",
                    "char_count",
                    "content_preview",
                ],
            )
            writer.writeheader()
            for record in records:
                writer.writerow(
                    {
                        "chunk_id": record["chunk_id"],
                        "source_file": record["source_file"],
                        "doc_group": record["doc_group"],
                        "doc_type": record["doc_type"],
                        "chunk_type": record["chunk_type"],
                        "section": record["section"],
                        "question": record["question"],
                        "page_start": record["page_start"],
                        "page_end": record["page_end"],
                        "char_count": record["char_count"],
                        "content_preview": self._content_preview(
                            str(record.get("content", ""))
                        ),
                    }
                )

        if create_preview:
            preview_html_path = (
                self.preview_root / f"{artifact_stem}.preview.html"
            )
            preview_html_path.write_text(
                self._render_preview_html(
                    source_file=source_file,
                    records=records,
                    stats=stats,
                ),
                encoding="utf-8",
            )

        return ChunkDebugArtifactPaths(
            jsonl_path=jsonl_path,
            csv_path=csv_path,
            preview_html_path=preview_html_path,
        )

    def _iter_chunk_records(
        self,
        *,
        source_file: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        for jsonl_path in sorted(self.debug_root.glob("*.chunks.jsonl")):
            for record in self._read_jsonl(jsonl_path):
                if source_file and str(record.get("source_file")) != source_file:
                    continue
                yield record

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def _load_first_metadata(
        self,
        *,
        source_file: str | None = None,
    ) -> dict[str, Any]:
        for record in self._iter_chunk_records(source_file=source_file):
            return dict(record.get("metadata") or {})
        return {}

    def _artifact_stem(self, source_file: str) -> str:
        cleaned = str(source_file).strip().replace("\\", "__").replace("/", "__")
        cleaned = re.sub(r"^[A-Za-z]:", "", cleaned)
        ascii_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", cleaned).strip("._")
        if ascii_stem:
            return ascii_stem[:96]
        digest = hashlib.sha1(str(source_file).encode("utf-8")).hexdigest()[:8]
        return f"unknown_source_{digest}"

    def _content_preview(self, content: str, limit: int = 240) -> str:
        normalized = content.replace("\r", " ").replace("\n", " ").strip()
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    def _render_preview_html(
        self,
        *,
        source_file: str,
        records: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> str:
        summary_rows = "".join(
            f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(str(value))}</li>"
            for key, value in stats.items()
            if key != "chunk_type_count"
        )
        type_rows = "".join(
            f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(str(value))}</li>"
            for key, value in (stats.get("chunk_type_count") or {}).items()
        )
        cards = []
        for record in records:
            metadata_json = html.escape(
                json.dumps(record.get("metadata") or {}, ensure_ascii=False, indent=2)
            )
            content = html.escape(str(record.get("content", ""))).replace("\n", "<br>")
            cards.append(
                f"""
                <article class="card">
                  <header>
                    <div class="meta-line">
                      <span>{html.escape(str(record.get('chunk_id', '')))}</span>
                      <span>{html.escape(str(record.get('chunk_type', '')))}</span>
                      <span>pages {html.escape(str(record.get('page_start', '')))}-{html.escape(str(record.get('page_end', '')))}</span>
                    </div>
                    <h3>{html.escape(str(record.get('section') or 'No section'))}</h3>
                    <p class="question">{html.escape(str(record.get('question') or 'No question'))}</p>
                  </header>
                  <pre class="metadata">{metadata_json}</pre>
                  <div class="content">{content}</div>
                </article>
                """
            )
        body = "\n".join(cards) if cards else "<p>No chunks available.</p>"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chunk Preview - {html.escape(source_file)}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: Arial, Helvetica, sans-serif;
      background: #f6f7fb;
      color: #1f2937;
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
    }}
    .panel {{
      background: #fff;
      border-radius: 16px;
      padding: 20px;
      box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
      margin-bottom: 20px;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 18px;
      margin-bottom: 16px;
      border: 1px solid #e5e7eb;
      box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
    }}
    .meta-line {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      font-size: 12px;
      color: #6b7280;
      margin-bottom: 8px;
    }}
    .question {{
      font-weight: 600;
      margin: 8px 0 12px;
    }}
    .metadata {{
      background: #0f172a;
      color: #e2e8f0;
      padding: 12px;
      border-radius: 12px;
      overflow-x: auto;
      font-size: 12px;
    }}
    .content {{
      margin-top: 12px;
      white-space: normal;
      line-height: 1.7;
      font-size: 14px;
    }}
    h1, h2, h3 {{ margin-top: 0; }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="panel">
      <h1>Chunk Preview</h1>
      <p>{html.escape(source_file)}</p>
    </div>
    <div class="panel">
      <h2>Stats</h2>
      <div class="stats">
        <div><ul>{summary_rows}</ul></div>
        <div><h3>Chunk Types</h3><ul>{type_rows}</ul></div>
      </div>
    </div>
    {body}
  </div>
</body>
</html>
"""

    def _is_fallback_chunk_type(self, chunk_type: str) -> bool:
        return "fallback" in chunk_type

    def _deduplicate(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def _write_jsonl(self, path: Path, records: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def _write_table_rows_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "id",
                    "table_id",
                    "row_index",
                    "page",
                    "row_text",
                    "row_json",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "id": row.get("id"),
                        "table_id": row.get("table_id"),
                        "row_index": row.get("row_index"),
                        "page": row.get("page"),
                        "row_text": row.get("row_text"),
                        "row_json": json.dumps(row.get("row_json") or {}, ensure_ascii=False),
                    }
                )

    def _count_pages(self, blocks: list[dict[str, Any]]) -> int:
        pages = {
            int(block.get("page", 0) or 0)
            for block in blocks
            if int(block.get("page", 0) or 0) > 0
        }
        return len(pages)
