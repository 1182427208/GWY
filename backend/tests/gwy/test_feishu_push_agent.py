from __future__ import annotations

from types import SimpleNamespace

from app.gwy.agents.feishu_push_agent import FeishuPushAgent


class FakeFeishuResponse:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.status_code = 200
        self._payload = payload or {"code": 0, "msg": "ok"}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class FakeFeishuClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, json: dict[str, object], timeout: float) -> FakeFeishuResponse:  # noqa: A002
        self.calls.append(
            {
                "url": url,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeFeishuResponse()


def test_feishu_push_agent_sends_interactive_card() -> None:
    client = FakeFeishuClient()
    agent = FeishuPushAgent(
        webhook_url="https://open.feishu.cn/webhook/test",
        http_client=client,
    )

    result = agent.run(
        report_kind="analysis",
        title="岗位分析报告",
        report_text=(
            "# 岗位分析报告\n\n"
            "## 概览\n"
            "- 推荐岗位数：3\n"
            "- 风险等级：medium\n"
        ),
        task_id="task-123",
    )

    assert result["status"] == "sent"
    assert result["trace"][0]["step"] == "plan"
    assert result["trace"][1]["step"] == "push"
    assert result["trace"][2]["step"] == "reflect"
    assert len(client.calls) == 1

    payload = client.calls[0]["json"]
    assert payload["msg_type"] == "interactive"
    assert "岗位分析报告" in str(payload["card"])
    assert "推荐岗位数：3" in str(payload["card"])


def test_feishu_push_agent_skips_without_webhook() -> None:
    client = FakeFeishuClient()
    agent = FeishuPushAgent(http_client=client)

    result = agent.run(
        report_kind="recommendation",
        title="岗位推荐报告",
        report_text="简单报告内容",
        task_id="task-456",
    )

    assert result["status"] == "skipped"
    assert result["trace"][-1]["step"] == "reflect"
    assert client.calls == []
