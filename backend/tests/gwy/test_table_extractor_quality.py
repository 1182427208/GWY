from __future__ import annotations

from app.gwy.document.table_extractor import _build_table_rows, _is_real_table_candidate


def test_build_table_rows_skips_noise_rows() -> None:
    table = {
        "table_id": "table-1",
        "columns": ["字段1", "字段2"],
        "rows": [
            ["首页 > 招考公告 > 招考公告：", ""],
            ["None", "None"],
            ["有效字段", "值"],
        ],
        "page_start": 1,
        "page_end": 1,
    }

    rows = _build_table_rows(table)

    assert len(rows) == 1
    assert rows[0]["row_text"] == "字段1：有效字段；字段2：值"


def test_build_table_rows_skips_footer_and_chrome_rows() -> None:
    table = {
        "table_id": "table-2",
        "columns": ["col_1", "col_2"],
        "rows": [
            ["版权所有：国家公务员局", "网站所有：国家公务员局"],
            ["首页", "招考公告"],
            ["有效A", "有效B"],
        ],
        "page_start": 1,
        "page_end": 1,
    }

    rows = _build_table_rows(table)

    assert len(rows) == 1
    assert rows[0]["row_text"] == "col_1：有效A；col_2：有效B"


def test_build_table_rows_skips_mixed_none_placeholder_rows() -> None:
    table = {
        "table_id": "table-3",
        "columns": ["col_1", "col_2", "col_3", "col_4", "col_5"],
        "rows": [
            ["None：成本", "None：增量", "玉米：成本", "None：增量", "None：成本"],
            ["有效A", "有效B", "有效C", "有效D", "有效E"],
        ],
        "page_start": 1,
        "page_end": 1,
    }

    rows = _build_table_rows(table)

    assert len(rows) == 1
    assert rows[0]["row_text"] == "col_1：有效A；col_2：有效B；col_3：有效C；col_4：有效D；col_5：有效E"


def test_navigation_bar_table_is_rejected() -> None:
    assert (
        _is_real_table_candidate(
            context="首页 > 招考公告 > 招考公告",
            markdown_content=(
                "| 首页 招考公告 政策法规 | 常见问题 | 相关下载 公告公示 个人中心 |\n"
                "| --- | --- | --- |\n"
                "|  | None | None |"
            ),
            columns=["首页 招考公告 政策法规", "常见问题", "相关下载 公告公示 个人中心"],
            rows=[
                ["首页 招考公告 政策法规", "常见问题", "相关下载 公告公示 个人中心"],
                ["None", "None", "None"],
            ],
            source_file="data/公告.pdf",
        )
        is False
    )


def test_placeholder_table_rows_are_dropped() -> None:
    table = {
        "table_id": "table-4",
        "columns": ["None", "None", "None"],
        "rows": [
            ["1", "2", "3"],
        ],
        "page_start": 1,
        "page_end": 1,
    }

    rows = _build_table_rows(table)

    assert rows == []
