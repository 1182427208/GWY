from __future__ import annotations

from sqlmodel import Session, select

from app.core.config import settings
from app.gwy.agents.position_decision_agent import PositionDecisionAgent
from app.gwy.models import GwyPosition, GwyRecommendationItem, GwyRecommendationTask, GwyUserProfile
from app.models import User


class DummyChatService:
    def chat_completion(self, messages: list[dict[str, object]], temperature: float = 0.2) -> str:  # noqa: ARG002,E501
        return "根据你的条件，我优先推荐这几个岗位。"


def test_position_decision_agent_ranks_positions_from_postgres(db: Session) -> None:
    user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert user is not None

    profile = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    if profile is None:
        profile = GwyUserProfile(
            user_id=user.id,
            education="本科",
            degree="学士",
            major="法学",
            political_status="中共党员",
            is_fresh_graduate=False,
            grassroots_experience_years=0,
            target_regions=["北京"],
        )
        db.add(profile)
    else:
        profile.education = "本科"
        profile.degree = "学士"
        profile.major = "法学"
        profile.political_status = "中共党员"
        profile.is_fresh_graduate = False
        profile.grassroots_experience_years = 0
        profile.target_regions = ["北京"]

    match_position = GwyPosition(
        department_code="001",
        department_name="国家税务总局北京税务局",
        office_name="第一税务分局",
        institution_type="中央国家行政机关",
        job_title="一级行政执法员",
        position_attribute="普通职位",
        position_distribution="北京",
        position_desc="依法行政相关岗位",
        position_code="001",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=2,
        major_requirement="法学",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="中共党员",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="3:1",
        work_location="北京",
        household_registration_location="北京",
        remarks="无",
        department_website="https://example.com",
        contact_phone_1="010-00000000",
        source_file="中央机关及其直属机构2026年度考试录用公务员招考简章.xls",
        source_sheet="一览",
        source_row_number=1,
        raw_data={"岗位": "一级行政执法员"},
    )
    mismatch_position = GwyPosition(
        department_code="002",
        department_name="国家税务总局上海税务局",
        office_name="第二税务分局",
        institution_type="中央国家行政机关",
        job_title="一级行政执法员",
        position_attribute="普通职位",
        position_distribution="上海",
        position_desc="经济相关岗位",
        position_code="002",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=1,
        major_requirement="经济学",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="不限",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="5:1",
        work_location="上海",
        household_registration_location="上海",
        remarks="无",
        department_website="https://example.com",
        contact_phone_1="010-00000001",
        source_file="中央机关及其直属机构2026年度考试录用公务员招考简章.xls",
        source_sheet="一览",
        source_row_number=2,
        raw_data={"岗位": "一级行政执法员"},
    )
    db.add(match_position)
    db.add(mismatch_position)
    db.commit()

    agent = PositionDecisionAgent(session=db, chat_service=DummyChatService())
    result = agent.run(
        query="我是法学本科，中共党员，想在北京找岗位",
        user_id=user.id,
        year=2026,
        exam_type="national",
        top_k=3,
    )

    assert result["recommendations"]
    assert result["recommendations"][0]["position_code"] == "001"
    assert str(result["answer"]).strip()
    assert "国家税务总局北京税务局" in str(result["answer"])
    assert "一级行政执法员" in str(result["answer"])

    task = db.exec(
        select(GwyRecommendationTask).order_by(GwyRecommendationTask.created_at.desc())
    ).first()
    assert task is not None
    items = db.exec(select(GwyRecommendationItem).where(GwyRecommendationItem.task_id == task.id)).all()
    assert len(items) >= 1


def test_position_decision_agent_matches_engineering_family_major(db: Session) -> None:
    user = db.exec(
        select(User).where(User.email == settings.EMAIL_TEST_USER)
    ).first()
    assert user is not None

    profile = db.exec(
        select(GwyUserProfile).where(GwyUserProfile.user_id == user.id)
    ).first()
    if profile is None:
        profile = GwyUserProfile(
            user_id=user.id,
            education="硕士研究生",
            degree="硕士",
            major="工学",
            political_status="中共党员",
            is_fresh_graduate=False,
            grassroots_experience_years=0,
            target_regions=["北京"],
        )
        db.add(profile)
    else:
        profile.education = "硕士研究生"
        profile.degree = "硕士"
        profile.major = "工学"
        profile.political_status = "中共党员"
        profile.is_fresh_graduate = False
        profile.grassroots_experience_years = 0
        profile.target_regions = ["北京"]

    engineering_position = GwyPosition(
        department_code="101",
        department_name="国家发展和改革委员会",
        office_name="信息化处",
        institution_type="中央国家行政机关",
        job_title="一级主任科员及以下",
        position_attribute="普通职位",
        position_distribution="北京",
        position_desc="工学相关岗位",
        position_code="101",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=2,
        major_requirement="0812计算机科学与技术",
        education_requirement="硕士研究生及以上",
        degree_requirement="硕士",
        political_status_requirement="中共党员",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="3:1",
        work_location="北京市",
        household_registration_location="北京市",
        remarks="无",
        department_website="https://example.com",
        contact_phone_1="010-00000010",
        source_file="中央机关及其直属机构2026年度考试录用公务员招考简章.xls",
        source_sheet="一览",
        source_row_number=10,
        raw_data={"岗位": "信息化处"},
    )
    mismatch_position = GwyPosition(
        department_code="102",
        department_name="国家税务总局上海税务局",
        office_name="第二税务分局",
        institution_type="中央国家行政机关",
        job_title="一级主任科员及以下",
        position_attribute="普通职位",
        position_distribution="上海",
        position_desc="经济相关岗位",
        position_code="102",
        institution_level="中央",
        exam_category="中央机关及其直属机构",
        recruit_count=1,
        major_requirement="经济学",
        education_requirement="本科",
        degree_requirement="学士",
        political_status_requirement="不限",
        grassroots_years_requirement="不限",
        grassroots_project_experience="不限",
        professional_test_in_interview="否",
        interview_ratio="5:1",
        work_location="上海",
        household_registration_location="上海",
        remarks="无",
        department_website="https://example.com",
        contact_phone_1="010-00000011",
        source_file="中央机关及其直属机构2026年度考试录用公务员招考简章.xls",
        source_sheet="一览",
        source_row_number=11,
        raw_data={"岗位": "第二税务分局"},
    )
    db.add(engineering_position)
    db.add(mismatch_position)
    db.commit()

    agent = PositionDecisionAgent(session=db, chat_service=DummyChatService())
    result = agent.run(
        query="我是工学硕士，中共党员，想在北京找岗位",
        user_id=user.id,
        year=2026,
        exam_type="national",
        top_k=3,
    )

    assert result["recommendations"]
    assert any(item["position_code"] == "101" for item in result["recommendations"])
    assert "国家发展和改革委员会" in str(result["answer"])


def test_position_decision_agent_asks_for_missing_fields(db: Session) -> None:
    agent = PositionDecisionAgent(session=db, chat_service=DummyChatService())
    result = agent.run(
        query="帮我推荐岗位",
        user_id=None,
        year=2026,
        exam_type="national",
        top_k=3,
    )

    assert result["need_more_info"] is True
    assert "补充" in str(result["answer"])
