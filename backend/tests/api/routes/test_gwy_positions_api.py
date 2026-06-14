from __future__ import annotations

from sqlmodel import Session

from app.gwy.models import GwyPosition


def _create_position(
    *,
    code: str,
    department_name: str,
    major_requirement: str,
    work_location: str,
    source_row_number: int,
) -> GwyPosition:
    return GwyPosition(
        department_code=code,
        department_name=department_name,
        office_name="业务处",
        institution_type="中央国家行政机关",
        job_title="一级主任科员及以下",
        position_attribute="普通职位",
        position_distribution=work_location,
        position_desc="测试岗位",
        position_code=code,
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=2,
        major_requirement=major_requirement,
        education_requirement="硕士研究生及以上",
        degree_requirement="硕士",
        political_status_requirement="中共党员",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="3:1",
        work_location=work_location,
        household_registration_location=work_location,
        remarks="无",
        department_website="https://example.com",
        contact_phone_1="010-00000000",
        source_file="中央机关及其直属机构2026年度考试录用公务员招考简章.xlsx",
        source_sheet="一览表",
        source_row_number=source_row_number,
        raw_data={"岗位代码": code},
    )


def test_positions_list_filters_and_pages(
    client,
    normal_user_token_headers,
    db: Session,
) -> None:
    position_match = _create_position(
        code="PX-001",
        department_name="国家发展和改革委员会",
        major_requirement="0812计算机科学与技术",
        work_location="北京",
        source_row_number=999001,
    )
    position_mismatch = _create_position(
        code="PX-002",
        department_name="国家税务总局上海税务局",
        major_requirement="经济学",
        work_location="上海",
        source_row_number=999002,
    )
    db.add(position_match)
    db.add(position_mismatch)
    db.commit()

    response = client.get(
        "/api/v1/gwy/positions",
        params={
            "major": "工学",
            "education": "硕士研究生",
            "degree": "硕士",
            "political_status": "中共党员",
            "region": "北京",
            "page": 1,
            "page_size": 10,
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert any(item["position_code"] == "PX-001" for item in payload["data"])
    assert all("上海" not in str(item["work_location"]) for item in payload["data"])


def test_positions_grid_returns_all_rows(
    client,
    normal_user_token_headers,
    db: Session,
) -> None:
    first = _create_position(
        code="PX-201",
        department_name="国家发展和改革委员会",
        major_requirement="0812计算机科学与技术",
        work_location="北京",
        source_row_number=999201,
    )
    second = _create_position(
        code="PX-202",
        department_name="国家税务总局",
        major_requirement="经济学",
        work_location="上海",
        source_row_number=999202,
    )
    db.add(first)
    db.add(second)
    db.commit()

    response = client.get(
        "/api/v1/gwy/positions/grid",
        params={"year": 2026},
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 2
    assert len(payload["data"]) >= 2
    assert any(item["position_code"] == "PX-201" for item in payload["data"])
    assert any(item["position_code"] == "PX-202" for item in payload["data"])


def test_positions_analyze_selected_items(
    client,
    normal_user_token_headers,
    db: Session,
) -> None:
    position_match = _create_position(
        code="PX-101",
        department_name="国家发展和改革委员会",
        major_requirement="0812计算机科学与技术",
        work_location="北京",
        source_row_number=999101,
    )
    db.add(position_match)
    db.commit()

    response = client.post(
        "/api/v1/gwy/positions/analyze",
        json={
            "position_ids": [str(position_match.id)],
            "query": "请分析我勾选的岗位",
            "top_k": 5,
            "position_profile": {
                "major": "工学",
                "education": "硕士研究生",
                "degree": "硕士",
                "political_status": "中共党员",
                "target_regions": ["北京"],
            },
        },
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "analysis" in payload
    assert payload["selected_positions"]
    assert payload["recommendations"]
    assert payload["recommendations"][0]["position_code"] == "PX-101"
