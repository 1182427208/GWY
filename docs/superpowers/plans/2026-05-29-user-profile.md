# User Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a simple editable user profile so the position recommendation flow can reliably read stable user inputs like education, major, political status, region preference, and study time.

**Architecture:** Reuse the existing `GwyUserProfile` SQLModel as the single source of truth. Add a small Gwy-specific API for reading and updating the current user's profile, then surface it in the existing settings page with a compact form. Recommendation logic already knows how to consume a profile object, so the API should return the same shape that the agent expects.

**Tech Stack:** FastAPI, SQLModel, React, TypeScript, React Hook Form, Zod, existing `gwy` services and generated frontend request helpers.

---

### Task 1: Add profile API endpoints on the backend

**Files:**
- Modify: `backend/app/api/routes/gwy.py`
- Modify: `backend/app/gwy/models.py` if response helpers need a reusable shape
- Test: `backend/tests/api/routes/test_gwy_profile_api.py` (new)

- [ ] **Step 1: Write the failing test**

```python
def test_profile_api_returns_current_user_profile(client, normal_user_token_headers):
    response = client.get("/api/v1/gwy/profile/me", headers=normal_user_token_headers)
    assert response.status_code == 200
    assert response.json()["education"] is None

def test_profile_api_updates_profile(client, normal_user_token_headers):
    response = client.put(
        "/api/v1/gwy/profile/me",
        headers=normal_user_token_headers,
        json={
            "education": "本科",
            "degree": "学士",
            "major": "法学",
            "political_status": "中共党员",
            "is_fresh_graduate": False,
            "grassroots_experience_years": 0,
            "target_regions": ["北京"],
            "desired_departments": ["税务系统"],
            "desired_positions": ["综合管理"],
            "excluded_positions": ["基层岗位"],
            "daily_study_hours": 3,
            "notes": "优先北京",
        },
    )
    assert response.status_code == 200
    assert response.json()["major"] == "法学"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\Anaconda3\\envs\\CareerFlow\\python.exe -m pytest backend/tests/api/routes/test_gwy_profile_api.py -q`
Expected: fail because `/gwy/profile/me` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
@router.get("/profile/me")
def get_my_profile(...):
    ...

@router.put("/profile/me")
def update_my_profile(...):
    ...
```

Implementation details:
- Load or create `GwyUserProfile` for the current user.
- Accept the existing profile fields.
- Return a serialized payload the frontend can bind directly.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\Anaconda3\\envs\\CareerFlow\\python.exe -m pytest backend/tests/api/routes/test_gwy_profile_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/gwy.py backend/tests/api/routes/test_gwy_profile_api.py
git commit -m "feat: add user profile api"
```

### Task 2: Replace the generic account settings tab with a Gwy profile editor

**Files:**
- Modify: `frontend/src/routes/_layout/settings.tsx`
- Modify: `frontend/src/components/UserSettings/UserInformation.tsx` or create a new Gwy-specific component under `frontend/src/components/UserSettings/`
- Test: frontend lint

- [ ] **Step 1: Write the failing UI state**

No automated UI test is required here; the failure is that the settings page only edits name/email and has no Gwy profile fields.

- [ ] **Step 2: Run lint to verify no profile form exists yet**

Run: `npm run lint --prefix frontend`
Expected: passes, but the UI still lacks Gwy profile fields.

- [ ] **Step 3: Write minimal implementation**

```tsx
const formSchema = z.object({
  education: z.string().optional(),
  degree: z.string().optional(),
  major: z.string().optional(),
  political_status: z.string().optional(),
  is_fresh_graduate: z.boolean().default(false),
  grassroots_experience_years: z.number().int().nonnegative().optional(),
  target_regions: z.array(z.string()).default([]),
  desired_departments: z.array(z.string()).default([]),
  desired_positions: z.array(z.string()).default([]),
  excluded_positions: z.array(z.string()).default([]),
  daily_study_hours: z.number().int().nonnegative().optional(),
  notes: z.string().optional(),
})
```

Implementation details:
- Keep the page compact.
- Reuse the existing settings layout.
- Add a save button and a reset button.

- [ ] **Step 4: Run lint to verify it passes**

Run: `npm run lint --prefix frontend`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/_layout/settings.tsx frontend/src/components/UserSettings/UserInformation.tsx
git commit -m "feat: add user profile editor"
```

### Task 3: Feed the saved profile into recommendation flow

**Files:**
- Modify: `backend/app/gwy/agents/position_decision_agent.py`
- Modify: `backend/app/gwy/services/policy_rag_service.py` if profile serialization needs to be passed through chat recommendation
- Test: `backend/tests/gwy/test_position_decision_agent.py`

- [ ] **Step 1: Write the failing test**

```python
def test_position_decision_agent_uses_saved_profile(db):
    # create GwyUserProfile for the test user
    # run the agent with user_id only
    # assert the extracted criteria uses the saved major/education/region
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\Anaconda3\\envs\\CareerFlow\\python.exe -m pytest backend/tests/gwy/test_position_decision_agent.py -q`
Expected: fail until the saved profile is correctly loaded/serialized.

- [ ] **Step 3: Write minimal implementation**

```python
profile = self._load_profile(UUID(state["user_id"]))
criteria = extract_position_recommendation_criteria(state["query"], profile)
```

Also ensure the chat route passes through `position_profile` overrides only when the user explicitly supplies them.

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\Anaconda3\\envs\\CareerFlow\\python.exe -m pytest backend/tests/gwy/test_position_decision_agent.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agents/position_decision_agent.py backend/app/gwy/services/policy_rag_service.py backend/tests/gwy/test_position_decision_agent.py
git commit -m "feat: use saved user profile in recommendations"
```

---

**Coverage check:** This plan covers profile CRUD, the UI entry point, and recommendation consumption. It intentionally does not add chat-based profile auto-extraction yet, because that can be a follow-up once the manual profile loop is stable.
