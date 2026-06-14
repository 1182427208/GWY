from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.gwy.document.asset_linker import link_assets_to_chunks
from app.gwy.document.chunker import chunk_policy_document
from app.gwy.document.image_extractor import (
    extract_pdf_image_assets,
    image_assets_to_chunks,
)
from app.gwy.document.layout_analyzer import analyze_pdf_layout
from app.gwy.document.metadata import infer_policy_metadata
from app.gwy.document.pdf_loader import load_pdf_pages, strip_document_chrome
from app.gwy.document.table_extractor import extract_pdf_tables
from app.gwy.document_processing.extractors import make_content_hash, normalize_text
from app.gwy.document_processing.guards import chunk_noise_guard
from app.gwy.document_processing.chunkers import chunk_semantic_text
from app.gwy.services.chunk_debug_service import ChunkDebugService
from app.gwy.llm.embedding_service import EmbeddingService
from app.gwy.models import GwyPdfAsset, GwyPdfTable, GwyPdfTableRow, GwyPolicyDocument
from app.gwy.vectorstores.milvus_store import (
    MilvusPolicyStore,
    build_policy_collection_name,
)


class PolicyIngestionService:
    def __init__(
        self,
        *,
        session: Session | None = None,
        embedding_service: EmbeddingService | None = None,
        chunk_debug_service: ChunkDebugService | None = None,
        milvus_store: MilvusPolicyStore | None = None,
        owner_user_id: UUID | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.session = session
        self.embedding_service = embedding_service or EmbeddingService()
        self.chunk_debug_service = chunk_debug_service or ChunkDebugService()
        self.collection_name = (
            collection_name
            or getattr(milvus_store, "collection_name", None)
            or build_policy_collection_name(owner_user_id)
        )
        self.milvus_store = milvus_store or MilvusPolicyStore(
            collection_name=self.collection_name,
        )

    def ingest_policy_pdf(
        self,
        file_path: str,
        *,
        owner_user_id: UUID | None = None,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        target_collection = self._resolve_collection_name(
            owner_user_id=owner_user_id,
            collection_name=collection_name,
        )
        metadata = infer_policy_metadata(file_path)
        try:
            layout_result = analyze_pdf_layout(file_path)
            try:
                pages = load_pdf_pages(file_path)
            except Exception:
                pages = self._build_pages_from_layout(layout_result)
            chunks = chunk_policy_document(
                pages=pages,
                doc_group=str(metadata["doc_group"]),
                doc_type=str(metadata["doc_type"]),
                base_metadata=metadata,
            )
            image_assets = extract_pdf_image_assets(
                file_path,
                layout_pages=list(layout_result.get("pages") or []),
            )
            image_chunks = image_assets_to_chunks(image_assets)
            table_result = extract_pdf_tables(
                file_path,
                layout_pages=list(layout_result.get("pages") or []),
            )
            table_assets = list(table_result.get("tables") or [])
            table_rows = list(table_result.get("rows") or [])
            table_chunks = list(table_result.get("chunks") or [])

            for chunk in [*image_chunks, *table_chunks]:
                merged_metadata = dict(metadata)
                merged_metadata.update(dict(chunk.get("metadata") or {}))
                chunk["metadata"] = merged_metadata
                chunk.setdefault("doc_group", merged_metadata.get("doc_group"))
                chunk.setdefault("doc_type", merged_metadata.get("doc_type"))
                chunk.setdefault("year", merged_metadata.get("year"))
                chunk.setdefault("exam_type", merged_metadata.get("exam_type"))
                chunk.setdefault("province", merged_metadata.get("province"))
                chunk.setdefault("doc_title", merged_metadata.get("doc_title"))

            chunks = self._deduplicate_chunks(chunks)
            image_chunks = self._deduplicate_chunks(image_chunks)
            table_chunks = self._deduplicate_chunks(table_chunks)

            linked_result = link_assets_to_chunks(
                [*chunks, *image_chunks, *table_chunks],
                layout_pages=list(layout_result.get("pages") or []),
                image_assets=image_assets,
                table_assets=table_assets,
            )
            all_chunks = list(linked_result.get("chunks") or [])
            image_assets = list(linked_result.get("image_assets") or [])
            table_assets = list(linked_result.get("table_assets") or [])
            layout_blocks = list(linked_result.get("layout_blocks") or [])

            if not all_chunks:
                fallback_chunks = self._build_empty_doc_fallback_chunks(
                    pages=pages,
                    metadata=metadata,
                )
                if fallback_chunks:
                    all_chunks = fallback_chunks
                else:
                    raise ValueError(f"No chunks generated from PDF: {file_path}")

            chunk_debug_result = self.chunk_debug_service.export_pdf_chunks(
                source_file=str(metadata["source_file"]),
                chunks=all_chunks,
                metadata=metadata,
            )
            debug_assets_result = self.chunk_debug_service.export_document_debug(
                source_file=str(metadata["source_file"]),
                layout_blocks=layout_blocks,
                image_assets=image_assets,
                tables=table_assets,
                table_rows=table_rows,
                chunks_with_assets=all_chunks,
            )
            vectors = self.embedding_service.embed_texts(
                [str(chunk["content"]) for chunk in all_chunks]
            )
            enriched_chunks = []
            for chunk, vector in zip(all_chunks, vectors, strict=True):
                enriched_chunk = dict(chunk)
                enriched_chunk["vector"] = vector
                enriched_chunks.append(enriched_chunk)

            milvus_store = self._get_milvus_store(target_collection)
            milvus_store.create_collection_if_not_exists()
            milvus_store.insert_chunks(enriched_chunks)
            self._upsert_pdf_assets(
                image_assets=image_assets,
                table_assets=table_assets,
                table_rows=table_rows,
            )
            self._upsert_policy_document(
                source_file=str(metadata["source_file"]),
                doc_title=str(metadata["doc_title"]),
                doc_group=str(metadata["doc_group"]),
                doc_type=str(metadata["doc_type"]),
                year=int(metadata["year"]),
                exam_type=str(metadata["exam_type"]),
                province=str(metadata["province"]),
                chunk_count=len(enriched_chunks),
                embedding_status="completed",
                milvus_collection=target_collection,
            )
            return {
                "success": True,
                "file_count": 1,
                "chunk_count": len(enriched_chunks),
                "failed_files": [],
                "source_file": str(metadata["source_file"]),
                "milvus_collection": target_collection,
                "chunk_stats": chunk_debug_result["chunk_stats"],
                "warnings": list(chunk_debug_result["warnings"]),
                "debug_artifacts": {
                    **dict(chunk_debug_result["artifact_paths"]),
                    **dict(debug_assets_result["artifact_paths"]),
                },
                "layout_stats": debug_assets_result["stats"],
            }
        except Exception:
            self._upsert_policy_document(
                source_file=str(metadata["source_file"]),
                doc_title=str(metadata["doc_title"]),
                doc_group=str(metadata["doc_group"]),
                doc_type=str(metadata["doc_type"]),
                year=int(metadata["year"]),
                exam_type=str(metadata["exam_type"]),
                province=str(metadata["province"]),
                chunk_count=0,
                embedding_status="failed",
                milvus_collection=target_collection,
            )
            raise

    def ingest_policy_directory(
        self,
        directory_path: str,
        *,
        owner_user_id: UUID | None = None,
        collection_name: str | None = None,
    ) -> dict[str, Any]:
        root = Path(directory_path)
        if not root.exists():
            raise FileNotFoundError(directory_path)

        if root.is_file():
            result = self.ingest_policy_pdf(
                str(root),
                owner_user_id=owner_user_id,
                collection_name=collection_name,
            )
            return result

        pdf_files = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".pdf"
        )
        chunk_count = 0
        failed_files: list[str] = []
        stats_list: list[dict[str, Any]] = []
        warnings: list[str] = []
        for pdf_file in pdf_files:
            try:
                result = self.ingest_policy_pdf(
                    str(pdf_file),
                    owner_user_id=owner_user_id,
                    collection_name=collection_name,
                )
                chunk_count += int(result["chunk_count"])
                if result.get("chunk_stats"):
                    stats_list.append(dict(result["chunk_stats"]))
                warnings.extend([str(item) for item in result.get("warnings", [])])
            except Exception:
                failed_files.append(str(pdf_file))
        aggregated_stats = self.chunk_debug_service.combine_chunk_stats(
            stats_list,
            source_file=str(root),
        )
        return {
            "success": not failed_files,
            "file_count": len(pdf_files),
            "chunk_count": chunk_count,
            "failed_files": failed_files,
            "chunk_stats": aggregated_stats,
            "warnings": warnings,
        }

    def _upsert_policy_document(
        self,
        *,
        source_file: str,
        doc_title: str,
        doc_group: str,
        doc_type: str,
        year: int,
        exam_type: str,
        province: str,
        chunk_count: int,
        embedding_status: str,
        milvus_collection: str,
    ) -> None:
        if self.session is None:
            return

        statement = select(GwyPolicyDocument).where(
            GwyPolicyDocument.source_file == source_file
        )
        existing = self.session.exec(statement).first()
        if existing is None:
            document = GwyPolicyDocument(
                source_file=source_file,
                doc_title=doc_title,
                doc_group=doc_group,
                doc_type=doc_type,
                year=year,
                exam_type=exam_type,
                province=province,
                chunk_count=chunk_count,
                milvus_collection=milvus_collection,
                embedding_status=embedding_status,
            )
            self.session.add(document)
        else:
            existing.doc_title = doc_title
            existing.doc_group = doc_group
            existing.doc_type = doc_type
            existing.year = year
            existing.exam_type = exam_type
            existing.province = province
            existing.chunk_count = chunk_count
            existing.milvus_collection = milvus_collection
            existing.embedding_status = embedding_status
            self.session.add(existing)
        self.session.commit()

    def _resolve_collection_name(
        self,
        *,
        owner_user_id: UUID | None,
        collection_name: str | None,
    ) -> str:
        if collection_name:
            return collection_name
        if owner_user_id is not None:
            return MilvusPolicyStore.user_collection_name(owner_user_id)
        return self.collection_name

    def _get_milvus_store(self, collection_name: str) -> MilvusPolicyStore:
        current_collection = getattr(self.milvus_store, "collection_name", None)
        if current_collection == collection_name:
            return self.milvus_store
        if current_collection is None and collection_name == self.collection_name:
            return self.milvus_store
        return MilvusPolicyStore(collection_name=collection_name)

    def _build_pages_from_layout(self, layout_result: dict[str, Any]) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        for page in layout_result.get("pages") or []:
            page_number = int(page.get("page", 0) or 0)
            texts = []
            for block in page.get("blocks") or []:
                block_type = str(block.get("block_type") or "")
                if block_type in {"header", "footer"}:
                    continue
                if block_type not in {"text", "title"}:
                    continue
                text = strip_document_chrome(str(block.get("text", "")).strip())
                if text:
                    texts.append(text)
            page_text = strip_document_chrome("\n".join(texts))
            if page_text:
                pages.append({"page": page_number, "text": page_text})
        return pages

    def _deduplicate_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chunk in chunks:
            metadata = dict(chunk.get("metadata") or {})
            if self._is_low_quality_chunk(chunk, metadata):
                continue
            chunk_type = str(chunk.get("chunk_type") or "")
            source_file = metadata.get("source_file") or chunk.get("source_file")
            content = normalize_text(str(chunk.get("content", "")))
            signature_parts = [
                chunk_type,
                source_file,
                int(chunk.get("page_start", 0) or 0),
                int(chunk.get("page_end", 0) or 0),
                content,
                metadata.get("question"),
                metadata.get("answer"),
            ]
            if chunk_type in {"table", "table_summary", "table_row"}:
                signature_parts.extend(
                    [
                        metadata.get("table_id") or chunk.get("table_id"),
                        metadata.get("row_json"),
                    ]
                )
            else:
                signature_parts.extend(
                    [
                        metadata.get("table_id"),
                        metadata.get("image_id"),
                        metadata.get("row_id"),
                    ]
                )

            signature = make_content_hash(*signature_parts)
            if signature in seen:
                continue
            seen.add(signature)
            unique.append(chunk)
        return unique

    def _is_low_quality_chunk(
        self,
        chunk: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bool:
        chunk_type = str(chunk.get("chunk_type") or "")
        content = normalize_text(str(chunk.get("content", "")))
        if not content:
            return True
        if not chunk_noise_guard({**chunk, "content": content}):
            return True
        if chunk_type == "table_row":
            columns = list(metadata.get("columns") or chunk.get("columns") or [])
            meaningful_columns = [
                str(column).strip()
                for column in columns
                if str(column).strip()
                and str(column).strip().lower() not in {"none", "null", "nan"}
            ]
            if len(meaningful_columns) < 2:
                return True
            if content in {"col_1：", "None：None"}:
                return True
            if len(content) < 18 and not any(ch.isdigit() for ch in content):
                return True
            if sum(1 for column in columns if str(column).strip().lower() in {"none", "null", "nan"}) >= max(1, len(columns) // 2):
                return True
        return False

    def _build_empty_doc_fallback_chunks(
        self,
        *,
        pages: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fallback_chunks: list[dict[str, Any]] = []
        for page in pages:
            page_text = normalize_text(str(page.get("text", "")))
            if not page_text:
                continue
            page_metadata = dict(metadata)
            page_metadata["page_start"] = int(page.get("page", 0) or 0)
            page_metadata["page_end"] = int(page.get("page", 0) or 0)
            page_chunks = chunk_semantic_text(page_text, page_metadata)
            fallback_chunks.extend(page_chunks)
        return self._deduplicate_chunks(fallback_chunks)

    def _upsert_pdf_assets(
        self,
        *,
        image_assets: list[dict[str, Any]],
        table_assets: list[dict[str, Any]],
        table_rows: list[dict[str, Any]],
    ) -> None:
        if self.session is None:
            return

        for asset in image_assets:
            asset_id = asset.get("image_id")
            if not asset_id:
                continue
            existing = self.session.get(GwyPdfAsset, UUID(str(asset_id)))
            if existing is None:
                existing = GwyPdfAsset(
                    id=UUID(str(asset_id)),
                    asset_type=str(asset.get("asset_type", "image")),
                    source_file=str(asset.get("source_file", "")),
                    page=int(asset.get("page", 0) or 0),
                    bbox=list(asset.get("bbox") or []),
                    image_path=str(asset.get("image_path") or ""),
                    nearby_text=str(asset.get("nearby_text") or ""),
                    summary=str(asset.get("summary") or ""),
                    ocr_text=str(asset.get("ocr_text") or ""),
                    extraction_status=str(asset.get("extraction_status") or "pending"),
                    linked_chunk_ids=list(asset.get("linked_chunk_ids") or []),
                )
            else:
                existing.asset_type = str(asset.get("asset_type", "image"))
                existing.source_file = str(asset.get("source_file", ""))
                existing.page = int(asset.get("page", 0) or 0)
                existing.bbox = list(asset.get("bbox") or [])
                existing.image_path = str(asset.get("image_path") or "")
                existing.nearby_text = str(asset.get("nearby_text") or "")
                existing.summary = str(asset.get("summary") or "")
                existing.ocr_text = str(asset.get("ocr_text") or "")
                existing.extraction_status = str(asset.get("extraction_status") or "pending")
                existing.linked_chunk_ids = list(asset.get("linked_chunk_ids") or [])
            self.session.add(existing)

        table_id_map: dict[str, UUID] = {}
        for table in table_assets:
            table_id = table.get("table_id")
            if not table_id:
                continue
            table_uuid = UUID(str(table_id))
            table_id_map[str(table_id)] = table_uuid
            existing_table = self.session.get(GwyPdfTable, table_uuid)
            if existing_table is None:
                existing_table = GwyPdfTable(
                    id=table_uuid,
                    source_file=str(table.get("source_file", "")),
                    page_start=int(table.get("page_start", 0) or 0),
                    page_end=int(table.get("page_end", 0) or 0),
                    bbox=list(table.get("bbox") or []),
                    columns=list(table.get("columns") or []),
                    markdown_content=str(table.get("markdown_content") or ""),
                    table_image_path=str(table.get("table_image_path") or ""),
                    extraction_status=str(table.get("extraction_status") or "pending"),
                    is_cross_page=bool(table.get("is_cross_page", False)),
                    source_pages=[int(value) for value in (table.get("source_pages") or [])],
                    linked_chunk_ids=list(table.get("linked_chunk_ids") or []),
                )
            else:
                existing_table.source_file = str(table.get("source_file", ""))
                existing_table.page_start = int(table.get("page_start", 0) or 0)
                existing_table.page_end = int(table.get("page_end", 0) or 0)
                existing_table.bbox = list(table.get("bbox") or [])
                existing_table.columns = list(table.get("columns") or [])
                existing_table.markdown_content = str(table.get("markdown_content") or "")
                existing_table.table_image_path = str(table.get("table_image_path") or "")
                existing_table.extraction_status = str(table.get("extraction_status") or "pending")
                existing_table.is_cross_page = bool(table.get("is_cross_page", False))
                existing_table.source_pages = [int(value) for value in (table.get("source_pages") or [])]
                existing_table.linked_chunk_ids = list(table.get("linked_chunk_ids") or [])
            self.session.add(existing_table)

        for row in table_rows:
            row_id = row.get("id")
            table_id = row.get("table_id")
            if not row_id or not table_id:
                continue
            row_uuid = UUID(str(row_id))
            table_uuid = table_id_map.get(str(table_id), UUID(str(table_id)))
            existing_row = self.session.get(GwyPdfTableRow, row_uuid)
            if existing_row is None:
                existing_row = GwyPdfTableRow(
                    id=row_uuid,
                    table_id=table_uuid,
                    row_index=int(row.get("row_index", 0) or 0),
                    row_text=str(row.get("row_text") or ""),
                    row_json=dict(row.get("row_json") or {}),
                    page=int(row.get("page", 0) or 0),
                )
            else:
                existing_row.table_id = table_uuid
                existing_row.row_index = int(row.get("row_index", 0) or 0)
                existing_row.row_text = str(row.get("row_text") or "")
                existing_row.row_json = dict(row.get("row_json") or {})
                existing_row.page = int(row.get("page", 0) or 0)
            self.session.add(existing_row)

        self.session.commit()
