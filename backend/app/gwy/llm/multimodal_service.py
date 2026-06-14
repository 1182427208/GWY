from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from app.gwy.llm.siliconflow_client import SiliconFlowClient


class MultimodalSummaryService:
    def __init__(self, *, client: SiliconFlowClient | None = None) -> None:
        self.client = client or SiliconFlowClient()

    def summarize_image(
        self,
        *,
        image_path: str,
        nearby_text: str = "",
        source_file: str = "",
        page: int | None = None,
        bbox: list[float] | None = None,
    ) -> dict[str, Any]:
        path = Path(image_path)
        if not path.exists():
            return self._pending_summary(
                image_path=image_path,
                nearby_text=nearby_text,
                source_file=source_file,
                page=page,
                bbox=bbox,
            )

        prompt = (
            "请对图片进行 OCR 和内容理解，并输出简洁摘要。"
            "如果图片包含表格、流程图或标题，请一并概括。"
            "返回中文摘要，尽量保留关键文字。"
        )
        try:
            image_bytes = path.read_bytes()
            image_data = base64.b64encode(image_bytes).decode("utf-8")
            image_url = f"data:image/png;base64,{image_data}"
            response = self.client.chat_completions(
                [
                    {
                        "role": "system",
                        "content": "你是一个擅长图片 OCR 和摘要的助手。",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._build_prompt(prompt, nearby_text)},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    },
                ],
                temperature=0.2,
            )
            summary = response.strip() or self._fallback_summary(
                source_file=source_file,
                page=page,
                nearby_text=nearby_text,
            )
            return {
                "summary": summary,
                "ocr_text": summary,
                "extraction_status": "success",
            }
        except Exception:
            return self._pending_summary(
                image_path=image_path,
                nearby_text=nearby_text,
                source_file=source_file,
                page=page,
                bbox=bbox,
            )

    def _pending_summary(
        self,
        *,
        image_path: str,
        nearby_text: str,
        source_file: str,
        page: int | None,
        bbox: list[float] | None,
    ) -> dict[str, Any]:
        return {
            "summary": self._fallback_summary(
                source_file=source_file,
                page=page,
                nearby_text=nearby_text,
            ),
            "ocr_text": "",
            "extraction_status": "pending_multimodal_summary",
            "image_path": image_path,
            "nearby_text": nearby_text,
            "page": page,
            "bbox": bbox or [],
        }

    def _fallback_summary(
        self,
        *,
        source_file: str,
        page: int | None,
        nearby_text: str,
    ) -> str:
        page_text = f"第 {page} 页" if page else "当前页"
        return (
            f"图片来源：{Path(source_file).name or source_file} {page_text}。"
            f"图片附近文本：{nearby_text[:120]}"
        ).strip()

    def _build_prompt(self, prompt: str, nearby_text: str) -> str:
        nearby = nearby_text.strip()
        if not nearby:
            return prompt
        return f"{prompt}\n\n图片附近文本：{nearby}"
