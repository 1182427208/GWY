from collections.abc import Sequence

from app.gwy.services.milvus_retrieval import (
    EXAM_GUIDE_COLLECTION_NAME,
    MAJOR_CATALOG_COLLECTION_NAME,
    POLICY_DOCUMENT_COLLECTION_NAME,
    MilvusRetrievalService,
    MilvusSearchHit,
    get_milvus_retrieval_service,
)


def _service() -> MilvusRetrievalService:
    return get_milvus_retrieval_service()


def search_policy_documents_by_text(
    query_text: str,
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_policy_documents_by_text(
        query_text=query_text,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def search_exam_guides_by_text(
    query_text: str,
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_exam_guides_by_text(
        query_text=query_text,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def search_major_catalogs_by_text(
    query_text: str,
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_major_catalogs_by_text(
        query_text=query_text,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def search_policy_documents_by_vector(
    query_vector: Sequence[float],
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_by_vector(
        collection_name=POLICY_DOCUMENT_COLLECTION_NAME,
        query_vector=query_vector,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def search_exam_guides_by_vector(
    query_vector: Sequence[float],
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_by_vector(
        collection_name=EXAM_GUIDE_COLLECTION_NAME,
        query_vector=query_vector,
        top_k=top_k,
        filter_expr=filter_expr,
    )


def search_major_catalogs_by_vector(
    query_vector: Sequence[float],
    top_k: int = 5,
    filter_expr: str | None = None,
) -> list[MilvusSearchHit]:
    return _service().search_by_vector(
        collection_name=MAJOR_CATALOG_COLLECTION_NAME,
        query_vector=query_vector,
        top_k=top_k,
        filter_expr=filter_expr,
    )
