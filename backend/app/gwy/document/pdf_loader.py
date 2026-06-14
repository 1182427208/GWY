from __future__ import annotations

from collections import Counter
import math
import re
from pathlib import Path
from typing import Any

from llama_index.core import SimpleDirectoryReader
from llama_index.core.readers.base import BaseReader
from llama_index.core.schema import Document


class PDFLoadError(RuntimeError):
    """Raised when a PDF file cannot be read."""


NAV_LABELS = {
    "首页",
    "招考公告",
    "政策法规",
    "常见问题",
    "相关下载",
    "公告公示",
    "个人中心",
}

CHROME_PATTERNS = (
    re.compile(r"国家公务员局"),
    re.compile(r"中央机关及其直属机构2026年度考试录用公务员专题"),
    re.compile(r"^首页\s*(?:>|»)\s*招考公告(?:\s*(?:>|»)\s*招考公告)?$"),
    re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日\s+星期[一二三四五六日天]\s+.*好[！!]?$"),
    re.compile(r"^(?:<<|>>|<|>)+$"),
    re.compile(r"^咨询电话$"),
)

CHROME_INLINE_PATTERNS = (
    re.compile(r"\d{4}年\d{1,2}月\d{1,2}日\s+星期[一二三四五六日天]\s+[^。\n]{0,40}?(?:上午好|下午好|晚上好|早上好)！?"),
    re.compile(r"国家公务员局\s*"),
    re.compile(r"中央机关及其直属机构2026年度考试录用公务员专题\s*"),
    re.compile(r"首页\s*(?:>|»)\s*招考公告(?:\s*(?:>|»)\s*招考公告)?"),
    re.compile(
        r"(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心)"
        r"(?:\s*(?:>|»)\s*(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心))+"
    ),
    re.compile(
        r"(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心)"
        r"(?:\s*(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心)){2,}"
    ),
    re.compile(r"返回顶部\s*咨询电话(?:<<|>>|<|>)?"),
    re.compile(r"专题首页"),
    re.compile(r"返回顶部"),
    re.compile(r"咨询电话(?:[:：]\s*[\d\-()（）\s]{0,30})?"),
    re.compile(r"版权所有[:：]?\s*国家公务员局"),
    re.compile(r"网站所有[:：]?\s*国家公务员局"),
    re.compile(r"京ICP备\d+-?\d*号?-?\d*"),
    re.compile(r"(?:<<|>>|<|>)"),
)


class LlamaIndexPDFPageReader(BaseReader):
    def lazy_load_data(self, *args: Any, **load_kwargs: Any) -> list[Document]:
        if not args:
            raise PDFLoadError("PDF reader requires a file path.")

        input_file = Path(args[0])
        extra_info = dict(load_kwargs.get("extra_info") or {})

        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise PDFLoadError(
                "PyMuPDF is required for PDF extraction but is not installed."
            ) from exc

        try:
            document = fitz.open(str(input_file))
        except Exception as exc:  # pragma: no cover - defensive
            raise PDFLoadError(f"Failed to open PDF: {input_file}") from exc

        docs: list[Document] = []
        try:
            for page_number, page in enumerate(document, start=1):
                text = strip_document_chrome(page.get_text("text"))
                if not text:
                    continue
                metadata = {
                    **extra_info,
                    "source_file": str(input_file),
                    "page_number": page_number,
                }
                docs.append(Document(text=text, metadata=metadata))
        except Exception as exc:  # pragma: no cover - defensive
            raise PDFLoadError(
                f"Failed to extract text from PDF: {input_file}"
            ) from exc
        finally:
            document.close()

        if not docs:
            raise PDFLoadError(f"No extractable text found in PDF: {input_file}")
        return docs


def load_pdf_pages(file_path: str) -> list[dict[str, str | int]]:
    path = Path(file_path)
    if not path.exists():
        raise PDFLoadError(f"PDF file does not exist: {file_path}")

    primary_documents: list[Document] = []
    try:
        primary_documents = _load_pdf_documents_with_llamaindex(path)
    except Exception:
        primary_documents = []

    pages = _documents_to_pages(primary_documents)
    if pages:
        return pages

    fallback_documents = _load_pdf_documents_with_pypdf(path)
    pages = _documents_to_pages(fallback_documents)
    if pages:
        return pages

    raise PDFLoadError(f"No extractable text found in PDF: {file_path}")


def _load_pdf_documents_with_llamaindex(path: Path) -> list[Document]:
    reader = SimpleDirectoryReader(
        input_files=[str(path)],
        file_extractor={".pdf": LlamaIndexPDFPageReader()},
        filename_as_id=False,
        raise_on_error=True,
    )
    try:
        return reader.load_data()
    except Exception as exc:  # pragma: no cover - defensive
        raise PDFLoadError(f"Failed to load PDF with LlamaIndex: {path}") from exc


def _load_pdf_documents_with_pypdf(path: Path) -> list[Document]:
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PDFLoadError(
            "PyMuPDF is required for PDF extraction but is not installed."
        ) from exc

    try:
        pdf = fitz.open(str(path))
    except Exception as exc:  # pragma: no cover - defensive
        raise PDFLoadError(f"Failed to open PDF with PyMuPDF: {path}") from exc

    documents: list[Document] = []
    try:
        for page_number, page in enumerate(pdf, start=1):
            text = strip_document_chrome(str(page.get_text("text") or ""))
            if not text:
                continue
            documents.append(
                Document(
                    text=text,
                    metadata={
                        "source_file": str(path),
                        "page_number": page_number,
                    },
                )
            )
    finally:
        pdf.close()

    if not documents:
        raise PDFLoadError(f"No extractable text found in PDF: {path}")
    return documents


def _documents_to_pages(documents: list[Document]) -> list[dict[str, str | int]]:
    if not documents:
        return []

    boilerplate_lines = _collect_repeated_boilerplate_lines(documents)
    pages: list[dict[str, str | int]] = []
    for document in documents:
        page_number = document.metadata.get("page_number")
        if page_number is None:
            continue
        text = strip_document_chrome(document.text, boilerplate_lines=boilerplate_lines)
        if not text:
            continue
        pages.append({"page": int(page_number), "text": text})
    return pages


def strip_document_chrome(
    text: str,
    *,
    boilerplate_lines: set[str] | None = None,
) -> str:
    raw_text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw_text.strip():
        return ""

    raw_text = _strip_inline_chrome_fragments(raw_text)
    kept_lines: list[str] = []
    for line in raw_text.splitlines():
        stripped = _clean_document_line(line)
        if not stripped:
            continue
        normalized = _normalize_comparison_key(stripped)
        if boilerplate_lines and normalized in boilerplate_lines:
            continue
        if _is_document_chrome_line(stripped):
            continue
        kept_lines.append(stripped)
    cleaned_text = _normalize_text("\n".join(kept_lines))
    if not cleaned_text:
        return ""
    cleaned_text = _strip_inline_chrome_fragments(cleaned_text)
    return _normalize_text(cleaned_text)


def _clean_document_line(line: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned:
        return ""

    for pattern in CHROME_INLINE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s*([>»<]{1,})\s*", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" -_|/\\")
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    if not cleaned:
        return ""
    if _is_document_chrome_line(cleaned):
        return ""
    return cleaned


def _strip_inline_chrome_fragments(text: str) -> str:
    cleaned = str(text or "")
    if not cleaned:
        return ""

    inline_patterns = (
        re.compile(r"2026年\d{2}月\d{2}日\s*星期[一二三四五六日]\s*下午好！\s*国家公务员局"),
        re.compile(r"国家公务员局\s*中央机关及其直属机构2026年度考试录用公务员专题"),
        re.compile(r"专题首页\s*[>»]\s*招考公告(?:\s*[>»]\s*招考公告)?"),
        re.compile(r"首页\s*[>»]\s*招考公告(?:\s*[>»]\s*招考公告)?"),
        re.compile(
            r"(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心)"
            r"(?:\s*(?:[>»]|\||/)\s*(?:首页|招考公告|政策法规|常见问题|相关下载|公告公示|个人中心))+"
        ),
        re.compile(r"返回顶部\s*咨询电话(?:<<|>>|<|>)?"),
        re.compile(r"\[关闭本页\]\s*版权所有[:：]?\s*国家公务员局"),
        re.compile(r"版权所有[:：]?\s*国家公务员局"),
        re.compile(r"网站所有[:：]?\s*国家公务员局"),
        re.compile(r"京ICP备\d{6,}号?-?\d*"),
        re.compile(r"咨询电话[:：]?\s*[\d\-()（）\s]{0,30}"),
    )

    for pattern in inline_patterns:
        cleaned = pattern.sub(" ", cleaned)

    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _is_document_chrome_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in NAV_LABELS:
        return True
    if all(part.strip() in NAV_LABELS for part in re.split(r"\s+", stripped) if part.strip()):
        return True
    return any(pattern.search(stripped) for pattern in CHROME_PATTERNS)


def _normalize_comparison_key(text: str) -> str:
    return re.sub(r"[\s>><<：:，,。\.·\-_/\\|]+", "", str(text or "").strip())


def _collect_repeated_boilerplate_lines(documents: list[Any]) -> set[str]:
    if not documents:
        return set()

    counts: Counter[str] = Counter()
    threshold = max(3, math.ceil(len(documents) * 0.4))
    for document in documents:
        seen: set[str] = set()
        for raw_line in str(document.text or "").splitlines():
            cleaned = _clean_document_line(raw_line)
            if not cleaned:
                continue
            normalized = _normalize_comparison_key(cleaned)
            if not normalized or normalized in seen:
                continue
            if len(normalized) > 80:
                continue
            if _looks_like_body_line(cleaned):
                continue
            seen.add(normalized)
            counts[normalized] += 1

    return {key for key, count in counts.items() if count >= threshold}


def _looks_like_body_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    if re.match(r"^(?:\d+|[一二三四五六七八九十]+)[.．、)]?\s*.+", stripped):
        return True
    if re.match(r"^（?[一二三四五六七八九十]+）", stripped):
        return True
    if re.search(r"[？?]$", stripped):
        return True
    if stripped.startswith(("答：", "答:", "问：", "问:")):
        return True
    if len(stripped) >= 20 and not any(marker in stripped for marker in ("首页", "返回顶部", "咨询电话", "专题", "版权所有", "网站所有")):
        return True
    return False


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n").replace("\u3000", " ")
    lines = [line.strip() for line in text.splitlines()]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if not line:
            if current:
                paragraphs.append(_merge_lines(current))
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(_merge_lines(current))

    normalized = "\n".join(paragraphs)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _merge_lines(lines: list[str]) -> str:
    if not lines:
        return ""
    merged = lines[0]
    for line in lines[1:]:
        if _should_join(merged, line):
            merged += line
        else:
            merged += f" {line}"
    return merged.strip()


def _should_join(previous: str, current: str) -> bool:
    if not previous:
        return False
    heading_prefixes = (
        "一、",
        "二、",
        "三、",
        "四、",
        "五、",
        "六、",
        "七、",
        "八、",
        "九、",
        "十、",
        "（一）",
        "（二）",
        "（三）",
        "（四）",
        "（五）",
        "（六）",
        "（七）",
        "（八）",
        "（九）",
        "（十）",
    )
    if current.startswith(heading_prefixes):
        return False
    if re.match(r"^[0-9]+[.．)]", current):
        return False
    if previous.endswith(("。", "！", "？", "?", "；", ";", ":", "：")):
        return False
    return True
