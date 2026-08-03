from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.gwy.llm.chat_service import ChatService
from app.gwy.prompts.search_query_planner import (
    SEARCH_QUERY_PLANNER_SYSTEM_PROMPT,
    SEARCH_QUERY_PLANNER_USER_PROMPT_TEMPLATE,
)


@dataclass(slots=True)
class SearchQueryRequest:
    query: str
    search_kind: str
    position: dict[str, Any] | None = None
    planned_queries: list[str] = field(default_factory=list)
    max_queries: int = 5


@dataclass(slots=True)
class SearchQueryPlan:
    original_query: str
    primary_query: str
    planned_queries: list[str]
    required_source_kinds: list[str]
    search_kind: str
    trace: list[dict[str, Any]] = field(default_factory=list)


class SearchQueryPlannerService:
    def __init__(self, *, chat_service: ChatService | None = None) -> None:
        self.chat_service = chat_service or ChatService()

    def plan(self, request: SearchQueryRequest) -> SearchQueryPlan:
        trace: list[dict[str, Any]] = []
        self._trace_started(request, trace)
        try:
            response = self.chat_service.chat_completion(
                [
                    {"role": "system", "content": SEARCH_QUERY_PLANNER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": SEARCH_QUERY_PLANNER_USER_PROMPT_TEMPLATE.format(
                            query=request.query,
                            search_kind=request.search_kind,
                            position=json.dumps(
                                request.position or {},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            planned_queries=json.dumps(
                                request.planned_queries,
                                ensure_ascii=False,
                            ),
                        ),
                    },
                ],
                temperature=0.0,
            )
            payload = self._parse_response(response)
            return self._plan_from_payload(request, payload, trace=trace)
        except Exception as exc:
            return self._fallback_plan(request, error=str(exc), trace=trace)

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError("planner response must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("planner response must be a JSON object")
        return payload

    def _plan_from_payload(
        self,
        request: SearchQueryRequest,
        payload: dict[str, Any],
        *,
        trace: list[dict[str, Any]],
    ) -> SearchQueryPlan:
        primary = self._text(payload.get("primary_query"))
        candidates = self._texts(payload.get("planned_queries"))
        if not primary or not candidates:
            raise ValueError("planner response is missing query candidates")

        search_kind = self._valid_search_kind(payload.get("search_kind"), request.search_kind)
        sources = self._texts(payload.get("required_source_kinds")) or self._default_sources(
            search_kind
        )
        candidates = self._normalize_candidates(
            [primary, *candidates, request.query],
            request,
            keep_original_first=False,
        )

        self._trace_rewritten(
            trace,
            request=request,
            payload=payload,
            search_kind=search_kind,
            sources=sources,
            candidates=candidates,
        )
        self._trace_finalized(
            trace,
            request=request,
            strategy="llm",
            search_kind=search_kind,
            sources=sources,
            candidates=candidates,
        )
        return SearchQueryPlan(
            original_query=request.query,
            primary_query=candidates[0],
            planned_queries=candidates,
            required_source_kinds=sources,
            search_kind=search_kind,
            trace=list(trace),
        )

    def _fallback_plan(
        self,
        request: SearchQueryRequest,
        *,
        error: str,
        trace: list[dict[str, Any]],
    ) -> SearchQueryPlan:
        position = request.position or {}
        context = self._unique(
            [
                self._text(position.get("position_code")),
                self._text(position.get("department_name")),
                self._text(position.get("job_title")),
            ]
        )
        base = " ".join([*context, request.query]).strip()
        candidates = [request.query.strip(), *request.planned_queries, base]
        if request.search_kind == "web":
            candidates.extend(
                [
                    f"{base} official announcement",
                    f"{base} site:gov.cn 招考简章",
                    f"{base} 面试名单 进面分",
                ]
            )
        elif request.search_kind == "policy":
            candidates.append(f"{base} official policy")
        else:
            candidates.append(base)

        candidates = self._normalize_candidates(
            candidates,
            request,
            keep_original_first=True,
        )
        self._trace_rewrite_failed(trace, error=error, request=request)
        self._trace_finalized(
            trace,
            request=request,
            strategy="fallback_rules",
            search_kind=request.search_kind,
            sources=self._default_sources(request.search_kind),
            candidates=candidates,
        )
        return SearchQueryPlan(
            original_query=request.query,
            primary_query=candidates[0],
            planned_queries=candidates,
            required_source_kinds=self._default_sources(request.search_kind),
            search_kind=request.search_kind,
            trace=list(trace),
        )

    def _normalize_candidates(
        self,
        candidates: list[str],
        request: SearchQueryRequest,
        *,
        keep_original_first: bool,
    ) -> list[str]:
        limit = self._limit(request)
        normalized = self._unique([self._text(item) for item in candidates if self._text(item)])
        original = self._text(request.query)
        if original and keep_original_first and original not in normalized:
            normalized.insert(0, original)
        elif original and keep_original_first:
            normalized = [original, *[item for item in normalized if item != original]]
        elif original and original not in normalized:
            normalized.append(original)
        return normalized[:limit]

    @staticmethod
    def _limit(request: SearchQueryRequest) -> int:
        return max(1, min(int(request.max_queries or 1), 5))

    @staticmethod
    def _text(value: Any) -> str:
        return value.strip() if isinstance(value, str) and value.strip() else ""

    @classmethod
    def _texts(cls, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [text for value in values if (text := cls._text(value))]

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

    @staticmethod
    def _valid_search_kind(value: Any, fallback: str) -> str:
        return value if value in {"web", "policy", "position"} else fallback

    @staticmethod
    def _default_sources(search_kind: str) -> list[str]:
        defaults = {
            "web": ["official"],
            "policy": ["official", "policy"],
            "position": ["position_database"],
        }
        return defaults.get(search_kind, ["official"])

    @staticmethod
    def _recommended_tool(search_kind: str) -> str:
        mapping = {
            "web": "web_search",
            "policy": "search_policy_knowledge",
            "position": "search_positions_pg",
        }
        return mapping.get(search_kind, "web_search")

    def _trace_started(self, request: SearchQueryRequest, trace: list[dict[str, Any]]) -> None:
        trace.append(
            {
                "step": "search_query_planning_started",
                "status": "done",
                "tool": "SearchQueryPlannerService.plan",
                "input": {
                    "original_query": request.query,
                    "search_kind": request.search_kind,
                    "planned_queries": list(request.planned_queries),
                    "max_queries": request.max_queries,
                    "position": request.position or {},
                },
            }
        )

    def _trace_rewritten(
        self,
        trace: list[dict[str, Any]],
        *,
        request: SearchQueryRequest,
        payload: dict[str, Any],
        search_kind: str,
        sources: list[str],
        candidates: list[str],
    ) -> None:
        output = {
            "original_query": request.query,
            "primary_query": candidates[0] if candidates else "",
            "planned_queries": list(candidates),
            "required_source_kinds": list(sources),
            "search_kind": search_kind,
            "rewrite_source": "llm",
        }
        if payload.get("trace_notes"):
            output["notes"] = str(payload["trace_notes"])
        trace.append(
            {
                "step": "search_query_rewritten",
                "status": "done",
                "tool": "ChatService.chat_completion",
                "backend": "LLM",
                "output": output,
            }
        )

    def _trace_rewrite_failed(
        self,
        trace: list[dict[str, Any]],
        *,
        request: SearchQueryRequest,
        error: str,
    ) -> None:
        trace.append(
            {
                "step": "search_query_rewrite_failed",
                "status": "done",
                "tool": "ChatService.chat_completion",
                "error": error,
                "input": {
                    "original_query": request.query,
                    "search_kind": request.search_kind,
                },
            }
        )

    def _trace_finalized(
        self,
        trace: list[dict[str, Any]],
        *,
        request: SearchQueryRequest,
        strategy: str,
        search_kind: str,
        sources: list[str],
        candidates: list[str],
    ) -> None:
        trace.append(
            {
                "step": "search_query_finalized",
                "status": "done",
                "tool": self._recommended_tool(search_kind),
                "output": {
                    "original_query": request.query,
                    "primary_query": candidates[0] if candidates else request.query,
                    "planned_queries": list(candidates),
                    "required_source_kinds": list(sources),
                    "search_kind": search_kind,
                    "strategy": strategy,
                },
            }
        )
