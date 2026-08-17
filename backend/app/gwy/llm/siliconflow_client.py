from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
from openai import APIStatusError, BadRequestError, OpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class SiliconFlowError(RuntimeError):
    """Raised when a SiliconFlow request fails."""


class SiliconFlowClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        chat_base_url: str | None = None,
        chat_api_key: str | None = None,
        chat_model: str | None = None,
        tool_chat_base_url: str | None = None,
        tool_chat_api_key: str | None = None,
        tool_chat_model: str | None = None,
        embedding_model: str | None = None,
        reranker_model: str | None = None,
        tts_model: str | None = None,
        tts_voice: str | None = None,
        enable_thinking: bool = True,
        thinking_budget: int = 1024,
        timeout: float = 60.0,
        client: Any | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.base_url = (base_url or settings.SILICONFLOW_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.SILICONFLOW_API_KEY
        self.chat_base_url = self._normalize_openai_base_url(
            chat_base_url or settings.CHAT_BASE_URL or self.base_url
        )
        self.chat_api_key = (
            chat_api_key if chat_api_key is not None else settings.CHAT_API_KEY
        )
        self.chat_model = chat_model or settings.CHAT_MODEL or settings.SILICONFLOW_CHAT_MODEL
        self.tool_chat_base_url = self._normalize_openai_base_url(
            tool_chat_base_url
            or settings.TOOL_CHAT_BASE_URL
            or self.chat_base_url
        )
        self.tool_chat_api_key = (
            tool_chat_api_key
            if tool_chat_api_key is not None
            else settings.TOOL_CHAT_API_KEY or self.chat_api_key
        )
        self.tool_chat_model = tool_chat_model or settings.TOOL_CHAT_MODEL or self.chat_model
        self.embedding_model = embedding_model or settings.SILICONFLOW_EMBEDDING_MODEL
        self.reranker_model = reranker_model or settings.SILICONFLOW_RERANKER_MODEL
        self.tts_model = tts_model or settings.SILICONFLOW_TTS_MODEL
        self.tts_voice = tts_voice or settings.SILICONFLOW_TTS_VOICE
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget
        self.timeout = timeout
        self._client = client
        self._http_client = http_client
        self._openai_client = client or OpenAI(
            api_key=self.chat_api_key or "EMPTY",
            base_url=self.chat_base_url,
            timeout=self.timeout,
        )
        self._tool_openai_client = client or OpenAI(
            api_key=self.tool_chat_api_key or "EMPTY",
            base_url=self.tool_chat_base_url,
            timeout=self.timeout,
        )

    def chat_completions(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> str:
        last_error: Exception | None = None
        for candidate_model in self._chat_model_candidates(model):
            try:
                response = self._chat_client().chat.completions.create(
                    model=candidate_model,
                    messages=list(messages),
                    temperature=temperature,
                    extra_body=self._thinking_payload(
                        candidate_model,
                        enable_thinking=enable_thinking,
                        thinking_budget=thinking_budget,
                    ),
                )
                choices = getattr(response, "choices", None) or []
                if not choices:
                    raise SiliconFlowError("SiliconFlow chat response is empty.")
                message = choices[0].message
                return self._stringify_content(getattr(message, "content", None))
            except (BadRequestError, APIStatusError, SiliconFlowError) as exc:
                last_error = exc
                logger.warning(
                    "SiliconFlow chat completion failed for model %s: %s",
                    candidate_model,
                    exc,
                )
                continue
        if last_error is not None:
            raise SiliconFlowError("SiliconFlow chat request failed.") from last_error
        raise SiliconFlowError("SiliconFlow chat request failed.")

    def chat_completions_stream(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        last_error: Exception | None = None
        for candidate_model in self._chat_model_candidates(model):
            try:
                stream = self._chat_client().chat.completions.create(
                    model=candidate_model,
                    messages=list(messages),
                    temperature=temperature,
                    stream=True,
                    extra_body=self._thinking_payload(
                        candidate_model,
                        enable_thinking=enable_thinking,
                        thinking_budget=thinking_budget,
                    ),
                )
                yield from self._iter_openai_stream_response(stream)
                return
            except (BadRequestError, APIStatusError, SiliconFlowError) as exc:
                last_error = exc
                logger.warning(
                    "SiliconFlow chat stream failed for model %s: %s",
                    candidate_model,
                    exc,
                )
                continue
        if last_error is not None:
            raise SiliconFlowError("SiliconFlow chat stream failed.") from last_error
        raise SiliconFlowError("SiliconFlow chat stream failed.")

    def chat_completion_message(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> dict[str, Any]:
        """Return an OpenAI-compatible assistant message, including tool calls."""
        last_error: Exception | None = None
        for candidate_model in self._tool_chat_model_candidates(model):
            try:
                payload: dict[str, Any] = {
                    "model": candidate_model,
                    "messages": list(messages),
                    "temperature": temperature,
                    "extra_body": self._thinking_payload(
                        candidate_model,
                        enable_thinking=enable_thinking,
                        thinking_budget=thinking_budget,
                    ),
                }
                if max_tokens is not None:
                    payload["max_tokens"] = max_tokens
                if tools:
                    payload["tools"] = list(tools)
                    payload["tool_choice"] = "auto"
                response = self._tool_chat_client().chat.completions.create(**payload)
                choices = getattr(response, "choices", None) or []
                if not choices:
                    raise SiliconFlowError("SiliconFlow chat response is empty.")
                return self._message_to_dict(
                    choices[0].message,
                    finish_reason=getattr(choices[0], "finish_reason", None),
                )
            except (BadRequestError, APIStatusError, SiliconFlowError) as exc:
                last_error = exc
                logger.debug(
                    "SiliconFlow tool chat failed for model %s: %s",
                    candidate_model,
                    exc,
                )
                continue
        if last_error is not None:
            raise SiliconFlowError("SiliconFlow tool chat failed.") from last_error
        raise SiliconFlowError("SiliconFlow tool chat failed.")

    def speech(
        self,
        text: str,
        *,
        model: str | None = None,
        voice: str | None = None,
        response_format: str = "mp3",
        speed: float | None = None,
        gain: float | None = None,
        stream: bool = True,
    ) -> bytes:
        payload: dict[str, Any] = {
            "model": model or self.tts_model,
            "input": text,
            "voice": voice if voice is not None else self.tts_voice,
            "response_format": response_format,
            "stream": stream,
        }
        if speed is not None:
            payload["speed"] = speed
        if gain is not None:
            payload["gain"] = gain

        response = self._request("POST", "/audio/speech", json=payload)
        self._raise_for_status(response)
        return response.content

    def embeddings(
        self,
        texts: Sequence[str],
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": model or self.embedding_model,
            "input": list(texts),
        }
        if dimensions is not None:
            payload["dimensions"] = dimensions
        data = self._post_json("/embeddings", payload)
        vectors = data.get("data") or []
        if len(vectors) != len(texts):
            raise SiliconFlowError("Embedding response size does not match input.")
        return [[float(value) for value in item["embedding"]] for item in vectors]

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int = 5,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        data = self._post_json(
            "/rerank",
            {
                "model": model or self.reranker_model,
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
            },
        )
        results = data.get("results") or data.get("data") or []
        normalized: list[dict[str, Any]] = []
        for item in results:
            index = item.get("index")
            if index is None and isinstance(item.get("document"), dict):
                index = item["document"].get("index")
            score = item.get("relevance_score", item.get("score", 0.0))
            normalized.append(
                {
                    "index": int(index),
                    "score": float(score),
                    "document": item.get("document"),
                }
            )
        return normalized[:top_n]

    def upload_file(
        self,
        file_path: str | Path,
        *,
        purpose: str = "batch",
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise SiliconFlowError(f"File not found: {path}")

        files = {
            "file": (path.name, path.open("rb")),
        }
        try:
            response = self._request(
                "POST",
                "/files",
                data={"purpose": purpose},
                files=files,
            )
            self._raise_for_status(response)
            payload = self._decode_json_response(response)
            return self._unwrap_data(payload)
        finally:
            file_obj = files["file"][1]
            if hasattr(file_obj, "close"):
                file_obj.close()

    def list_files(
        self,
        *,
        purpose: str | None = "batch",
        limit: int | None = None,
        order: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if purpose is not None:
            params["purpose"] = purpose
        if limit is not None:
            params["limit"] = limit
        if order is not None:
            params["order"] = order
        response = self._request("GET", "/files", params=params or None)
        self._raise_for_status(response)
        payload = self._decode_json_response(response)
        return self._unwrap_data(payload)

    def create_batch(
        self,
        *,
        input_file_id: str,
        endpoint: str = "/v1/chat/completions",
        completion_window: str = "24h",
        metadata: dict[str, Any] | None = None,
        replace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input_file_id": input_file_id,
            "endpoint": endpoint,
            "completion_window": completion_window,
        }
        if metadata is not None:
            payload["metadata"] = metadata
        if replace is not None:
            payload["replace"] = replace
        response = self._post("/batches", payload)
        decoded = self._decode_json_response(response)
        return self._unwrap_data(decoded)

    def get_batch(self, batch_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/batches/{batch_id}")
        self._raise_for_status(response)
        payload = self._decode_json_response(response)
        return self._unwrap_data(payload)

    def list_batches(
        self,
        *,
        limit: int | None = None,
        after: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if after is not None:
            params["after"] = after
        response = self._request("GET", "/batches", params=params or None)
        self._raise_for_status(response)
        payload = self._decode_json_response(response)
        return self._unwrap_data(payload)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._post(path, payload)
        return self._decode_json_response(response)

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        headers = self._auth_headers()

        response = self._request("POST", path, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - defensive
            raise SiliconFlowError(
                f"SiliconFlow request failed: {exc.response.status_code}"
            ) from exc
        return response

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:  # pragma: no cover - defensive
            raise SiliconFlowError(
                f"SiliconFlow request failed: {exc.response.status_code}"
            ) from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        merged_headers = dict(headers or {})
        if method.upper() != "GET" and json is not None:
            merged_headers.setdefault("Content-Type", "application/json")
        if self.api_key:
            merged_headers.setdefault("Authorization", f"Bearer {self.api_key}")

        if self._http_client is not None:
            client = self._http_client
            request_fn = getattr(client, method.lower())
            return request_fn(
                self._url(path),
                headers=merged_headers or None,
                params=params,
                json=json,
                data=data,
                files=files,
            )

        with httpx.Client(timeout=self.timeout) as client:
            return client.request(
                method.upper(),
                self._url(path),
                headers=merged_headers or None,
                params=params,
                json=json,
                data=data,
                files=files,
            )

    def _decode_json_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise SiliconFlowError("SiliconFlow returned invalid JSON.") from exc

    def _unwrap_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return payload

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _iter_openai_stream_response(
        self, response: Any
    ) -> Iterator[dict[str, Any]]:
        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                yield {
                    "type": "reasoning",
                    "text": self._stringify_content(reasoning),
                }
            content = getattr(delta, "content", None)
            if content:
                yield {"type": "content", "text": self._stringify_content(content)}

    def _url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized_path}"

    def _normalize_openai_base_url(self, url: str | None) -> str:
        normalized = (url or self.base_url).rstrip("/")
        if normalized in {"https://a6api.com", "http://a6api.com"}:
            return f"{normalized}/v1"
        return normalized

    def _chat_model_candidates(self, model: str | None) -> list[str]:
        primary = model or self.chat_model
        return [primary]

    def _tool_chat_model_candidates(self, model: str | None) -> list[str]:
        primary = model or self.tool_chat_model
        return [primary]

    def _chat_client(self) -> Any:
        return self._openai_client

    def _tool_chat_client(self) -> Any:
        return self._tool_openai_client

    def _thinking_payload(
        self,
        model: str,
        *,
        enable_thinking: bool | None = None,
        thinking_budget: int | None = None,
    ) -> dict[str, Any]:
        if enable_thinking is None:
            enable_thinking = self.enable_thinking
        if thinking_budget is None:
            thinking_budget = self.thinking_budget
        payload: dict[str, Any] = {}
        if enable_thinking and self._supports_enable_thinking(model):
            payload["enable_thinking"] = True
        if self._supports_thinking_budget(model):
            payload["thinking_budget"] = int(thinking_budget)
        return payload

    def _supports_enable_thinking(self, model: str) -> bool:
        normalized = model.strip().lower()
        supported_prefixes = (
            "qwen/qwen3-8b",
            "qwen/qwen3-14b",
            "qwen/qwen3-32b",
            "qwen/qwen3-30b-a3b",
            "qwen/qwen3-235b-a22b",
            "tencent/hunyuan-a13b-instruct",
            "zai-org/glm-4.5v",
            "deepseek-ai/deepseek-v3.1-terminus",
            "pro/deepseek-ai/deepseek-v3.1-terminus",
        )
        return normalized.startswith(supported_prefixes)

    def _supports_thinking_budget(self, model: str) -> bool:
        normalized = model.strip().lower()
        if "thinking" in normalized or "r1" in normalized or "reasoning" in normalized:
            return True
        return self._supports_enable_thinking(model)

    def _stringify_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text:
                        parts.append(str(text))
                else:
                    parts.append(str(item))
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    def _message_to_dict(
        self,
        message: Any,
        *,
        finish_reason: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": "assistant",
            "content": self._stringify_content(getattr(message, "content", None)),
        }
        if finish_reason:
            result["finish_reason"] = finish_reason
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            result["tool_calls"] = []
            for call in tool_calls:
                function = getattr(call, "function", None)
                result["tool_calls"].append(
                    {
                        "id": str(getattr(call, "id", "")),
                        "type": str(getattr(call, "type", "function")),
                        "function": {
                            "name": str(getattr(function, "name", "")),
                            "arguments": str(
                                getattr(function, "arguments", "{}") or "{}"
                            ),
                        },
                    }
                )
        return result
