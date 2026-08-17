from __future__ import annotations

from collections import Counter
from typing import Any


class PositionDecisionMatrixService:
    """Turn position facts into conservative, comparable decision items."""

    def build(
        self,
        *,
        recommendations: list[dict[str, Any]],
        research: list[dict[str, Any]],
        risk_review: dict[str, Any],
        profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        research_by_id = {
            str(item.get("position_id") or item.get("id") or ""): item
            for item in research
        }
        risks_by_id: dict[str, list[dict[str, Any]]] = {}
        for risk in risk_review.get("risk_items") or []:
            position_id = str(risk.get("position_id") or "")
            if position_id:
                risks_by_id.setdefault(position_id, []).append(risk)

        items: list[dict[str, Any]] = []
        missing: list[str] = []
        for recommendation in recommendations:
            position_id = str(
                recommendation.get("position_id")
                or recommendation.get("id")
                or ""
            )
            research_item = research_by_id.get(position_id, {})
            risks = self._merge_risks(
                recommendation.get("risks") or [],
                risks_by_id.get(position_id, []),
            )
            item = self._build_item(
                recommendation=recommendation,
                research=research_item,
                risks=risks,
                profile=profile or {},
            )
            items.append(item)
            missing.extend(item["unknowns"])

        tier_summary = dict(Counter(item["tier"] for item in items))
        missing = self._unique(missing)
        next_actions = self._unique(
            task
            for item in items
            for task in item["verification_tasks"]
        )
        confidence = self._overall_confidence(items)
        return {
            "items": items,
            "tier_summary": tier_summary,
            "missing": missing,
            "confidence": confidence,
            "next_actions": next_actions,
        }

    def _build_item(
        self,
        *,
        recommendation: dict[str, Any],
        research: dict[str, Any],
        risks: list[dict[str, Any]],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        hard_passed = recommendation.get("hard_filter_passed")
        if hard_passed is None:
            hard_passed = not bool(recommendation.get("hard_filter_reasons"))
        reasons = self._texts(recommendation.get("reasons"))
        hard_reasons = self._texts(recommendation.get("hard_filter_reasons"))
        reasons = self._unique([*hard_reasons, *reasons])
        unknowns: list[str] = []
        verification_tasks: list[str] = []
        history = dict(research.get("history") or {})
        summary = dict(history.get("summary") or {})
        records = list(history.get("records") or research.get("history_records") or [])

        if not hard_passed:
            tier = "exclude"
            fit_score = 0
            confidence = "high"
        else:
            fit_score = self._fit_score(recommendation, profile)
            competition = self._competition_level(summary, records)
            if competition == "unknown":
                unknowns.append("competition")
                verification_tasks.append("查阅该岗位近三年官方招录与进面数据")
            preparation_cost = self._preparation_cost(recommendation, risks)
            tier = self._tier(
                fit_score=fit_score,
                competition=competition,
                preparation_cost=preparation_cost,
                risk_count=len(risks),
            )
            confidence = "low" if unknowns else ("medium" if risks else "high")

        for risk in risks:
            task = str(
                risk.get("verification_task")
                or risk.get("suggestion")
                or risk.get("text")
                or "核对官方公告中的岗位限制"
            ).strip()
            if task:
                verification_tasks.append(task)

        unknowns = self._unique(unknowns)
        verification_tasks = self._unique(verification_tasks)
        label = " / ".join(
            str(recommendation.get(key) or "").strip()
            for key in ("department_name", "office_name", "job_title")
            if str(recommendation.get(key) or "").strip()
        ) or "unknown position"
        return {
            "position_id": str(
                recommendation.get("position_id")
                or recommendation.get("id")
                or ""
            ),
            "label": label,
            "tier": tier,
            "fit_score": fit_score,
            "competition_level": self._competition_level(summary, records)
            if hard_passed
            else "not_applicable",
            "preparation_cost": self._preparation_cost(recommendation, risks)
            if hard_passed
            else "not_applicable",
            "confidence": confidence,
            "reasons": reasons,
            "risks": risks,
            "unknowns": unknowns,
            "verification_tasks": verification_tasks,
            "decision_change_rules": self._decision_change_rules(unknowns, risks),
        }

    def _fit_score(self, recommendation: dict[str, Any], profile: dict[str, Any]) -> int:
        try:
            score = float(recommendation.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score <= 1:
            score *= 100
        return max(0, min(100, round(score)))

    def _competition_level(
        self,
        summary: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> str:
        ratio = summary.get("latest_interview_ratio")
        if ratio in (None, ""):
            ratio = next(
                (record.get("interview_ratio") for record in records if record.get("interview_ratio") not in (None, "")),
                None,
            )
        try:
            value = float(ratio)
        except (TypeError, ValueError):
            return "unknown"
        if value >= 50:
            return "high"
        if value >= 15:
            return "medium"
        return "low"

    def _preparation_cost(
        self,
        recommendation: dict[str, Any],
        risks: list[dict[str, Any]],
    ) -> str:
        text = " ".join(
            str(recommendation.get(key) or "")
            for key in ("remarks", "job_title", "major_requirement")
        )
        costly_types = {"professional_test", "service_year_limit", "shift_limit", "travel_limit"}
        if any(str(risk.get("risk_type") or "") in costly_types for risk in risks):
            return "high"
        if any(token in text for token in ("专业测试", "基层", "值班", "出差")):
            return "high"
        return "medium" if recommendation.get("need_manual_confirm") else "low"

    def _tier(
        self,
        *,
        fit_score: int,
        competition: str,
        preparation_cost: str,
        risk_count: int,
    ) -> str:
        if fit_score < 60:
            return "caution"
        if fit_score >= 85 and competition == "high":
            return "sprint"
        if competition == "high" or risk_count >= 3:
            return "caution"
        if competition == "low" and fit_score >= 80:
            return "backup"
        if fit_score >= 85 and competition in {"medium", "unknown"}:
            return "primary"
        if fit_score >= 70 and preparation_cost != "high":
            return "primary"
        return "backup"

    def _decision_change_rules(
        self,
        unknowns: list[str],
        risks: list[dict[str, Any]],
    ) -> list[str]:
        rules = []
        if "competition" in unknowns:
            rules.append("若官方历史竞争数据明显偏高，则由主攻降为谨慎")
        if risks:
            rules.append("若公告确认隐性条件不满足，则排除该岗位")
        return rules

    def _merge_risks(self, raw: Any, reviewed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        values = [item if isinstance(item, dict) else {"text": str(item)} for item in raw if item]
        values.extend(item for item in reviewed if isinstance(item, dict))
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in values:
            key = (str(item.get("risk_type") or "generic"), str(item.get("text") or item.get("explanation") or item.get("evidence") or "").strip())
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _texts(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return self._unique(
            str(
                item.get("text") or item.get("explanation") or item
                if isinstance(item, dict)
                else item
            ).strip()
            for item in values
            if item
        )

    def _overall_confidence(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return "unknown"
        levels = {item["confidence"] for item in items}
        if "low" in levels:
            return "low"
        if "medium" in levels:
            return "medium"
        return "high"

    def _unique(self, values: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result
