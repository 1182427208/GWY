from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import delete, select

from app.gwy.models import GwyPosition
from app.gwy.services import position_importer
from app.gwy.services.position_importer import (
    HEADER_TO_FIELD,
    POSITION_HEADERS,
    import_positions_from_directory,
)


@pytest.fixture(autouse=True)
def _clear_positions(db) -> None:
    db.exec(delete(GwyPosition))
    db.commit()
    yield
    db.exec(delete(GwyPosition))
    db.commit()


def _header_for_field(field_name: str) -> str:
    for header, mapped_field in HEADER_TO_FIELD.items():
        if mapped_field == field_name:
            return header
    raise KeyError(field_name)


def _build_row(**field_values: object) -> list[object | None]:
    header_index = {header: index for index, header in enumerate(POSITION_HEADERS)}
    row: list[object | None] = [None] * len(POSITION_HEADERS)
    for field_name, value in field_values.items():
        header = _header_for_field(field_name)
        row[header_index[header]] = value
    return row


class _FakeSheet:
    def __init__(self, rows: list[list[object | None]]) -> None:
        self._rows = rows
        self.nrows = len(rows)

    def row_values(self, index: int) -> list[object | None]:
        return self._rows[index]


class _FakeWorkbook:
    def __init__(self, sheets: dict[str, _FakeSheet]) -> None:
        self._sheets = sheets

    def sheet_names(self) -> list[str]:
        return list(self._sheets.keys())

    def sheet_by_name(self, sheet_name: str) -> _FakeSheet:
        return self._sheets[sheet_name]


def _make_workbook(*, year: int, recruit_count: int, source_suffix: str) -> _FakeWorkbook:
    header_row = list(POSITION_HEADERS)
    data_row = _build_row(
        department_code="1001",
        department_name="中央机关测试局",
        office_name="综合处",
        institution_type="中央机关",
        job_title="综合管理岗",
        position_attribute="普通职位",
        position_distribution="北京",
        position_desc="用于测试的岗位",
        position_code=f"POS-{year}",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=recruit_count,
        major_requirement="计算机类",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="不限",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="3:1",
        work_location="北京",
        household_registration_location="北京",
        remarks="测试数据",
        department_website="https://example.com",
        contact_phone_1="010-00000000",
    )
    rows = [
        ["title row"],
        header_row,
        data_row,
    ]
    return _FakeWorkbook({"Sheet1": _FakeSheet(rows)})


def test_import_positions_from_directory_replaces_only_matching_years(
    db,
    tmp_path: Path,
    monkeypatch,
) -> None:
    workbook_dir = tmp_path / "国考职位表"
    workbook_dir.mkdir()

    file_2024 = workbook_dir / "positions_2024.xls"
    file_2025 = workbook_dir / "positions_2025.xls"
    file_2026 = workbook_dir / "positions_2026.xls"
    file_2024.write_bytes(b"")
    file_2025.write_bytes(b"")
    file_2026.write_bytes(b"")

    fake_workbooks = {
        file_2024.name: _make_workbook(year=2024, recruit_count=12, source_suffix="A"),
        file_2025.name: _make_workbook(year=2025, recruit_count=10, source_suffix="B"),
        file_2026.name: _make_workbook(year=2026, recruit_count=8, source_suffix="C"),
    }

    def fake_open_workbook(path: Path) -> _FakeWorkbook:
        return fake_workbooks[Path(path).name]

    monkeypatch.setattr(position_importer.xlrd, "open_workbook", fake_open_workbook)

    existing = GwyPosition(
        department_code="1001",
        department_name="中央机关测试局",
        office_name="综合处",
        institution_type="中央机关",
        job_title="综合管理岗",
        position_attribute="普通职位",
        position_distribution="北京",
        position_desc="已存在的2026测试岗位",
        position_code="POS-2026",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=99,
        major_requirement="计算机类",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="不限",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="99:1",
        work_location="北京",
        household_registration_location="北京",
        remarks="旧数据",
        department_website="https://example.com",
        contact_phone_1="010-00000000",
        source_file=file_2026.name,
        source_sheet="Sheet1",
        source_row_number=3,
        raw_data={"position_code": "POS-2026"},
    )
    db.add(existing)
    db.commit()

    result = import_positions_from_directory(
        db,
        workbook_dir,
        years=[2024, 2025],
        replace_existing=True,
    )

    assert result["imported_count"] == 2
    assert sorted(result["imported_years"]) == [2024, 2025]

    rows = list(db.exec(select(GwyPosition)).all())
    assert len(rows) == 3
    source_files = {row.source_file for row in rows}
    assert source_files == {file_2024.name, file_2025.name, file_2026.name}

    row_2026 = db.exec(
        select(GwyPosition).where(GwyPosition.source_file == file_2026.name)
    ).first()
    assert row_2026 is not None
    assert row_2026.recruit_count == 99
    assert row_2026.remarks == "旧数据"

    row_2024 = db.exec(
        select(GwyPosition).where(GwyPosition.source_file == file_2024.name)
    ).first()
    row_2025 = db.exec(
        select(GwyPosition).where(GwyPosition.source_file == file_2025.name)
    ).first()
    assert row_2024 is not None
    assert row_2025 is not None
    assert row_2024.recruit_count == 12
    assert row_2025.recruit_count == 10
