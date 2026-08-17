from __future__ import annotations

from collections import Counter
from typing import Any


class ReportQualityService:
    REQUIRED_MARKERS = {
        "tier": ("tier", "分层", "冲刺", "主攻", "保底"),
        "comparison": ("comparison", "比较", "对比", "优于", "更适合"),
        "action": ("verification", "核验", "核查", "下一步", "行动"),
        "conclusion": ("conclusion", "结论", "建议"),
    }

    def validate(
        self,
        *,
        report: str,
        decision_matrix: dict[str, Any],
        risk_review: dict[str, Any],
    ) -> dict[str, Any]:
        text = str(report or "").lower()
        missing = [
            key
            for key, markers in self.REQUIRED_MARKERS.items()
            if not any(marker.lower() in text for marker in markers)
        ]
        items = list(decision_matrix.get("items") or [])
        if items and not any(
            str(item.get("tier") or "").lower() in text
            or str(item.get("label") or "").lower() in text
            for item in items
        ):
            missing.append("position_decisions")
        duplicate_risks = self._duplicate_risks(risk_review)
        if duplicate_risks:
            missing.append("deduplicated_risks")
        missing = list(dict.fromkeys(missing))
        return {
            "passed": not missing,
            "missing_requirements": missing,
            "duplicate_risks": duplicate_risks,
            "next_actions": [
                "补充岗位分层和直接选岗结论" if "tier" in missing else "",
                "补充岗位横向比较" if "comparison" in missing else "",
                "补充具体核验材料和下一步动作" if "action" in missing else "",
            ],
        }

    def _duplicate_risks(self, risk_review: dict[str, Any]) -> list[str]:
        keys = [
            str(item.get("risk_type") or item.get("text") or "").strip()
            for item in risk_review.get("risk_items") or []
            if isinstance(item, dict)
        ]
        return [key for key, count in Counter(keys).items() if key and count > 1]
