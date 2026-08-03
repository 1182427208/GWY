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
            return self._plan_from_payload(request, payload)
        except Exception as exc:
            return self._fallback_plan(request, error=str(exc))

    @staticmethod
    def _parse_response(response: str) -> dict[str, Any]:
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned).strip()
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("planner response must be a JSON object")
        return payload

    def _plan_from_payload(
        self, request: SearchQueryRequest, payload: dict[str, Any]
    ) -> SearchQueryPlan:
        primary = self._text(payload.get("primary_query"))
        candidates = self._texts(payload.get("planned_queries"))
        if not primary or not candidates:
            raise ValueError("planner response is missing query candidates")
        candidates = self._unique([primary, *candidates])[: self._limit(request)]
        search_kind = self._valid_search_kind(payload.get("search_kind"), request.search_kind)
        sources = self._texts(payload.get("required_source_kinds"))
        if not sources:
            sources = self._default_sources(search_kind)
        trace = [{"strategy": "llm", "search_kind": search_kind}]
        if payload.get("trace_notes"):
            trace[0]["notes"] = str(payload["trace_notes"])
        return SearchQueryPlan(
            original_query=request.query,
            primary_query=candidates[0],
            planned_queries=candidates,
            required_source_kinds=sources,
            search_kind=search_kind,
            trace=trace,
        )

    def _fallback_plan(
        self, request: SearchQueryRequest, *, error: str
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
        candidates = [request.query.strip(), base]
        if request.search_kind == "web":
            candidates.extend(
                [
                    f"{base} 官方公告",
                    f"{base} site:gov.cn 招考简章",
                    f"{base} 面试名单 进面分",
                ]
            )
        elif request.search_kind == "policy":
            candidates.append(f"{base} 官方政策")
        else:
            candidates.append(base)
        candidates = self._unique([*request.planned_queries, *candidates])[: self._limit(request)]
        return SearchQueryPlan(
            original_query=request.query,
            primary_query=candidates[0] if candidates else request.query,
            planned_queries=candidates or [request.query],
            required_source_kinds=self._default_sources(request.search_kind),
            search_kind=request.search_kind,
            trace=[{"strategy": "fallback_rules", "error": error}],
        )

    @staticmethod
    def _limit(request: SearchQueryRequest) -> int:
        return max(1, min(request.max_queries, 5))

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
