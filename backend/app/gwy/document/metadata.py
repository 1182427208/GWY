from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DOC_TYPE_RULES: list[tuple[str, str]] = [
    ("\u4fe1\u606f\u4fee\u6539", "info_modify"),
    ("\u804c\u4f4d\u586b\u62a5", "position_fill"),
    ("\u8d44\u683c\u5ba1\u67e5\u72b6\u6001\u67e5\u770b", "qualification_status"),
    ("\u62a5\u540d\u786e\u8ba4", "registration_confirmation"),
    ("\u62a5\u540d\u5e8f\u53f7", "registration_number"),
    ("\u51c6\u8003\u8bc1", "admission_ticket"),
    ("\u6210\u7ee9", "score_query"),
    ("\u62a5\u8003\u6761\u4ef6", "application_conditions"),
    ("\u5173\u4e8e\u62a5\u540d", "registration_policy"),
    ("\u62a5\u540d\u6307\u5357", "registration_policy"),
    ("\u62a5\u8003\u6307\u5357", "registration_policy"),
    ("\u5173\u4e8e\u7b14\u8bd5", "written_exam"),
    ("\u5173\u4e8e\u9762\u8bd5", "interview"),
    ("\u4f53\u68c0\u548c\u8003\u5bdf", "physical_exam_and_inspection"),
    ("\u4f53\u68c0", "physical_exam_and_inspection"),
    ("\u8fdd\u7eaa\u8fdd\u89c4", "discipline"),
    ("\u8d44\u683c\u5ba1\u67e5", "qualification_review"),
    ("\u516c\u5171\u79d1\u76ee\u8003\u8bd5\u5927\u7eb2", "public_subject_outline"),
    ("\u4e13\u4e1a\u76ee\u5f55", "major_catalog"),
    ("\u516c\u544a", "recruitment_announcement"),
]


def infer_policy_metadata(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    stem = path.stem
    year = _infer_year(str(path)) or 2026
    doc_group = _infer_doc_group(path, stem)
    doc_type = _infer_doc_type(stem, doc_group)

    return {
        "year": year,
        "exam_type": "national",
        "province": "national",
        "doc_group": doc_group,
        "doc_type": doc_type,
        "doc_title": _clean_title(stem),
        "source_file": str(path),
        "source": "official",
    }


def _infer_year(text: str) -> int | None:
    match = re.search(r"(20\d{2})", text)
    if not match:
        return None
    return int(match.group(1))


def _infer_doc_group(path: Path, stem: str) -> str:
    parts = [part for part in path.parts if part]
    if any("\u6280\u672f\u95ee\u7b54" in part for part in parts):
        return "technical_qa"
    if any("\u8003\u52a1\u95ee\u7b54" in part for part in parts):
        return "exam_affairs_qa"
    if any("\u653f\u7b56\u95ee\u7b54" in part for part in parts):
        return "policy_qa"
    if any("\u4e13\u4e1a\u76ee\u5f55" in part for part in parts):
        return "major_catalog"

    if "\u516c\u544a" in stem:
        return "announcement"
    if "\u5927\u7eb2" in stem or "\u4e13\u9898" in stem:
        return "exam_outline"
    if "\u4e13\u4e1a\u76ee\u5f55" in stem:
        return "major_catalog"
    if "\u8003\u52a1" in stem:
        return "exam_affairs_qa"
    if "\u6280\u672f" in stem:
        return "technical_qa"
    return "policy_qa"


def _infer_doc_type(stem: str, doc_group: str) -> str:
    for keyword, doc_type in DOC_TYPE_RULES:
        if keyword in stem:
            return doc_type

    if doc_group == "announcement":
        return "recruitment_announcement"
    if doc_group == "exam_outline":
        if "\u516c\u5171\u79d1\u76ee" in stem:
            return "public_subject_outline"
        return "other_policy"
    if doc_group == "major_catalog":
        return "major_catalog"
    return "other_policy"


def _clean_title(stem: str) -> str:
    title = re.sub(r"^(20\d{2})[_\- ]*", "", stem)
    title = title.replace("_", " ").strip()
    return title or stem
