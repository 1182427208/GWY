from __future__ import annotations

import pytest
from sqlmodel import Session, delete, select

from app.gwy.models import GwyPosition
from app.gwy.services.position_catalog_service import (
    PositionCatalogService,
    PositionListFilters,
)


@pytest.fixture(autouse=True)
def _clear_positions(db: Session) -> None:
    db.exec(delete(GwyPosition))
    db.commit()
    yield
    db.exec(delete(GwyPosition))
    db.commit()


class FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str) -> None:
        self.store[key] = value
        self.set_calls.append((key, value))


def _create_position(
    code: str,
    source_row_number: int,
    *,
    source_file: str = "positions_2026.xls",
    department_code: str = "1001",
    department_name: str = "测试部门",
    office_name: str = "测试司局",
    job_title: str = "综合管理岗",
) -> GwyPosition:
    return GwyPosition(
        department_code=department_code,
        department_name=department_name,
        office_name=office_name,
        institution_type="中央机关",
        job_title=job_title,
        position_attribute="普通职位",
        position_distribution="北京",
        position_desc="测试岗位",
        position_code=code,
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=1,
        major_requirement="工学",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="不限",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="3:1",
        work_location="北京",
        household_registration_location="北京",
        remarks="测试",
        department_website="https://example.com",
        contact_phone_1="010-00000000",
        source_file=source_file,
        source_sheet="Sheet1",
        source_row_number=source_row_number,
        raw_data={"position_code": code},
    )


def test_position_grid_uses_redis_cache(db: Session) -> None:
    fake_redis = FakeRedisClient()
    service = PositionCatalogService(db, redis_client=fake_redis)

    first = _create_position("PX-301", 301)
    db.add(first)
    db.commit()

    first_result = service.list_positions_grid(PositionListFilters(year=2026))
    assert first_result["count"] >= 1
    assert fake_redis.set_calls

    second = _create_position("PX-302", 302)
    db.add(second)
    db.commit()

    second_result = service.list_positions_grid(PositionListFilters(year=2026))
    assert second_result["count"] == first_result["count"]
    assert all(item["position_code"] != "PX-302" for item in second_result["data"])


def test_position_history_falls_back_when_position_codes_change(db: Session) -> None:
    current = _create_position(
        "POS-2026-A",
        301,
        source_file="positions_2026.xls",
        department_code="1001",
        department_name="中央机关测试局",
        office_name="综合处",
        job_title="综合管理岗",
    )
    previous_2025 = _create_position(
        "POS-2025-B",
        201,
        source_file="positions_2025.xls",
        department_code="1001",
        department_name="中央机关测试局",
        office_name="综合处",
        job_title="综合管理岗",
    )
    previous_2024 = _create_position(
        "POS-2024-C",
        101,
        source_file="positions_2024.xls",
        department_code="1001",
        department_name="中央机关测试局",
        office_name="综合处",
        job_title="综合管理岗",
    )
    current.recruit_count = 8
    previous_2025.recruit_count = 10
    previous_2024.recruit_count = 12
    current.interview_ratio = "9:1"
    previous_2025.interview_ratio = "7:1"
    previous_2024.interview_ratio = "5:1"

    db.add(current)
    db.add(previous_2025)
    db.add(previous_2024)
    db.commit()

    service = PositionCatalogService(db)
    history = service.get_position_history(current, limit=5)

    assert history["summary"]["record_count"] == 2
    assert history["summary"]["history_years"] == [2025, 2024]
    assert history["summary"]["latest_recruit_count"] == 10
    assert history["summary"]["earliest_recruit_count"] == 12
    assert history["summary"]["recruit_count_trend"] == "upward"
