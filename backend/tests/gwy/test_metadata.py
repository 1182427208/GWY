from app.gwy.document.metadata import infer_policy_metadata


def test_infer_metadata_from_technical_qa_path() -> None:
    metadata = infer_policy_metadata(
        "data\\\u6280\u672f\u95ee\u7b54\\\u4fe1\u606f\u4fee\u6539.pdf"
    )

    assert metadata["year"] == 2026
    assert metadata["exam_type"] == "national"
    assert metadata["province"] == "national"
    assert metadata["doc_group"] == "technical_qa"
    assert metadata["doc_type"] == "info_modify"
    assert metadata["doc_title"] == "\u4fe1\u606f\u4fee\u6539"
    assert metadata["source_file"].endswith(
        "data\\\u6280\u672f\u95ee\u7b54\\\u4fe1\u606f\u4fee\u6539.pdf"
    )
    assert metadata["source"] == "official"


def test_infer_metadata_from_announcement_path() -> None:
    metadata = infer_policy_metadata("data/2026_\u56fd\u8003\u516c\u544a.pdf")

    assert metadata["doc_group"] == "announcement"
    assert metadata["doc_type"] == "recruitment_announcement"
    assert metadata["doc_title"] == "\u56fd\u8003\u516c\u544a"


def test_infer_metadata_from_major_catalog_path() -> None:
    metadata = infer_policy_metadata("data/\u4e13\u4e1a\u76ee\u5f55/\u6cd5\u5b66.pdf")

    assert metadata["doc_group"] == "major_catalog"
    assert metadata["doc_type"] == "major_catalog"
