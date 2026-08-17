from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SkillRecord:
    name: str
    description: str
    content: str


class SkillRegistry:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parents[1] / "runtime_skills"
        self.skills = self._scan()

    def catalog_text(self) -> str:
        if not self.skills:
            return "(no skills registered)"
        return "\n".join(
            f"- {item.name}: {item.description}" for item in self.skills.values()
        )

    def load(self, name: str) -> SkillRecord | None:
        return self.skills.get(name)

    def _scan(self) -> dict[str, SkillRecord]:
        records: dict[str, SkillRecord] = {}
        if not self.base_dir.exists():
            return records
        for manifest in sorted(self.base_dir.glob("*/SKILL.md")):
            raw = manifest.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(raw)
            name = str(meta.get("name") or manifest.parent.name)
            desc = str(meta.get("description") or _first_heading(body) or name)
            records[name] = SkillRecord(name=name, description=desc, content=raw)
        return records


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, parts[2].strip()


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""
