from __future__ import annotations

from app.gwy.document import pdf_loader
from app.gwy.document.pdf_loader import load_pdf_pages, strip_document_chrome


def test_strip_document_chrome_removes_repeated_site_header() -> None:
    text = (
        "2026年5月7日 星期三 下午好！\n"
        "国家公务员局 中央机关及其直属机构2026年度考试录用公务员专题\n"
        "首页 招考公告 政策法规 常见问题 相关下载 公告公示 个人中心\n"
        "首页 > 招考公告 > 招考公告\n"
        "中央机关及其直属机构2026年度考试录用公务员公告\n"
        "发布日期：2025-10-14\n"
        "第一章 报考政策规定\n"
        "一、关于报考条件\n"
        "1. 非普通高等学历教育的其他国民教育形式的毕业生是否可以报考？\n"
        "答：可以报考。\n"
        "咨询电话\n"
        "<<"
    )

    cleaned = strip_document_chrome(text)

    assert "国家公务员局" not in cleaned
    assert "首页" not in cleaned
    assert "咨询电话" not in cleaned
    assert "<<" not in cleaned
    assert "中央机关及其直属机构2026年度考试录用公务员公告" in cleaned
    assert "1. 非普通高等学历教育的其他国民教育形式的毕业生是否可以报考？" in cleaned


def test_strip_document_chrome_removes_inline_chrome_but_keeps_body() -> None:
    text = (
        "2026年5月7日 星期三 下午好！ 国家公务员局 中央机关及其直属机构2026年度考试录用公务员专题 "
        "首页 > 招考公告 > 招考公告 中央机关及其直属机构2026年度考试录用公务员报名指南 "
        "发布日期：2025-10-14 第一章 报考政策规定 一、关于报考条件 "
        "1. 非普通高等学历教育的其他国民教育形式的毕业生是否可以报考？\n"
        "答：可以报考。\n"
        "返回顶部 咨询电话 <<\n"
    )

    cleaned = strip_document_chrome(text)

    assert "国家公务员局" not in cleaned
    assert "首页" not in cleaned
    assert "返回顶部" not in cleaned
    assert "咨询电话" not in cleaned
    assert "中央机关及其直属机构2026年度考试录用公务员报名指南" in cleaned
    assert "第一章 报考政策规定" in cleaned
    assert "1. 非普通高等学历教育的其他国民教育形式的毕业生是否可以报考？" in cleaned
    assert "答：可以报考。" in cleaned


def test_strip_document_chrome_removes_embedded_footer_noise() -> None:
    text = (
        "正文第一段。首页 > 招考公告 > 招考公告 返回顶部 咨询电话 << 版权所有：国家公务员局 网站所有：国家公务员局\n"
        "正文第二段保留。"
    )

    cleaned = strip_document_chrome(text)

    assert "首页" not in cleaned
    assert "返回顶部" not in cleaned
    assert "咨询电话" not in cleaned
    assert "版权所有" not in cleaned
    assert "正文第一段" in cleaned
    assert "正文第二段保留" in cleaned


def test_load_pdf_pages_falls_back_to_pypdf_when_primary_reader_is_empty(
    monkeypatch,
    tmp_path,
) -> None:
    pdf_path = tmp_path / "sample.pdf"

    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "Candidate registration\nEnter registration from the home page",
    )
    doc.save(str(pdf_path))
    doc.close()

    class EmptyDirectoryReader:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = (args, kwargs)

        def load_data(self) -> list[object]:
            return []

    monkeypatch.setattr(pdf_loader, "SimpleDirectoryReader", EmptyDirectoryReader)

    pages = load_pdf_pages(str(pdf_path))

    assert len(pages) == 1
    assert "Candidate registration" in pages[0]["text"]
