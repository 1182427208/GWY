from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import xlrd
from sqlalchemy import delete
from sqlmodel import Session

from app.gwy.models import GwyPosition

POSITION_HEADERS = [
    "部门代码",
    "部门名称",
    "用人司局",
    "机构性质",
    "招考职位",
    "职位属性",
    "职位分布",
    "职位简介",
    "职位代码",
    "机构层级",
    "考试类别",
    "招考人数",
    "专业",
    "学历",
    "学位",
    "政治面貌",
    "基层工作最低年限",
    "服务基层项目工作经历",
    "是否在面试阶段组织专业能力测试",
    "面试人员比例",
    "工作地点",
    "落户地点",
    "备注",
    "部门网站",
    "咨询电话1",
    "咨询电话2",
    "咨询电话3",
]

HEADER_TO_FIELD = {
    "部门代码": "department_code",
    "部门名称": "department_name",
    "用人司局": "office_name",
    "机构性质": "institution_type",
    "招考职位": "job_title",
    "职位属性": "position_attribute",
    "职位分布": "position_distribution",
    "职位简介": "position_desc",
    "职位代码": "position_code",
    "机构层级": "institution_level",
    "考试类别": "exam_category",
    "招考人数": "recruit_count",
    "专业": "major_requirement",
    "学历": "education_requirement",
    "学位": "degree_requirement",
    "政治面貌": "political_status_requirement",
    "基层工作最低年限": "grassroots_years_requirement",
    "服务基层项目工作经历": "grassroots_project_experience",
    "是否在面试阶段组织专业能力测试": "professional_test_in_interview",
    "面试人员比例": "interview_ratio",
    "工作地点": "work_location",
    "落户地点": "household_registration_location",
    "备注": "remarks",
    "部门网站": "department_website",
    "咨询电话1": "contact_phone_1",
    "咨询电话2": "contact_phone_2",
    "咨询电话3": "contact_phone_3",
}


def import_positions_from_workbook(
    session: Session,
    workbook_path: str | Path,
    *,
    replace_existing: bool = True,
    replace_source_file: bool = False,
) -> int:
    path = Path(workbook_path)
    if replace_existing:
        session.exec(delete(GwyPosition))
        session.commit()
    elif replace_source_file:
        session.exec(delete(GwyPosition).where(GwyPosition.source_file == path.name))
        session.commit()

    book = xlrd.open_workbook(path)
    count = 0
    for sheet_name in book.sheet_names():
        sheet = book.sheet_by_name(sheet_name)
        count += _import_sheet(
            session=session,
            sheet=sheet,
            sheet_name=sheet_name,
            source_file=path.name,
        )

    session.commit()
    return count


def import_positions_from_directory(
    session: Session,
    directory_path: str | Path,
    *,
    years: list[int] | None = None,
    replace_existing: bool = True,
) -> dict[str, Any]:
    directory = Path(directory_path)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    year_filter = {int(year) for year in years or []}
    workbook_paths = discover_position_workbooks(
        directory,
        years=year_filter or None,
    )

    imported_files: list[dict[str, Any]] = []
    imported_count = 0
    imported_years: list[int] = []

    for workbook_path in workbook_paths:
        year = _extract_year_from_path(workbook_path)
        count = import_positions_from_workbook(
            session,
            workbook_path,
            replace_existing=False,
            replace_source_file=replace_existing,
        )
        imported_count += count
        if year is not None:
            imported_years.append(year)
        imported_files.append(
            {
                "path": str(workbook_path),
                "year": year,
                "imported_count": count,
            }
        )

    return {
        "imported_count": imported_count,
        "imported_years": imported_years,
        "files": imported_files,
    }


def discover_position_workbooks(
    directory_path: str | Path,
    *,
    years: set[int] | None = None,
) -> list[Path]:
    directory = Path(directory_path)
    if not directory.exists():
        return []

    candidates = sorted(directory.rglob("*.xls"))
    if years:
        candidates = [
            path for path in candidates if _extract_year_from_path(path) in years
        ]
    return sorted(
        candidates,
        key=lambda path: (
            _extract_year_from_path(path) or 0,
            path.name,
        ),
    )


def _import_sheet(
    session: Session,
    sheet: xlrd.sheet.Sheet,
    sheet_name: str,
    source_file: str,
) -> int:
    if sheet.nrows < 3:
        return 0

    headers = [str(value).strip() for value in sheet.row_values(1)]
    count = 0
    for row_index in range(2, sheet.nrows):
        row_values = sheet.row_values(row_index)
        record = _build_record(
            headers=headers,
            row_values=row_values,
            source_file=source_file,
            source_sheet=sheet_name,
            source_row_number=row_index + 1,
        )
        if record is None:
            continue
        session.add(GwyPosition(**record))
        count += 1
    return count


def _build_record(
    *,
    headers: list[str],
    row_values: list[Any],
    source_file: str,
    source_sheet: str,
    source_row_number: int,
) -> dict[str, Any] | None:
    normalized_row: dict[str, Any] = {}
    raw_data: dict[str, Any] = {}
    has_value = False

    for header, value in zip(headers, row_values, strict=False):
        normalized_value = _normalize_value(header, value)
        raw_data[header] = normalized_value
        field_name = HEADER_TO_FIELD.get(header)
        if field_name:
            normalized_row[field_name] = normalized_value
        if normalized_value not in (None, ""):
            has_value = True

    if not has_value:
        return None

    normalized_row["source_file"] = source_file
    normalized_row["source_sheet"] = source_sheet
    normalized_row["source_row_number"] = source_row_number
    normalized_row["raw_data"] = raw_data
    return normalized_row


def _normalize_value(header: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if value.is_integer():
            value = int(value)
        else:
            return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        if header == "招考人数" and value.isdigit():
            return int(value)
        return value
    if header == "招考人数":
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


def _extract_year_from_path(path: str | Path) -> int | None:
    match = re.search(r"(20\d{2})", str(path))
    if not match:
        return None
    return int(match.group(1))
