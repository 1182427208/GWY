from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.request = SimpleNamespace(method="GET", url="http://example.test")

    def json(self) -> dict[str, object]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RecordingHttpClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeHttpResponse:
        self.requests.append({"method": "POST", "url": url, **kwargs})
        if url.endswith("/files"):
            return FakeHttpResponse({"data": {"id": "file-123", "purpose": "batch"}})
        if url.endswith("/batches"):
            return FakeHttpResponse({"data": {"id": "batch-456", "status": "in_progress"}})
        return FakeHttpResponse({"data": {}})

    def get(self, url: str, **kwargs: object) -> FakeHttpResponse:
        self.requests.append({"method": "GET", "url": url, **kwargs})
        if url.endswith("/files"):
            return FakeHttpResponse({"data": {"data": [{"id": "file-123"}], "object": "list"}})
        if "/batches/" in url:
            return FakeHttpResponse({"data": {"id": "batch-456", "status": "completed"}})
        if url.endswith("/batches"):
            return FakeHttpResponse({"data": {"data": [{"id": "batch-456"}], "object": "list"}})
        return FakeHttpResponse({"data": {}})


def test_siliconflow_client_uploads_and_lists_files(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello", encoding="utf-8")
    http_client = RecordingHttpClient()
    client = SiliconFlowClient(http_client=http_client, api_key="token", base_url="https://api.siliconflow.cn/v1")

    upload_result = client.upload_file(file_path)
    files_result = client.list_files()

    assert upload_result["id"] == "file-123"
    assert files_result["object"] == "list"
    assert http_client.requests[0]["url"] == "https://api.siliconflow.cn/v1/files"
    assert http_client.requests[0]["headers"]["Authorization"] == "Bearer token"
    assert http_client.requests[1]["method"] == "GET"


def test_siliconflow_client_creates_and_gets_batches() -> None:
    http_client = RecordingHttpClient()
    client = SiliconFlowClient(http_client=http_client, api_key="token", base_url="https://api.siliconflow.cn/v1")

    create_result = client.create_batch(
        input_file_id="file-123",
        replace={"model": "deepseek-ai/DeepSeek-V3"},
    )
    get_result = client.get_batch("batch-456")
    list_result = client.list_batches(limit=10)

    assert create_result["id"] == "batch-456"
    assert get_result["status"] == "completed"
    assert list_result["object"] == "list"
    assert http_client.requests[0]["url"] == "https://api.siliconflow.cn/v1/batches"
    assert http_client.requests[0]["json"]["input_file_id"] == "file-123"
    assert http_client.requests[2]["url"] == "https://api.siliconflow.cn/v1/batches"
