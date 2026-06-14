# GwyPilot Memory Layer Refactor Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor GwyPilot's memory layer to behave like Giftia's layered memory: a concise working memory for the current dialogue, a structured cross-session long-term profile that keeps updating, and prompt injection that feels more natural and less template-driven.

**Architecture:** Keep the existing FastAPI/template layout intact. Rework short-term memory into a summary-driven working memory block with configurable recent-turn fallback, then reorganize long-term memory into prioritized structured profile fields plus cross-session preferences. Finally, centralize prompt ordering so policy RAG, direct answers, and analysis flows all consume the same memory shape.

**Tech Stack:** FastAPI, SQLModel, PostgreSQL, Redis, Pytest, LangGraph prompt/service layer.

---

### Task 1: Lock down the memory contract with tests first

**Files:**
- Modify: `backend/tests/gwy/test_agent_memory_service.py`
- Modify: `backend/tests/gwy/test_chat_session_service.py`
- Modify: `backend/tests/gwy/test_policy_rag_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from uuid import UUID


def test_build_memory_prompt_prioritizes_profile_fields(db_session):
    from app.gwy.services.agent_memory_service import AgentMemoryService
    from app.gwy.models import GwyUserProfile

    user_id = UUID("11111111-1111-1111-1111-111111111111")
    db_session.add(
        GwyUserProfile(
            user_id=user_id,
            name="小李",
            political_status="中共党员",
            major="法学",
            education="本科",
            degree="学士",
        )
    )
    db_session.commit()

    svc = AgentMemoryService(session=db_session, redis_client=None, user_id=user_id)
    prompt = svc.build_memory_prompt()

    assert prompt.index("政治面貌") < prompt.index("专业")
    assert prompt.index("专业") < prompt.index("学历")
    assert "仅供参考，遇到冲突时以用户最新说明为准" in prompt


def test_build_session_summary_compacts_recent_messages(db_session):
    from app.gwy.services.chat_session_service import ChatSessionService

    svc = ChatSessionService(session=db_session, redis_client=None)
    summary = svc.build_session_summary([])

    assert summary == ""


def test_build_memory_block_prefers_long_term_and_working_memory(db_session):
    from app.gwy.services.policy_rag_service import PolicyRagService

    service = PolicyRagService(session=db_session, redis_client=None)
    block = service._build_memory_block(
        {
            "session_summary": "用户在问岗位推荐",
            "active_topic": "岗位筛选",
            "last_intent": "想缩小范围",
            "conversation_memory": {"summary": "短期摘要"},
            "long_term_context": {
                "user_profile": {
                    "political_status": "中共党员",
                    "major": "法学",
                    "education": "本科",
                    "degree": "学士",
                }
            },
        }
    )

    assert "会话摘要" in block
    assert "长期记忆" in block
    assert block.index("政治面貌") < block.index("专业")
```

- [ ] **Step 2: Run the focused tests and confirm they fail for the right reason**

Run: `cd backend && pytest tests/gwy/test_agent_memory_service.py tests/gwy/test_chat_session_service.py tests/gwy/test_policy_rag_service.py -q`
Expected: failures around missing ordering / memory shaping behavior, not import errors.

- [ ] **Step 3: Keep the tests committed as the contract before implementation**

```bash
git add backend/tests/gwy/test_agent_memory_service.py backend/tests/gwy/test_chat_session_service.py backend/tests/gwy/test_policy_rag_service.py
git commit -m "test: lock down layered memory contract"
```

### Task 2: Rework short-term memory into a working-memory style block

**Files:**
- Modify: `backend/app/gwy/services/chat_session_service.py`
- Modify: `backend/app/gwy/services/agent_memory_service.py`
- Modify: `backend/app/gwy/settings.py` or the existing settings module that already holds RAG memory config
- Modify: `backend/tests/gwy/test_chat_session_service.py`
- Modify: `backend/tests/gwy/test_agent_memory_service.py`

- [ ] **Step 1: Add a configurable working-memory window and summary-first context builder**

```python
# In the existing settings module, add a memory window that can be tuned without code changes.
RAG_MEMORY_TURNS = 12
WORKING_MEMORY_OPEN_TOPICS_LIMIT = 5
WORKING_MEMORY_SUMMARY_MAX_CHARS = 200
```

```python
# In chat_session_service.py, make get_memory_context return a concise working-memory payload.
return {
    "session_summary": chat_session.summary or self.build_session_summary(messages),
    "active_topic": chat_session.active_topic,
    "open_topics": list(chat_session.mentioned_docs or [])[:5],
    "last_intent": chat_session.last_intent,
    "recent_messages": [
        {"role": m.role, "content": m.content}
        for m in messages[-(settings.RAG_MEMORY_TURNS * 2) :]
    ],
    "conversation_memory": conversation_memory,
    "long_term_context": long_term_service.build_cross_session_summary(user_id=user_id),
    "user_profile": user_profile,
    "memory_prompt": memory_service.build_memory_prompt(),
}
```

- [ ] **Step 2: Make the agent memory prompt read like a working memory, not a log dump**

```python
parts: list[str] = []
if prefs:
    parts.append("当前会话偏好（仅供参考，优先使用用户最新明确说明）：")
    ...
if lt.get("historical_task_count"):
    parts.append(...)
return "\n".join(parts)
```

- [ ] **Step 3: Add tests for compact short-term output and configurable turn window**

```python
def test_build_session_summary_uses_recent_messages_window(monkeypatch, db_session):
    from app.gwy.services.chat_session_service import ChatSessionService
    from app.gwy.core.config import settings

    monkeypatch.setattr(settings, "RAG_MEMORY_TURNS", 12)
    ...
    assert len(summary) > 0
    assert "用户" in summary or "助手" in summary
```

- [ ] **Step 4: Run the short-term memory tests**

Run: `cd backend && pytest tests/gwy/test_chat_session_service.py tests/gwy/test_agent_memory_service.py -q`
Expected: the working-memory assertions pass and the output stays concise.

### Task 3: Reorganize long-term memory into a stable, updated profile

**Files:**
- Modify: `backend/app/gwy/services/long_term_memory_service.py`
- Modify: `backend/app/gwy/services/agent_memory_service.py`
- Modify: `backend/app/gwy/services/chat_session_service.py`
- Modify: `backend/tests/gwy/test_agent_memory_service.py`
- Modify: `backend/tests/gwy/test_long_term_memory_cache.py`
- Modify: `backend/tests/gwy/test_identity_memory_update.py`

- [ ] **Step 1: Make the long-term context return ordered profile fields with update-friendly semantics**

```python
profile_fields = [
    ("political_status", "政治面貌"),
    ("major", "专业"),
    ("education", "学历"),
    ("degree", "学位"),
    ("is_fresh_graduate", "应届"),
    ("grassroots_experience_years", "基层年限"),
    ("target_regions", "地区偏好"),
    ("desired_departments", "部门偏好"),
    ("desired_positions", "岗位偏好"),
]
```

```python
# The prompt must say the fields are reference-only and updateable.
parts.append("用户基础资料（仅供参考，遇到冲突时以用户最新说明为准）：")
```

- [ ] **Step 2: Ensure cross-session memory is cached in Redis but sourced from PostgreSQL**

```python
summary = {
    "user_profile": user_profile,
    "liked_departments": liked_departments,
    "liked_job_titles": liked_job_titles,
    "total_analyses": total_analyses,
    "total_decisions": total_decisions,
    "last_analysis_at": last_analysis_at,
}
```

- [ ] **Step 3: Keep profile updates incremental instead of write-once**

```python
# When new extracted values differ from current values, update them and bump version.
if profile.major != new_major:
    profile.major = new_major
    profile.version += 1
```

- [ ] **Step 4: Run the long-term memory tests**

Run: `cd backend && pytest tests/gwy/test_long_term_memory_cache.py tests/gwy/test_identity_memory_update.py tests/gwy/test_agent_memory_service.py -q`
Expected: cached summaries still work, profile fields stay ordered, and updates overwrite older values when newer ones arrive.

### Task 4: Unify prompt tone and memory injection across answer flows

**Files:**
- Modify: `backend/app/gwy/prompts/policy_rag.py`
- Modify: `backend/app/gwy/prompts/position_analysis.py`
- Modify: `backend/app/gwy/prompts/study_plan.py`
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/tests/gwy/test_policy_rag_service.py`
- Modify: `backend/tests/gwy/test_study_plan.py`

- [ ] **Step 1: Rewrite the memory block ordering so working memory comes before long-term memory**

```python
lines: list[str] = [
    "以下记忆仅供参考，遇到冲突时以用户最新明确说明为准。",
]
if session_summary:
    lines.append(f"会话摘要：{session_summary}")
if active_topic:
    lines.append(f"当前话题：{active_topic}")
if last_intent:
    lines.append(f"最近意图：{last_intent}")
...
```

- [ ] **Step 2: Replace template-heavy phrasing with a more conversational assistant tone**

```python
system_prompt = """你是一个说话自然、回答直接但不生硬的公务员考试助手。"""
```

- [ ] **Step 3: Add tests that guard against fixed, robotic phrasing**

```python
def test_memory_block_uses_natural_priority_order():
    block = service._build_memory_block(...)
    assert "系统记录" not in block
    assert "您已提供的基础信息" not in block
```

- [ ] **Step 4: Run the prompt and service tests**

Run: `cd backend && pytest tests/gwy/test_policy_rag_service.py tests/gwy/test_study_plan.py tests/gwy/test_position_analysis_agent.py -q`
Expected: memory injection remains stable and the new phrasing does not regress.

### Task 5: Verify the refactor end-to-end

**Files:**
- Modify: none

- [ ] **Step 1: Run the full backend memory-related test set**

Run: `cd backend && pytest tests/gwy/test_agent_memory_service.py tests/gwy/test_chat_session_service.py tests/gwy/test_policy_rag_service.py tests/gwy/test_long_term_memory_cache.py tests/gwy/test_identity_memory_update.py tests/gwy/test_study_plan.py -q`
Expected: all targeted memory tests pass.

- [ ] **Step 2: Run the backend lint/format checks if the touched files are formatted inconsistently**

Run: `cd backend && bash ./scripts/format.sh`
Run: `cd backend && bash ./scripts/lint.sh`
Expected: no formatting or lint regressions in the touched services and prompts.

- [ ] **Step 3: Commit the completed refactor**

```bash
git add backend/app/gwy/services/chat_session_service.py backend/app/gwy/services/agent_memory_service.py backend/app/gwy/services/long_term_memory_service.py backend/app/gwy/services/policy_rag_service.py backend/app/gwy/prompts/policy_rag.py backend/app/gwy/prompts/position_analysis.py backend/app/gwy/prompts/study_plan.py backend/tests/gwy/test_agent_memory_service.py backend/tests/gwy/test_chat_session_service.py backend/tests/gwy/test_policy_rag_service.py backend/tests/gwy/test_long_term_memory_cache.py backend/tests/gwy/test_identity_memory_update.py backend/tests/gwy/test_study_plan.py
git commit -m "feat: refactor layered memory flow"
```
