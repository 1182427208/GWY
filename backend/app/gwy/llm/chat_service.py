from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import Any

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class ChatService:
    def __init__(self, *, client: SiliconFlowClient | None = None) -> None:
        self.client = client or SiliconFlowClient()

    def chat_completion(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> str:
        return self.client.chat_completions(
            messages,
            model=model,
            temperature=temperature,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
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

    def summarize_compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        focus: str = "",
    ) -> str:
        conversation_text = json.dumps(messages, ensure_ascii=False, default=str)[-80000:]
        focus_instruction = ""
        if focus:
            focus_instruction = f" Pay special attention to preserving details about: {focus}."
        prompt = (
            "Summarize this conversation for continuity. Include: "
            "1) What was accomplished, 2) Current state, 3) Key decisions made. "
            "Be concise but preserve critical details."
            f"{focus_instruction}\n\n{conversation_text}"
        )
        return self.chat_completion([{"role": "user", "content": prompt}], temperature=0.2)
