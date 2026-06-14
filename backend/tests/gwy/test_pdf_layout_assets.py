from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from app.gwy.document.asset_linker import link_assets_to_chunks
from app.gwy.document.cross_page_table_merger import merge_cross_page_tables
from app.gwy.document.image_extractor import extract_pdf_image_assets, image_assets_to_chunks
from app.gwy.document.layout_analyzer import analyze_pdf_layout
from app.gwy.document.table_extractor import extract_pdf_tables


class FakeRect:
    def __init__(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1


class FakePixmap:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path

    def save(self, path: str) -> None:
        Path(path).write_bytes(b"png")


class FakeLayoutPage:
    def __init__(self) -> None:
        self.rect = SimpleNamespace(width=800, height=1000)
        self.parent = self

    def get_text(self, mode: str, sort: bool = False):  # noqa: ARG002
        return [
            (10, 20, 200, 40, "页眉", 0, 0),
            (10, 200, 300, 240, "一、报名条件", 1, 0),
            (10, 260, 500, 320, "正文内容", 2, 0),
            (10, 950, 150, 980, "页脚", 3, 0),
        ]

    def get_images(self, full: bool = False):  # noqa: ARG002
        return []

    def get_image_rects(self, xref: int):  # noqa: ARG002
        return []

    def get_pixmap(self, matrix=None, clip=None, alpha=False):  # noqa: ARG002
        return FakePixmap(Path("unused"))

    def extract_image(self, xref: int):  # noqa: ARG002
        return {"image": b"png", "ext": "png"}


class FakeDoc:
    def __init__(self, pages: list[FakeLayoutPage]) -> None:
        self._pages = pages
        self.name = "fake.pdf"

    def __iter__(self):
        return iter(self._pages)

    def __getitem__(self, index: int) -> FakeLayoutPage:
        return self._pages[index]

    def close(self) -> None:
        return None


class FakeTable:
    def __init__(self, bbox, rows):
        self.bbox = bbox
        self._rows = rows

    def extract(self):
        return self._rows


class FakePlumberPage:
    def __init__(self, tables):
        self._tables = tables

    def find_tables(self):
        return self._tables


class FakePlumberDoc:
    def __init__(self, pages):
        self.pages = pages

    def close(self) -> None:
        return None


def test_layout_analyzer_returns_expected_block_types(monkeypatch, tmp_path) -> None:
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")
    fake_fitz = SimpleNamespace(open=lambda path: FakeDoc([FakeLayoutPage()]))
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(open=lambda path: FakePlumberDoc([FakePlumberPage([])])),
    )

    result = analyze_pdf_layout(str(fake_pdf))

    assert result["page_count"] == 1
    block_types = {block["block_type"] for block in result["blocks"]}
    assert {"header", "title", "text", "footer"}.issubset(block_types)


def test_image_extractor_builds_summary_chunks(monkeypatch, tmp_path) -> None:
    import app.gwy.llm.multimodal_service as multimodal_module

    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")
    fake_fitz = SimpleNamespace(open=lambda path: FakeDoc([FakeLayoutPage()]))
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setattr(FakeLayoutPage, "get_images", lambda self, full=False: [(12,)])  # noqa: ARG005
    monkeypatch.setattr(
        FakeLayoutPage,
        "get_image_rects",
        lambda self, xref: [FakeRect(20, 20, 120, 120)],  # noqa: ARG005
    )
    monkeypatch.setattr(
        multimodal_module.MultimodalSummaryService,
        "summarize_image",
        lambda self, **kwargs: {
            "summary": "图片内容摘要",
            "ocr_text": "图片文字",
            "extraction_status": "success",
        },
    )

    assets = extract_pdf_image_assets(
        str(fake_pdf),
        layout_pages=[{"page": 1, "blocks": [{"block_type": "text", "bbox": [0, 0, 0, 0], "text": "附近文本"}]}],
    )
    chunks = image_assets_to_chunks(assets)

    assert len(assets) == 1
    assert assets[0]["summary"] == "图片内容摘要"
    assert chunks[0]["chunk_type"] == "image_summary"
    assert chunks[0]["metadata"]["asset_type"] == "image"


def test_table_extractor_builds_table_and_row_chunks(monkeypatch, tmp_path) -> None:
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")
    fake_tables = [FakeTable((10, 10, 300, 200), [["姓名", "成绩"], ["张三", "90"], ["李四", "88"]])]
    fake_fitz = SimpleNamespace(
        open=lambda path: FakeDoc([FakeLayoutPage()]),
        Rect=lambda *args: FakeRect(*args),
        Matrix=lambda *args: None,
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    monkeypatch.setitem(
        sys.modules,
        "pdfplumber",
        SimpleNamespace(open=lambda path: FakePlumberDoc([FakePlumberPage(fake_tables)])),
    )

    result = extract_pdf_tables(str(fake_pdf), layout_pages=[{"page": 1, "blocks": []}])

    assert len(result["tables"]) == 1
    assert len(result["rows"]) == 2
    assert len(result["chunks"]) == 3
    assert "姓名" in result["tables"][0]["markdown_content"]


def test_cross_page_table_merger_merges_continuations() -> None:
    merged = merge_cross_page_tables(
        [
            {
                "table_id": "table-a",
                "page_start": 1,
                "page_end": 1,
                "columns": ["姓名", "成绩"],
                "rows": [["张三", "90"]],
                "bbox": [10, 10, 300, 200],
                "source_pages": [1],
                "linked_chunk_ids": [],
                "markdown_content": "| 姓名 | 成绩 |\n| --- | --- |\n| 张三 | 90 |",
            },
            {
                "table_id": "table-b",
                "page_start": 2,
                "page_end": 2,
                "columns": ["姓名", "成绩"],
                "rows": [["李四", "88"]],
                "bbox": [12, 12, 302, 210],
                "source_pages": [2],
                "linked_chunk_ids": [],
                "markdown_content": "| 姓名 | 成绩 |\n| --- | --- |\n| 李四 | 88 |",
            },
        ]
    )

    assert len(merged) == 1
    assert merged[0]["is_cross_page"] is True
    assert merged[0]["page_end"] == 2


def test_asset_linker_links_assets_to_chunks() -> None:
    result = link_assets_to_chunks(
        [
            {
                "chunk_id": "chunk-1",
                "content": "正文",
                "page_start": 1,
                "page_end": 1,
                "metadata": {},
            }
        ],
        layout_pages=[
            {
                "page": 1,
                "blocks": [
                    {"block_type": "text", "bbox": [10, 10, 100, 100], "text": "正文"},
                ],
            }
        ],
        image_assets=[
            {
                "image_id": "image-1",
                "page": 1,
                "bbox": [12, 12, 80, 80],
            }
        ],
        table_assets=[
            {
                "table_id": "table-1",
                "page_start": 1,
                "page_end": 1,
                "bbox": [15, 15, 120, 120],
            }
        ],
    )

    chunk = result["chunks"][0]
    assert chunk["bbox_list"]
    assert "image-1" in chunk["linked_image_ids"]
    assert "table-1" in chunk["linked_table_ids"]
