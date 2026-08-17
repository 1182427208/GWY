from __future__ import annotations

from pathlib import Path

import pytest

from app.gwy.llm.multimodal_service import MultimodalSummaryService


class RecordingVisionClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def chat_completions(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.messages = list(messages)
        return "图片中有一张岗位信息表。"


def test_summarize_image_preserves_actual_image_mime_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = Path("position.jpg")
    monkeypatch.setattr(Path, "exists", lambda self: self == image_path)
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"image-bytes")
    client = RecordingVisionClient()

    result = MultimodalSummaryService(client=client).summarize_image(
        image_path=str(image_path),
        source_file=image_path.name,
    )

    image_part = client.messages[1]["content"][1]  # type: ignore[index]
    image_url = image_part["image_url"]["url"]  # type: ignore[index]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert result["extraction_status"] == "success"
    assert result["summary"] == "图片中有一张岗位信息表。"
