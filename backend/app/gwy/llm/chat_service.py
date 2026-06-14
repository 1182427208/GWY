from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class ChatService:
    def __init__(self, *, client: SiliconFlowClient | None = None) -> None:
        self.client = client or SiliconFlowClient()

    def chat_completion(
        self,
        messages: Sequence[dict[str, Any]],
        temperature: float = 0.2,
    ) -> str:
        return self.client.chat_completions(
            messages,
            temperature=temperature,
        )

    def stream_chat_completion(
        self,
        messages: Sequence[dict[str, Any]],
        temperature: float = 0.2,
    ) -> Iterator[dict[str, Any]]:
        return self.client.chat_completions_stream(
            messages,
            temperature=temperature,
        )
