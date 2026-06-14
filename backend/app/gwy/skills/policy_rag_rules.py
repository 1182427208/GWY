from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class IntentRule:
    intent: str
    keywords: tuple[str, ...]
    doc_group: str
    doc_type: str | None = None


POSITION_RECOMMENDATION_KEYWORDS: tuple[str, ...] = (
    "岗位推荐",
    "推荐岗位",
    "推荐几个岗位",
    "适合我的岗位",
    "我能报哪些岗位",
    "能报哪些岗位",
    "我能报什么岗位",
    "能报什么岗位",
    "筛选岗位",
    "帮我筛选",
    "择岗",
    "选岗",
    "岗位匹配",
    "职位推荐",
    "国考职位推荐",
    "公考职位推荐",
)


INTENT_RULES: tuple[IntentRule, ...] = (
    IntentRule(
        intent="position_recommendation",
        keywords=POSITION_RECOMMENDATION_KEYWORDS,
        doc_group="position_table",
        doc_type="position_recommendation",
    ),
    IntentRule(
        intent="admission_ticket",
        keywords=("准考证", "打印准考证", "下载准考证"),
        doc_group="exam_affairs_qa",
        doc_type="admission_ticket",
    ),
    IntentRule(
        intent="registration_confirmation",
        keywords=("报名确认", "确认方式", "确认时间", "确认地点"),
        doc_group="exam_affairs_qa",
        doc_type="registration_confirmation",
    ),
    IntentRule(
        intent="registration_number",
        keywords=("报名序号",),
        doc_group="exam_affairs_qa",
        doc_type="registration_number",
    ),
    IntentRule(
        intent="score_query",
        keywords=("成绩", "笔试成绩单", "查询笔试成绩"),
        doc_group="exam_affairs_qa",
        doc_type="score_query",
    ),
    IntentRule(
        intent="qualification_status",
        keywords=("资格审核状态", "状态查询"),
        doc_group="exam_affairs_qa",
        doc_type="qualification_status",
    ),
    IntentRule(
        intent="qualification_review",
        keywords=("资格审核", "审核"),
        doc_group="policy_qa",
        doc_type="qualification_review",
    ),
    IntentRule(
        intent="application_conditions",
        keywords=("报考条件", "报考资格", "条件限制"),
        doc_group="policy_qa",
        doc_type="application_conditions",
    ),
    IntentRule(
        intent="registration_policy",
        keywords=("报名", "报考", "职位填报", "注册"),
        doc_group="policy_qa",
        doc_type="registration_policy",
    ),
    IntentRule(
        intent="written_exam",
        keywords=("笔试",),
        doc_group="policy_qa",
        doc_type="written_exam",
    ),
    IntentRule(
        intent="interview",
        keywords=("面试",),
        doc_group="policy_qa",
        doc_type="interview",
    ),
    IntentRule(
        intent="physical_exam_and_inspection",
        keywords=("体检", "考察"),
        doc_group="policy_qa",
        doc_type="physical_exam_and_inspection",
    ),
    IntentRule(
        intent="discipline",
        keywords=("违纪", "违规", "纪律", "处理"),
        doc_group="policy_qa",
        doc_type="discipline",
    ),
    IntentRule(
        intent="public_subject_outline",
        keywords=("公共科目考试大纲", "考试大纲", "大纲"),
        doc_group="exam_outline",
        doc_type="public_subject_outline",
    ),
    IntentRule(
        intent="technical_qa",
        keywords=("信息修改", "考生注册", "个人信息", "照片处理", "密码"),
        doc_group="technical_qa",
        doc_type="other_policy",
    ),
)

GENERAL_CHAT_KEYWORDS: tuple[str, ...] = (
    "你好",
    "您好",
    "hello",
    "hi",
    "谢谢",
    "多谢",
    "你是谁",
    "你能帮我做什么",
    "你能帮我什么",
    "你可以帮我什么",
    "你会什么",
    "介绍一下自己",
    "介绍一下",
    "解释一下",
    "说明一下",
    "总结一下",
    "怎么使用",
    "怎么操作",
    "怎么用",
    "帮我看看",
    "帮我总结",
    "帮我解释",
    "请问",
)

POLICY_SIGNAL_KEYWORDS: tuple[str, ...] = (
    "公务员",
    "国考",
    "省考",
    "招录",
    "招聘",
    "报名",
    "报考",
    "准考证",
    "资格",
    "审核",
    "公告",
    "考试",
    "笔试",
    "面试",
    "体检",
    "考察",
    "成绩",
    "专业",
    "专业目录",
    "学历",
    "学位",
    "年龄",
    "应届",
    "基层",
    "户籍",
    "职位",
    "岗位",
    "条件",
    "限制",
    "材料",
    "科目",
    "大纲",
    "违纪",
    "违规",
    "政审",
    "确认",
    "填报",
    "审核",
    "推荐岗位",
    "岗位推荐",
)

INTENT_LABELS: dict[str, str] = {
    "position_recommendation": "岗位推荐",
    "admission_ticket": "准考证",
    "registration_confirmation": "报名确认",
    "registration_number": "报名序号",
    "score_query": "成绩查询",
    "qualification_status": "资格审核状态",
    "qualification_review": "资格审核",
    "application_conditions": "报考条件",
    "registration_policy": "报名政策",
    "written_exam": "笔试",
    "interview": "面试",
    "physical_exam_and_inspection": "体检考察",
    "discipline": "违纪处理",
    "public_subject_outline": "考试大纲",
    "technical_qa": "技术问答",
}

QUERY_HINTS: dict[str, tuple[str, ...]] = {
    "position_recommendation": ("岗位筛选", "专业匹配", "学历匹配"),
    "admission_ticket": ("打印准考证", "准考证打印时间", "准考证下载"),
    "registration_confirmation": ("报名确认", "确认流程", "确认时间地点"),
    "registration_number": ("报名序号", "报名编号"),
    "score_query": ("笔试成绩单", "成绩发布时间"),
    "qualification_status": ("资格审核状态查询", "审核结果"),
    "qualification_review": ("资格审核条件", "审核材料", "资格审核"),
    "application_conditions": ("报考条件", "报考资格", "专业要求"),
    "registration_policy": ("报名流程", "职位填报", "注册账号"),
    "written_exam": ("笔试安排", "考试时间", "考试要求"),
    "interview": ("面试安排", "面试形式", "面试要求"),
    "physical_exam_and_inspection": ("体检标准", "考察要求", "体检安排"),
    "discipline": ("违纪违规处理", "考试纪律", "处分规定"),
    "public_subject_outline": ("行政职业能力测验", "申论", "模块要求"),
    "technical_qa": ("信息修改", "照片处理", "考生注册"),
}


def route_intent(query: str) -> dict[str, str | bool]:
    normalized = query.strip()
    if not normalized:
        return {
            "intent": "unknown",
            "doc_group": "policy_qa",
            "doc_type": "other_policy",
            "need_rag": True,
        }

    policy_signal = _contains_any(normalized, POLICY_SIGNAL_KEYWORDS)
    direct_signal = _contains_any(normalized, GENERAL_CHAT_KEYWORDS)
    if _looks_like_position_recommendation(normalized):
        return {
            "intent": "position_recommendation",
            "doc_group": "position_table",
            "doc_type": "position_recommendation",
            "need_rag": False,
        }

    if _looks_like_position_profile_query(normalized):
        return {
            "intent": "position_recommendation",
            "doc_group": "position_table",
            "doc_type": "position_recommendation",
            "need_rag": False,
        }

    for rule in INTENT_RULES:
        if any(keyword in normalized for keyword in rule.keywords):
            need_rag = rule.intent not in {"position_recommendation"}
            return {
                "intent": rule.intent,
                "doc_group": rule.doc_group,
                "doc_type": rule.doc_type or "other_policy",
                "need_rag": need_rag,
            }

    if policy_signal:
        return {
            "intent": "unknown",
            "doc_group": "policy_qa",
            "doc_type": "other_policy",
            "need_rag": True,
        }

    if direct_signal:
        return {
            "intent": "general_chat",
            "doc_group": "technical_qa",
            "doc_type": "other_policy",
            "need_rag": False,
        }

    return {
        "intent": "general_chat",
        "doc_group": "technical_qa",
        "doc_type": "other_policy",
        "need_rag": False,
    }


def build_rewritten_queries(query: str, intent: str) -> list[str]:
    normalized = query.strip()
    if not normalized:
        return []

    hints = list(QUERY_HINTS.get(intent, ()))
    candidates = [
        normalized,
        f"{normalized} 官方说明",
        f"{normalized} 具体要求",
    ]
    if hints:
        candidates.append(f"{normalized} {' '.join(hints[:2])}")

    rewritten: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in rewritten:
            rewritten.append(candidate)
        if len(rewritten) >= 3:
            break
    return rewritten


def build_doc_title_hint(intent: str) -> str | None:
    return INTENT_LABELS.get(intent)


def build_filter_parts(
    *,
    year: int,
    exam_type: str,
    intent: str,
    doc_group: str,
    doc_type: str,
) -> list[str]:
    parts = [
        f"year == {year}",
        f'exam_type == "{_escape_expr(exam_type)}"',
    ]
    if doc_group:
        parts.append(f'doc_group == "{_escape_expr(doc_group)}"')
    if doc_type and doc_type != "other_policy":
        parts.append(f'doc_type == "{_escape_expr(doc_type)}"')
    if intent == "public_subject_outline":
        parts.append('doc_type == "public_subject_outline"')
    return parts


def build_cache_key(
    *,
    session_id: str | None,
    query: str,
    year: int,
    exam_type: str,
    doc_group: str,
    doc_type: str,
) -> str:
    import hashlib
    import json

    payload = json.dumps(
        {
            "session_id": session_id,
            "query": query.strip(),
            "year": year,
            "exam_type": exam_type,
            "doc_group": doc_group,
            "doc_type": doc_type,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _looks_like_position_recommendation(text: str) -> bool:
    has_position_word = any(
        token in text for token in ("岗位", "职位", "职位表", "岗位表", "公考职位表", "公务员职位表")
    )
    if not has_position_word:
        return any(
            token in text
            for token in (
                "我能报哪些",
                "能报哪些",
                "适合我",
                "哪些能报",
                "帮我筛选",
                "帮我分析",
                "帮我找",
                "帮我看",
            )
        )
    recommendation_hints = (
        "推荐",
        "筛选",
        "适合我",
        "适合我的",
        "帮我找",
        "帮我看",
        "哪些",
        "能报",
        "可报",
        "选岗",
        "择岗",
        "分析哪个更适合",
        "哪个更适合我",
        "比较一下",
    )
    return _contains_any(text, recommendation_hints)


def _looks_like_position_profile_query(text: str) -> bool:
    profile_signals = 0
    signal_groups = (
        ("专业", "我的专业", "学的是"),
        ("学历", "本科", "硕士", "博士", "专科", "大专", "研究生"),
        ("学位", "学士", "硕士学位", "博士学位"),
        ("政治面貌", "中共党员", "党员", "群众", "共青团员", "预备党员"),
        ("应届", "应届生", "2026届", "2025届", "毕业"),
        ("基层", "基层工作", "基层经历", "无基层工作经验"),
        ("地区", "北京", "上海", "广东", "浙江", "江苏", "中央"),
    )
    for group in signal_groups:
        if any(token in text for token in group):
            profile_signals += 1
    if profile_signals < 2:
        return False
    if any(token in text for token in ("推荐", "筛选", "适合", "能报", "可报", "分析", "择岗", "选岗")):
        return True
    return profile_signals >= 3


def _escape_expr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
