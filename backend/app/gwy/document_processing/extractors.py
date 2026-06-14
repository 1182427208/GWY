from __future__ import annotations

import hashlib
import json
import re
from typing import Any


QUESTION_PREFIX_RE = re.compile(r"^(?:问(?:题)?|Q)\s*[:：]?\s*(.+)$", re.IGNORECASE)
ANSWER_PREFIX_RE = re.compile(r"^(?:答(?:复)?|回(?:答|复)|A)\s*[:：]?\s*(.+)$", re.IGNORECASE)
NUMBERED_PREFIX_RE = re.compile(
    r"^(?:\d+|[一二三四五六七八九十]+|（[一二三四五六七八九十]+）)[.、)]\s*(.+)$"
)
QUESTION_HINT_RE = re.compile(
    r"(?:[?？]$|(?:如何|怎么|怎样|何时|哪里|哪些|是否|能否|可以吗|怎么办|多少|什么|为什么|谁|需不需要|是不是))"
)
HEADING_PATTERN = re.compile(
    r"^(?:第[一二三四五六七八九十百千0-9]+[章节条篇部分]|[一二三四五六七八九十百千0-9]+[、.．)]|\([一二三四五六七八九十百千0-9]+\)|（[一二三四五六七八九十百千0-9]+）)"
)


def normalize_text(text: str) -> str:
    text = str(text or "").replace("\u3000", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    compacted: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            blank_seen = True
            continue
        if blank_seen and compacted:
            compacted.append("")
        compacted.append(line)
        blank_seen = False
    return "\n".join(compacted).strip()


def has_question_answer_structure(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    pairs = parse_qa_pairs(normalized)
    if any(str(pair.get("question", "")).strip() and str(pair.get("answer", "")).strip() for pair in pairs):
        return True

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    question_lines = sum(1 for line in lines if _is_question_line(line))
    answer_lines = sum(1 for line in lines if _is_answer_line(line))
    return question_lines >= 1 and answer_lines >= 1


def parse_qa_pairs(text: str) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return []

    pairs: list[dict[str, str]] = []
    current_question: list[str] = []
    current_answer: list[str] = []
    state: str | None = None

    def flush() -> None:
        question = normalize_text(" ".join(current_question)).strip()
        answer = normalize_text(" ".join(current_answer)).strip()
        question = _strip_qa_prefix(question)
        answer = _strip_qa_prefix(answer)
        if not question and not answer:
            return
        if not question:
            return
        pairs.append(
            {
                "question": question,
                "answer": answer,
                "content": f"问：{question}\n答：{answer}".strip(),
            }
        )

    for line in lines:
        if _is_question_line(line):
            if current_question or current_answer:
                flush()
                current_question = []
                current_answer = []
            state = "question"
            current_question.append(_strip_question_prefix(line))
            continue

        if _is_answer_line(line):
            state = "answer"
            current_answer.append(_strip_answer_prefix(line))
            continue

        if state == "answer":
            current_answer.append(line)
        elif state == "question":
            # Treat the line as part of the question until the answer marker appears.
            current_question.append(line)
        else:
            current_question.append(line)

    flush()
    if any(str(pair.get("question", "")).strip() and str(pair.get("answer", "")).strip() for pair in pairs):
        return pairs

    compact_pairs = _parse_compact_numbered_qa_pairs(normalized)
    if compact_pairs:
        return compact_pairs

    return pairs


def parse_table_from_text(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    if has_question_answer_structure(normalized):
        return None

    rows: list[list[str]] = []
    for line in lines:
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|") if cell.strip()]
        elif "\t" in line:
            cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        else:
            cells = [cell.strip() for cell in re.split(r"\s{2,}", line) if cell.strip()]
        if len(cells) >= 2:
            rows.append(cells)

    if len(rows) < 2:
        return None

    columns = rows[0]
    data_rows = rows[1:]
    if len(columns) < 2 or len(data_rows) < 1:
        return None
    if not _table_is_stable(columns, data_rows):
        return None

    return {
        "title": "",
        "columns": columns,
        "rows": data_rows,
        "markdown_content": table_rows_to_markdown(columns, data_rows),
    }


def table_rows_to_markdown(columns: list[str], rows: list[list[str]]) -> str:
    if not columns:
        return ""
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body: list[str] = []
    for row in rows:
        normalized = [str(cell).strip() for cell in row]
        if len(normalized) < len(columns):
            normalized.extend([""] * (len(columns) - len(normalized)))
        body.append("| " + " | ".join(normalized[: len(columns)]) + " |")
    return "\n".join([header, separator, *body])


def _parse_compact_numbered_qa_pairs(text: str) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    # Insert line breaks before numbered questions so compact pages can be parsed.
    prepared = re.sub(
        r"(?<!\n)(?=(?:\d+|[一二三四五六七八九十]+)[\.、])",
        "\n",
        normalized,
    )
    prepared = re.sub(
        r"(?<!\n)(?=(?:问[:：]|问题[:：]|Q[:：]|答[:：]|回答[:：]|A[:：]))",
        "\n",
        prepared,
    )
    lines = [line.strip() for line in prepared.splitlines() if line.strip()]
    if not lines:
        return []

    question_prefix = re.compile(r"^(?:\d+|[一二三四五六七八九十]+)[\.、]\s*")
    question_body = re.compile(
        r"^(?P<body>.+?[？?])(?:\s*(?P<answer>.*))?$",
    )

    pairs: list[dict[str, str]] = []
    current_question: str = ""
    current_answer_parts: list[str] = []

    def flush_current() -> None:
        nonlocal current_question, current_answer_parts
        question = normalize_text(current_question).strip()
        answer = normalize_text(" ".join(current_answer_parts)).strip()
        question = _strip_qa_prefix(question)
        answer = _strip_qa_prefix(answer)
        answer = _strip_trailing_chrome(answer)
        question = _strip_trailing_chrome(question)
        if question and answer:
            pairs.append(
                {
                    "question": question,
                    "answer": answer,
                    "content": f"问：{question}\n答：{answer}".strip(),
                }
            )
        current_question = ""
        current_answer_parts = []

    for line in lines:
        if question_prefix.match(line):
            if current_question or current_answer_parts:
                flush_current()
            line = question_prefix.sub("", line).strip()
            match = question_body.match(line)
            if match:
                current_question = match.group("body").strip()
                initial_answer = (match.group("answer") or "").strip()
                if initial_answer:
                    current_answer_parts.append(initial_answer)
            else:
                current_question = line
            continue

        if _is_answer_line(line):
            current_answer_parts.append(_strip_answer_prefix(line))
            continue

        if current_question:
            current_answer_parts.append(line)

    if current_question or current_answer_parts:
        flush_current()

    return pairs


def split_heading_sections(text: str) -> list[dict[str, str]]:
    normalized = normalize_text(text)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return []

    sections: list[dict[str, str]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush() -> None:
        if not current_lines:
            return
        sections.append(
            {
                "heading": current_heading,
                "content": "\n".join(current_lines).strip(),
            }
        )

    for line in lines:
        if HEADING_PATTERN.match(line):
            flush()
            current_heading = line
            current_lines = [line]
        else:
            current_lines.append(line)

    flush()
    return sections


def split_semantic_text(
    text: str,
    *,
    chunk_size: int = 700,
    overlap: int = 150,
) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in normalized.splitlines() if line.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0
            chunks.extend(_split_long_paragraph(paragraph, chunk_size=chunk_size))
            continue

        addition = len(paragraph) + (2 if current else 0)
        if current and current_len + addition > chunk_size:
            chunks.append("\n\n".join(current).strip())
            current = _build_overlap(current, overlap)
            current_len = len("\n\n".join(current).strip())

        current.append(paragraph)
        current_len = len("\n\n".join(current).strip())

    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def make_content_hash(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _is_question_line(line: str) -> bool:
    if QUESTION_PREFIX_RE.match(line):
        return True
    match = NUMBERED_PREFIX_RE.match(line)
    if not match:
        return False
    body = match.group(1).strip()
    return bool(QUESTION_HINT_RE.search(body))


def _is_answer_line(line: str) -> bool:
    return bool(ANSWER_PREFIX_RE.match(line))


def _strip_qa_prefix(text: str) -> str:
    text = _strip_question_prefix(text)
    text = _strip_answer_prefix(text)
    return text.strip()


def _strip_question_prefix(text: str) -> str:
    text = QUESTION_PREFIX_RE.sub(r"\1", text)
    text = NUMBERED_PREFIX_RE.sub(r"\1", text)
    text = re.sub(r"^[0-9]+[.、)]\s*", "", text)
    return text.strip()


def _strip_answer_prefix(text: str) -> str:
    return ANSWER_PREFIX_RE.sub(r"\1", text).strip()


def _strip_trailing_chrome(text: str) -> str:
    cleaned = normalize_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(
        r"(?:首页|返回顶部|咨询电话|版权所有|网站所有|个人中心)(?:\s*(?:首页|返回顶部|咨询电话|版权所有|网站所有|个人中心))*\s*$",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:<<|>>|<|>)\s*$", "", cleaned)
    return normalize_text(cleaned).strip()


def _table_is_stable(columns: list[str], rows: list[list[str]]) -> bool:
    if len(columns) < 2 or len(rows) < 1:
        return False

    normalized_rows = [[str(cell).strip() for cell in row] for row in rows]
    widths = [len([cell for cell in row if cell]) for row in normalized_rows[: min(len(normalized_rows), 6)]]
    if any(width < 2 for width in widths):
        return False
    if len(set(widths)) > 2:
        return False
    if sum(1 for row in normalized_rows if len([cell for cell in row if cell]) >= len(columns)) < max(1, len(normalized_rows) // 2):
        return False
    if sum(1 for row in normalized_rows if _row_looks_like_qa(row)) > 0:
        return False
    return True


def _row_looks_like_qa(row: list[str]) -> bool:
    row_text = "\n".join(cell for cell in row if cell)
    return has_question_answer_structure(row_text)


def _build_overlap(current: list[str], overlap: int) -> list[str]:
    if not current or overlap <= 0:
        return []
    overlap_parts: list[str] = []
    overlap_len = 0
    for paragraph in reversed(current):
        overlap_parts.insert(0, paragraph)
        overlap_len += len(paragraph)
        if overlap_len >= overlap:
            break
    return overlap_parts


def _split_long_paragraph(paragraph: str, *, chunk_size: int) -> list[str]:
    sentences = re.split(r"(?<=[。！？!?；;])", paragraph)
    sentences = [sentence.strip() for sentence in sentences if sentence.strip()]
    if not sentences:
        return [paragraph]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(sentence.strip())
            continue
        if current and len(current) + len(sentence) > chunk_size:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current}{sentence}" if current else sentence
    if current:
        chunks.append(current.strip())
    return chunks
