# ReAct and Plan-and-Solve Agent Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the GwyPilot backend so the project has explicit ReAct and Plan-and-Solve agent capabilities while keeping岗位推荐的规则流稳定可靠.

**Architecture:** Keep `PositionDecisionAgent` as a deterministic rule-and-scoring pipeline. Add a new `RiskReviewAgent` that follows a ReAct loop to identify risks, gather evidence, reflect, and emit structured risk items. Add a new `ReportGeneratorAgent` that follows a Plan-and-Solve loop to create a report outline, generate sections, and run a final consistency review. Extend `PolicyRagService` with a lightweight ReAct-style evidence refinement step so policy answers can perform one more evidence-gathering pass when citations are thin or ambiguous.

**Tech Stack:** Python, FastAPI, SQLModel, PostgreSQL, LangGraph, Milvus, Redis, pytest.

---

### Task 1: Add a ReAct-style risk review agent

**Files:**
- Create: `backend/app/gwy/agents/risk_review_agent.py`
- Modify: `backend/app/gwy/agents/__init__.py`
- Test: `backend/tests/gwy/test_risk_review_agent.py`

- [ ] **Step 1: Write the failing test**

```python
from app.gwy.agents.risk_review_agent import RiskReviewAgent


def test_risk_review_agent_returns_structured_risk_items(db):
    agent = RiskReviewAgent()
    result = agent.run(
        query="请帮我审查这个岗位是否存在风险",
        recommendations=[
            {
                "position_id": "pos-1",
                "job_title": "行政执法岗",
                "remarks": "需基层工作经历2年，面试可能有专业测试",
                "score": 82,
            }
        ],
    )

    assert result["risk_level"] in {"low", "medium", "high"}
    assert result["risk_items"]
    assert result["trace"][0]["step"] == "risk_intent_analysis"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_risk_review_agent.py -v`
Expected: FAIL because the agent module does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class RiskReviewState(TypedDict, total=False):
    query: str
    recommendations: list[dict[str, Any]]
    risk_items: list[dict[str, Any]]
    risk_level: str
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class RiskReviewAgent:
    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(self, *, query: str, recommendations: list[dict[str, Any]]) -> dict[str, Any]:
        state: RiskReviewState = {"query": query, "recommendations": recommendations, "trace": []}
        return self.graph.invoke(state)

    def _build_graph(self):
        builder = StateGraph(RiskReviewState)
        builder.add_node("analyze", self._node_analyze)
        builder.add_node("observe", self._node_observe)
        builder.add_node("reflect", self._node_reflect)
        builder.add_edge(START, "analyze")
        builder.add_edge("analyze", "observe")
        builder.add_edge("observe", "reflect")
        builder.add_edge("reflect", END)
        return builder.compile()

    def _node_analyze(self, state: RiskReviewState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        trace.append({"step": "risk_intent_analysis"})
        return {"trace": trace}

    def _node_observe(self, state: RiskReviewState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        risk_items: list[dict[str, Any]] = []
        for item in state.get("recommendations") or []:
            remarks = str(item.get("remarks") or "")
            if "基层" in remarks or "专业测试" in remarks or "值班" in remarks:
                risk_items.append(
                    {
                        "risk_type": "position_remarks",
                        "risk_level": "medium",
                        "evidence": remarks,
                        "explanation": "岗位备注包含需要人工核验的信息",
                        "suggestion": "继续核对公告原文和备注字段",
                    }
                )
        trace.append({"step": "risk_observation", "risk_count": len(risk_items)})
        return {"risk_items": risk_items, "trace": trace}

    def _node_reflect(self, state: RiskReviewState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        risk_level = "high" if state.get("risk_items") else "low"
        trace.append({"step": "risk_reflection", "risk_level": risk_level})
        return {"risk_level": risk_level, "trace": trace}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_risk_review_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agents/risk_review_agent.py backend/app/gwy/agents/__init__.py backend/tests/gwy/test_risk_review_agent.py
git commit -m "feat: add react-style risk review agent"
```

### Task 2: Add a Plan-and-Solve report generator agent

**Files:**
- Create: `backend/app/gwy/agents/report_generator_agent.py`
- Modify: `backend/app/gwy/agents/__init__.py`
- Test: `backend/tests/gwy/test_report_generator_agent.py`

- [ ] **Step 1: Write the failing test**

```python
from app.gwy.agents.report_generator_agent import ReportGeneratorAgent


def test_report_generator_agent_produces_outline_and_report():
    agent = ReportGeneratorAgent()
    result = agent.run(
        title="岗位推荐报告",
        recommendations=[{"job_title": "信息化岗", "score": 88}],
        risk_summary={"risk_level": "medium", "risk_items": []},
    )

    assert result["outline"]
    assert result["report"]
    assert result["trace"][0]["step"] == "plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_report_generator_agent.py -v`
Expected: FAIL because the agent module does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class ReportState(TypedDict, total=False):
    title: str
    recommendations: list[dict[str, Any]]
    risk_summary: dict[str, Any]
    outline: list[str]
    report: str
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class ReportGeneratorAgent:
    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        *,
        title: str,
        recommendations: list[dict[str, Any]],
        risk_summary: dict[str, Any],
    ) -> dict[str, Any]:
        state: ReportState = {
            "title": title,
            "recommendations": recommendations,
            "risk_summary": risk_summary,
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self):
        builder = StateGraph(ReportState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("solve", self._node_solve)
        builder.add_node("review", self._node_review)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "solve")
        builder.add_edge("solve", "review")
        builder.add_edge("review", END)
        return builder.compile()

    def _node_plan(self, state: ReportState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        outline = ["概要", "推荐岗位", "风险提示", "结论"]
        trace.append({"step": "plan", "outline_count": len(outline)})
        return {"outline": outline, "trace": trace}

    def _node_solve(self, state: ReportState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        report = f"{state.get('title')}\n\n" + "\n".join(
            f"- {item.get('job_title')} (score={item.get('score')})"
            for item in state.get("recommendations") or []
        )
        trace.append({"step": "solve", "report_length": len(report)})
        return {"report": report, "trace": trace}

    def _node_review(self, state: ReportState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        trace.append({"step": "review", "checked": True})
        return {"trace": trace}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_report_generator_agent.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/agents/report_generator_agent.py backend/app/gwy/agents/__init__.py backend/tests/gwy/test_report_generator_agent.py
git commit -m "feat: add plan-and-solve report generator agent"
```

### Task 3: Add a lightweight ReAct evidence refinement step to PolicyRagService

**Files:**
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/app/gwy/prompts/policy_rag.py`
- Test: `backend/tests/gwy/test_policy_rag_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_policy_rag_service_runs_lightweight_react_when_citations_are_sparse():
    service = PolicyRagService(...)
    result = service._node_react_evidence_review(
        {
            "query": "报名确认什么时候开始？",
            "citations": [{"content": "报名确认"}],
            "retrieval_trace": [],
            "use_rerank": True,
        }
    )

    assert result["retrieval_trace"][-1]["step"] == "react_evidence_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_policy_rag_service.py -v`
Expected: FAIL because the node does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def _node_react_evidence_review(self, state: PolicyRagState) -> dict[str, Any]:
    citations = list(state.get("citations") or [])
    trace = list(state.get("retrieval_trace") or [])
    if len(citations) >= 2:
        trace.append({"step": "react_evidence_review", "action": "skip", "reason": "enough_citations"})
        return {"retrieval_trace": trace}

    follow_up_query = f"{state['query']} 补充官方依据"
    vector_results = self.milvus_store.search(
        query_vector=self.embedding_service.embed_text(follow_up_query),
        filter_expr=state["metadata_filter"],
        top_k=max(state["top_k"], 8),
    )
    refined = self.rerank_service.rerank(
        query=follow_up_query,
        documents=vector_results,
        top_n=min(state["top_k"], 6),
    )
    trace.append(
        {
            "step": "react_evidence_review",
            "action": "refined_retrieval",
            "follow_up_query": follow_up_query,
            "result_count": len(refined),
        }
    )
    return {
        "fused_results": list(state.get("fused_results") or []),
        "rerank_results": refined,
        "citations": citations or self._build_citations(refined),
        "retrieval_trace": trace,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy/test_policy_rag_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/policy_rag_service.py backend/app/gwy/prompts/policy_rag.py backend/tests/gwy/test_policy_rag_service.py
git commit -m "feat: add lightweight react evidence review"
```

### Task 4: Wire the new agents into the existing recommendation flow

**Files:**
- Modify: `backend/app/gwy/services/policy_rag_service.py`
- Modify: `backend/app/api/routes/gwy.py`
- Modify: `backend/app/gwy/models.py`
- Test: `backend/tests/api/routes/test_gwy.py`

- [ ] **Step 1: Write the failing test**

```python
def test_position_recommendation_returns_risk_review_and_report(client, monkeypatch):
    ...
    assert payload["risk_review"]["risk_level"]
    assert payload["report"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/api/routes/test_gwy.py -v`
Expected: FAIL because response payload does not yet include the new fields.

- [ ] **Step 3: Write minimal implementation**

```python
result["risk_review"] = risk_review_result
result["report"] = report_result["report"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/api/routes/test_gwy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/gwy/services/policy_rag_service.py backend/app/api/routes/gwy.py backend/app/gwy/models.py backend/tests/api/routes/test_gwy.py
git commit -m "feat: wire agentic risk review and reporting"
```

### Task 5: Run the focused backend test suite

**Files:**
- No code changes

- [ ] **Step 1: Run the agent and API tests**

Run: `E:\\GwyPilot\\GwyPilot\\.venv\\Scripts\\python.exe -m pytest backend/tests/gwy backend/tests/api/routes/test_gwy.py -q`
Expected: all targeted tests pass.

- [ ] **Step 2: Fix any failures**

If anything fails, update the relevant agent or API file and rerun the same test command until green.

- [ ] **Step 3: Commit verification state**

```bash
git add -A
git commit -m "test: verify agentic workflow upgrade"
```
