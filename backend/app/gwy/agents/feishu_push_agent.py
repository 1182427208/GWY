from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from app.core.config import settings


class FeishuPushState(TypedDict, total=False):
    report_kind: str
    title: str
    report_text: str
    task_id: str | None
    report_url: str | None
    webhook_url: str | None
    frontend_host: str | None
    payload: dict[str, Any]
    response_json: dict[str, Any]
    status: str
    error_message: str | None
    trace: list[dict[str, Any]]


@dataclass(slots=True)
class FeishuPushAgent:
    webhook_url: str | None = None
    frontend_host: str | None = None
    timeout: float = 10.0
    http_client: Any | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = self._build_graph()

    def run(
        self,
        *,
        report_kind: str,
        title: str,
        report_text: str,
        task_id: str | None = None,
        report_url: str | None = None,
        webhook_url: str | None = None,
    ) -> dict[str, Any]:
        resolved_webhook_url = (
            webhook_url
            or self.webhook_url
            or str(getattr(settings, "FEISHU_WEBHOOK_URL", "") or "").strip()
            or None
        )
        state: FeishuPushState = {
            "report_kind": report_kind,
            "title": title,
            "report_text": report_text,
            "task_id": task_id,
            "report_url": report_url,
            "webhook_url": resolved_webhook_url,
            "frontend_host": self.frontend_host or settings.FRONTEND_HOST,
            "trace": [],
        }
        return self.graph.invoke(state)

    def _build_graph(self) -> Any:
        builder = StateGraph(FeishuPushState)
        builder.add_node("plan", self._node_plan)
        builder.add_node("push", self._node_push)
        builder.add_node("reflect", self._node_reflect)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "push")
        builder.add_edge("push", "reflect")
        builder.add_edge("reflect", END)
        return builder.compile()

    def _node_plan(self, state: FeishuPushState) -> dict[str, Any]:
        webhook_url = str(state.get("webhook_url") or "").strip()
        report_text = str(state.get("report_text") or "").strip()
        title = str(state.get("title") or "GwyPilot 报告").strip()
        report_kind = str(state.get("report_kind") or "report").strip()
        trace = list(state.get("trace") or [])

        if not webhook_url:
            trace.append(
                {
                    "step": "plan",
                    "status": "skipped",
                    "reason": "webhook_missing",
                }
            )
            return {
                "status": "skipped",
                "error_message": "Feishu webhook is not configured.",
                "trace": trace,
            }

        card = self._build_card(
            title=title,
            report_kind=report_kind,
            report_text=report_text,
            task_id=state.get("task_id"),
            report_url=str(state.get("report_url") or "").strip() or None,
            frontend_host=str(state.get("frontend_host") or "").strip() or None,
        )
        payload = {
            "msg_type": "interactive",
            "card": json.dumps(card, ensure_ascii=False),
        }
        trace.append(
            {
                "step": "plan",
                "status": "done",
                "title": title,
                "report_kind": report_kind,
                "summary_length": len(self._build_summary_lines(report_text)),
            }
        )
        return {"payload": payload, "status": "planned", "trace": trace}

    def _node_push(self, state: FeishuPushState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        if str(state.get("status") or "") == "skipped":
            trace.append(
                {
                    "step": "push",
                    "status": "skipped",
                    "reason": str(state.get("error_message") or "webhook_missing"),
                }
            )
            return {"trace": trace, "status": "skipped", "error_message": state.get("error_message")}

        webhook_url = str(state.get("webhook_url") or "").strip()
        payload = dict(state.get("payload") or {})
        if not webhook_url or not payload:
            trace.append(
                {
                    "step": "push",
                    "status": "failed",
                    "reason": "payload_not_ready",
                }
            )
            return {
                "status": "failed",
                "error_message": "Feishu payload is not ready.",
                "trace": trace,
            }

        try:
            response = self._post_json(webhook_url, payload)
            response.raise_for_status()
            response_json = self._read_response_json(response)
            trace.append(
                {
                    "step": "push",
                    "status": "done",
                    "http_status": getattr(response, "status_code", None),
                }
            )
            return {
                "response_json": response_json,
                "status": "pushed",
                "trace": trace,
            }
        except Exception as exc:  # pragma: no cover - defensive network handling
            trace.append(
                {
                    "step": "push",
                    "status": "failed",
                    "error": str(exc),
                }
            )
            return {
                "status": "failed",
                "error_message": str(exc),
                "trace": trace,
            }

    def _node_reflect(self, state: FeishuPushState) -> dict[str, Any]:
        trace = list(state.get("trace") or [])
        status = str(state.get("status") or "failed")
        response_json = dict(state.get("response_json") or {})
        error_message = state.get("error_message")

        if status == "planned":
            status = "failed"

        if status == "pushed":
            if self._response_indicates_success(response_json):
                status = "sent"
            else:
                status = "failed"
                error_message = (
                    error_message
                    or f"Feishu webhook returned unexpected payload: {response_json}"
                )
        elif status == "skipped":
            error_message = error_message or "Feishu webhook is not configured."

        trace.append(
            {
                "step": "reflect",
                "status": status,
                "has_response": bool(response_json),
            }
        )
        return {
            "status": status,
            "error_message": error_message,
            "response_json": response_json,
            "trace": trace,
        }

    def _build_card(
        self,
        *,
        title: str,
        report_kind: str,
        report_text: str,
        task_id: str | None,
        report_url: str | None,
        frontend_host: str | None,
    ) -> dict[str, Any]:
        summary_lines = self._build_summary_lines(report_text)
        summary_md = "\n".join(f"- {line}" for line in summary_lines)
        if not summary_md:
            summary_md = "- 报告已生成，但没有可提炼的摘要。"

        action_url = report_url or frontend_host
        elements: list[dict[str, Any]] = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**报告类型**：{self._report_kind_label(report_kind)}\n"
                        f"**任务 ID**：`{task_id or 'unknown'}`"
                    ),
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**摘要**\n{summary_md}",
                },
            },
        ]
        if action_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "打开系统查看详情",
                            },
                            "type": "primary",
                            "url": action_url,
                        }
                    ],
                }
            )
        return {
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title,
                },
                "template": "blue",
            },
            "elements": elements,
        }

    def _build_summary_lines(self, report_text: str) -> list[str]:
        lines: list[str] = []
        for raw_line in report_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                line = line.lstrip("#").strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if not line:
                continue
            lines.append(line)
            if len(lines) >= 4:
                break
        return lines

    def _report_kind_label(self, report_kind: str) -> str:
        mapping = {
            "analysis": "岗位分析报告",
            "recommendation": "岗位推荐报告",
        }
        return mapping.get(report_kind, report_kind or "报告")

    def _response_indicates_success(self, response_json: dict[str, Any]) -> bool:
        if not response_json:
            return True
        if response_json.get("code") == 0:
            return True
        if response_json.get("StatusCode") == 0:
            return True
        if response_json.get("errcode") == 0:
            return True
        if str(response_json.get("msg") or "").lower() in {"ok", "success"}:
            return True
        return False

    def _post_json(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        if self.http_client is not None:
            return self.http_client.post(url, json=payload, timeout=self.timeout)
        with httpx.Client(timeout=self.timeout) as client:
            return client.post(url, json=payload)

    def _read_response_json(self, response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            return {}
        if isinstance(payload, dict):
            return payload
        return {}
