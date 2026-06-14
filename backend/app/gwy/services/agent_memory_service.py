"""Agent memory service: short-term + long-term memory.

Short-term (working memory):
- Redis TTL cache for intermediate analysis state
- Key-value store scoped per conversation/session

Long-term:
- Cross-session aggregation via GwyDecisionMemory + GwyConversationMemory
- Auto-extract preferences from chat messages
- Build memory-augmented prompts for downstream agents
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from app.gwy.models import (
    GwyConversationMemory,
    GwyDecisionMemory,
    GwyRecommendationTask,
    GwyUserProfile,
)

logger = logging.getLogger(__name__)

_SHORT_TERM_TTL_SECONDS = 86400

_MK_USER_PREFERENCES = "user_preferences"
_MK_ANALYSIS_PROGRESS = "analysis_progress"
_MK_LAST_RECOMMENDATIONS = "last_recommendations"
_MK_TASK_CONTEXT = "task_context"

# Build regex patterns at module load time to avoid source encoding issues
def _build_preference_patterns():
    NL = chr(10)
    return [
        (
            "target_regions",
            re.compile(
                r"(?:想去|想要|意向)[^。，“,." + NL + r"]{0,10}?"
                r"(北京|上海|天津|重庆|广州|深圳|杭州|南京|"
                r"武汉|成都|西安|苏州|浙江|广东|江苏|山东|"
                r"四川|河南|湖北|湖南|福建|安徽|江西|辽宁|"
                r"吉林|黑龙江|河北|山西|陕西|甘肃|云南|贵州|"
                r"海南|内蒙古|宁夏|青海|新疆|西藏|广西)"
            ),
        ),
        (
            "desired_departments",
            re.compile(
                r"(?:想进|想去|目标)[^。，“,." + NL + r"]{0,10}?"
                r"(国税|海关|公安|法院|检察院|纪委|"
                r"组织部|宣传部|发改委|教育部|科技部|"
                r"工信部|财政部|人社部|自然资源部|"
                r"生态环境部|住建部|交通运输部|水利部|"
                r"农业农村部|商务部|文化和旅游部|"
                r"卫生健康委|退役军人事务部|市场监管总局|"
                r"金融监管总局|银保监会|证监会|统计局)"
            ),
        ),
        ("degree", re.compile(r"(?:我是|学历是|学位是|学历为|学历)([^，。,." + NL + r"]{1,6})")),
        (
            "name",
            re.compile(
                r"(?:我叫|我的名字叫|我的姓名叫|请叫我|称呼我为|以后叫我)\s*([^^\s，。！？?!]{1,12})"
            ),
        ),
        (
            "nickname",
            re.compile(
                r"(?:可以叫我|大家叫我|我的昵称是|昵称是|称呼我为)\s*([^^\s，。！？?!]{1,12})"
            ),
        ),
        ("major", re.compile(r"(?:专业是|学的是|我的专业是|专业为)([^，。,." + NL + r"]{1,20})")),
    ]

_PREFERENCE_PATTERNS = _build_preference_patterns()


def _looks_like_invalid_identity_value(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    normalized = re.sub(r"[。！？?!,，；;:：]+$", "", text)
    if not normalized:
        return True
    if len(normalized) > 16:
        return True
    if re.search(r"\s", normalized):
        return True
    if any(
        token in normalized
        for token in (
            "什么",
            "谁",
            "哪",
            "多少",
            "怎么",
            "如何",
            "未知",
            "待定",
            "暂无",
            "占位",
            "null",
            "none",
            "N/A",
        )
    ):
        return True
    return False


class AgentMemoryService:

    def __init__(self, *, session: Session, redis_client: Any = None, user_id: UUID | None = None, conversation_id: str | None = None) -> None:
        self.session = session
        self.redis = redis_client
        self.user_id = user_id
        self.conversation_id = conversation_id

    def set_working_memory(self, key: str, value: dict[str, Any], ttl_seconds: int = _SHORT_TERM_TTL_SECONDS) -> None:
        full_key = self._mk_redis_key(key)
        if self.redis:
            try:
                self.redis.setex(full_key, ttl_seconds, json.dumps(value, ensure_ascii=False))
            except Exception:
                logger.warning("Redis set failed for key=%s", key)
        if self.conversation_id is not None:
            self._upsert_pg_memory(key, value)

    def get_working_memory(self, key: str) -> dict[str, Any] | None:
        full_key = self._mk_redis_key(key)
        if self.redis:
            try:
                raw = self.redis.get(full_key)
                if raw:
                    return json.loads(raw)
            except Exception:
                logger.warning("Redis get failed for key=%s", key)
        if self.conversation_id is not None:
            return self._load_pg_memory(key)
        return None

    def save_analysis_progress(self, progress: dict[str, Any]) -> None:
        self.set_working_memory(_MK_ANALYSIS_PROGRESS, progress)

    def save_recommendations(self, recommendations: list[dict[str, Any]]) -> None:
        self.set_working_memory(_MK_LAST_RECOMMENDATIONS, {"recommendations": recommendations, "count": len(recommendations)})

    def save_task_context(self, context: dict[str, Any]) -> None:
        self.set_working_memory(_MK_TASK_CONTEXT, context)

    def extract_preferences_from_message(self, user_message: str) -> dict[str, Any]:
        extracted: dict[str, Any] = {}
        for field, pattern in _PREFERENCE_PATTERNS:
            match = pattern.search(user_message)
            if match:
                value = match.group(1).strip()
                if value and len(value) < 100:
                    if field in {"name", "nickname"} and _looks_like_invalid_identity_value(value):
                        continue
                    extracted[field] = value
        if extracted and self.conversation_id is not None:
            existing = self.get_working_memory(_MK_USER_PREFERENCES) or {}
            existing.update(extracted)
            self.set_working_memory(_MK_USER_PREFERENCES, existing)
        return extracted

    def get_extracted_preferences(self) -> dict[str, Any]:
        return self.get_working_memory(_MK_USER_PREFERENCES) or {}

    def get_long_term_context(self) -> dict[str, Any]:
        if self.user_id is None:
            return {}
        decisions = self.session.exec(
            select(GwyDecisionMemory).where(GwyDecisionMemory.user_id == self.user_id).order_by(GwyDecisionMemory.created_at.desc()).limit(20)
        ).all()
        liked_positions: list[str] = []
        disliked_positions: list[str] = []
        for d in decisions:
            info = str(d.position_id)
            if d.decision_reason:
                info += "(" + d.decision_reason + ")"
            if d.decision_type == "like":
                liked_positions.append(info)
            elif d.decision_type == "dislike":
                disliked_positions.append(info)
        tasks = self.session.exec(
            select(GwyRecommendationTask).where(GwyRecommendationTask.user_id == self.user_id).order_by(GwyRecommendationTask.created_at.desc()).limit(5)
        ).all()
        conv_memories = self.session.exec(
            select(GwyConversationMemory).where(GwyConversationMemory.user_id == self.user_id).order_by(GwyConversationMemory.created_at.desc()).limit(30)
        ).all()
        cross_session_prefs: dict[str, Any] = {}
        for mem in conv_memories:
            if mem.memory_key == _MK_USER_PREFERENCES:
                cross_session_prefs.update(mem.memory_value or {})
        profile_stmt = select(GwyUserProfile).where(
            GwyUserProfile.user_id == self.user_id
        )
        profile = self.session.exec(profile_stmt).first()
        user_profile: dict[str, Any] = {}
        if profile is not None:
            user_profile = {
                "name": profile.name if not _looks_like_invalid_identity_value(profile.name) else None,
                "nickname": profile.nickname if not _looks_like_invalid_identity_value(profile.nickname) else None,
                "education": profile.education,
                "degree": profile.degree,
                "major": profile.major,
                "political_status": profile.political_status,
                "is_fresh_graduate": profile.is_fresh_graduate,
                "grassroots_experience_years": profile.grassroots_experience_years,
                "target_regions": list(profile.target_regions or []),
                "avoid_conditions": list(profile.avoid_conditions or []),
                "desired_departments": list(profile.desired_departments or []),
                "desired_positions": list(profile.desired_positions or []),
                "excluded_positions": list(profile.excluded_positions or []),
                "daily_study_hours": profile.daily_study_hours,
                "notes": profile.notes,
            }
        return {
            "historical_task_count": len(tasks),
            "liked_positions_count": len(liked_positions),
            "disliked_positions_count": len(disliked_positions),
            "recent_liked": liked_positions[:5],
            "recent_disliked": disliked_positions[:5],
            "cross_session_preferences": cross_session_prefs,
            "user_profile": user_profile,
        }

    def build_memory_prompt(self) -> str:
        parts: list[str] = []
        prefs = self.get_extracted_preferences()
        if prefs:
            parts.append("当前会话偏好（仅供参考，优先使用用户最新明确说明）：")
            for k, v in prefs.items():
                parts.append("- " + k + ": " + str(v))
        lt = self.get_long_term_context()
        user_profile = lt.get("user_profile") or {}
        if user_profile:
            parts.append("用户基础资料（仅供参考，遇到冲突时以用户最新说明为准）：")
            profile_fields = [
                ("political_status", "政治面貌"),
                ("major", "专业"),
                ("education", "学历"),
                ("degree", "学位"),
                ("name", "姓名"),
                ("nickname", "昵称"),
                ("target_regions", "地区偏好"),
                ("desired_departments", "部门偏好"),
                ("desired_positions", "岗位偏好"),
                ("is_fresh_graduate", "应届"),
                ("grassroots_experience_years", "基层年限"),
            ]
            for key, label in profile_fields:
                value = user_profile.get(key)
                if value in (None, "", [], {}):
                    continue
                parts.append("- " + label + ": " + str(value))
        if lt.get("historical_task_count"):
            parts.append(
                "历史：已进行"
                + str(lt["historical_task_count"])
                + "次岗位分析，感兴趣"
                + str(lt["liked_positions_count"])
                + "次，不感兴趣"
                + str(lt["disliked_positions_count"])
                + "次"
            )
        cross_prefs = lt.get("cross_session_preferences", {})
        if cross_prefs:
            parts.append("长期偏好（可被后续对话更新）：")
            for k, v in cross_prefs.items():
                parts.append("- " + k + ": " + str(v))
        progress = self.get_working_memory(_MK_ANALYSIS_PROGRESS)
        if progress:
            stage = progress.get("stage", "")
            parts.append("当前任务阶段: " + str(stage))
        if not parts:
            return ""
        return "以下信息仅供参考，后续如有新说明请以用户最新表述为准。\n" + chr(10).join(parts)

    def _mk_redis_key(self, key: str) -> str:
        cid = self.conversation_id or "global"
        uid = str(self.user_id) if self.user_id else "anon"
        return "gwy:mem:" + uid + ":" + cid + ":" + key

    def _upsert_pg_memory(self, key: str, value: dict[str, Any]) -> None:
        if self.conversation_id is None:
            return
        stmt = select(GwyConversationMemory).where(
            GwyConversationMemory.conversation_id == self.conversation_id,
            GwyConversationMemory.memory_key == key,
        )
        if self.user_id is not None:
            stmt = stmt.where(GwyConversationMemory.user_id == self.user_id)
        mem = self.session.exec(stmt).first()
        if mem is None:
            mem = GwyConversationMemory(
                user_id=self.user_id, conversation_id=self.conversation_id,
                memory_key=key, memory_value=value,
            )
        else:
            mem.memory_value = value
        self.session.add(mem)
        self.session.commit()

    def _load_pg_memory(self, key: str) -> dict[str, Any] | None:
        stmt = select(GwyConversationMemory).where(
            GwyConversationMemory.conversation_id == self.conversation_id,
            GwyConversationMemory.memory_key == key,
        )
        if self.user_id is not None:
            stmt = stmt.where(GwyConversationMemory.user_id == self.user_id)
        mem = self.session.exec(stmt).first()
        return dict(mem.memory_value or {}) if mem else None

