from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import httpx

from app.core.config import settings
from app.gwy.services.web_mcp_client import WebMCPClient


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str | None
    title: str | None
    text: str
    content_type: str | None
    status_code: int | None
    source: str = "fetch"
    retrieved_via: str = "http"
    is_pdf: bool = False


class WebFetchService:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        web_mcp_enabled: bool = True,
        mcp_url: str | None = None,
        timeout: float | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.enabled = True if enabled is None else enabled
        self.web_mcp_enabled = web_mcp_enabled
        self.mcp_url = mcp_url or (
            str(settings.FETCH_MCP_URL) if settings.FETCH_MCP_URL else None
        )
        self.timeout = timeout or settings.WEB_FETCH_TIMEOUT_SECONDS
        self.http_client = http_client

    def fetch(self, url: str) -> dict[str, Any]:
        normalized_url = str(url or "").strip()
        if not self.enabled or not normalized_url:
            return {}

        try:
            if self.web_mcp_enabled and settings.WEB_MCP_URL is not None:
                mcp_result = WebMCPClient(endpoint_url=str(settings.WEB_MCP_URL)).fetch(
                    normalized_url
                )
                if mcp_result:
                    return self._normalize_result(
                        url=normalized_url,
                        title=_as_text(mcp_result.get("title")),
                        text=_as_text(mcp_result.get("text") or mcp_result.get("content")),
                        content_type=_as_text(mcp_result.get("content_type")),
                        status_code=mcp_result.get("status_code"),
                        final_url=_as_text(mcp_result.get("url") or mcp_result.get("final_url"))
                        or normalized_url,
                        source="fetch",
                        retrieved_via=str(
                            mcp_result.get("retrieved_via") or "fetch_mcp"
                        ),
                        is_pdf=bool(mcp_result.get("is_pdf")),
                    )
            if self.mcp_url:
                return self._fetch_via_mcp(normalized_url)
            return self._fetch_via_http(normalized_url)
        except Exception:
            return {}

    def _fetch_via_mcp(self, url: str) -> dict[str, Any]:
        payload = {"url": url}
        endpoint = self.mcp_url.rstrip("/") + "/fetch"
        if self.http_client is not None:
            response = self.http_client.post(endpoint, json=payload, timeout=self.timeout)
        else:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.post(endpoint, json=payload)
        response.raise_for_status()
        data = response.json()
        return self._normalize_result(
            url=url,
            title=_as_text(data.get("title")),
            text=_as_text(data.get("text") or data.get("content")),
            content_type=_as_text(data.get("content_type")),
            status_code=getattr(response, "status_code", None),
            final_url=_as_text(data.get("url") or data.get("final_url")) or url,
            source="fetch",
            retrieved_via="fetch_mcp",
            is_pdf=bool(data.get("is_pdf")),
        )

    def _fetch_via_http(self, url: str) -> dict[str, Any]:
        if self.http_client is not None:
            response = self.http_client.get(
                url,
                timeout=self.timeout,
                follow_redirects=True,
            )
        else:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.get(url, headers=_default_headers())
        response.raise_for_status()
        content_type = _content_type_from_headers(response.headers)
        body = getattr(response, "content", b"")
        text = ""
        title = None
        is_pdf = False

        if content_type and "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            text = _extract_pdf_text(body)
            is_pdf = True
        else:
            html_text = getattr(response, "text", "")
            text, title = _extract_html_text(html_text)

        return self._normalize_result(
            url=url,
            title=title,
            text=text,
            content_type=content_type,
            status_code=getattr(response, "status_code", None),
            final_url=str(getattr(response, "url", url) or url),
            source="fetch",
            retrieved_via="http",
            is_pdf=is_pdf,
        )

    def _normalize_result(
        self,
        *,
        url: str,
        final_url: str | None,
        title: str | None,
        text: str,
        content_type: str | None,
        status_code: int | None,
        source: str,
        retrieved_via: str,
        is_pdf: bool,
    ) -> dict[str, Any]:
        cleaned_text = _normalize_text(text)
        return {
            "url": url,
            "final_url": final_url,
            "title": title or None,
            "text": cleaned_text,
            "content_type": content_type,
            "status_code": status_code,
            "source": source,
            "retrieved_via": retrieved_via,
            "is_pdf": is_pdf,
            "text_length": len(cleaned_text),
        }


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._title_parts: list[str] = []
        self._capture_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._capture_title = True
            return
        if tag in {"p", "div", "section", "article", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        text = str(data or "").strip()
        if not text or self._skip_depth > 0:
            return
        if self._capture_title:
            self._title_parts.append(text)
        self._chunks.append(text)

    @property
    def title(self) -> str | None:
        text = " ".join(self._title_parts).strip()
        return text or None

    @property
    def text(self) -> str:
        return _normalize_text(" ".join(self._chunks))


def _extract_html_text(html_text: str) -> tuple[str, str | None]:
    parser = _ReadableHTMLParser()
    parser.feed(str(html_text or ""))
    parser.close()
    return parser.text, parser.title


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError:
        return ""

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return ""

    try:
        parts: list[str] = []
        for page in document:
            text = str(page.get_text("text") or "").strip()
            if text:
                parts.append(text)
        return "\n".join(parts)
    finally:
        document.close()


def _normalize_text(text: str) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in raw.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned.strip()


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }


def _content_type_from_headers(headers: Any) -> str | None:
    if not headers:
        return None
    if isinstance(headers, dict):
        return str(headers.get("content-type") or headers.get("Content-Type") or "").strip() or None
    try:
        return str(headers.get("content-type") or headers.get("Content-Type") or "").strip() or None
    except Exception:
        return None


def _as_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
