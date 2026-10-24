"""Manage the project's robot skills (``.claude/skills/<name>/SKILL.md``) from the web UI.

A disabled skill is moved to ``.claude/skills-disabled/<name>/``, where neither the agent nor
Claude Code looks for skills; enabling moves it back. Each skill folder may hold more files
than SKILL.md, so enable, disable and delete act on the whole folder.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ENABLED_DIR = Path(".claude") / "skills"
DISABLED_DIR = Path(".claude") / "skills-disabled"
SKILL_FILE = "SKILL.md"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MAX_SKILL_BYTES = 64_000
FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


class SkillError(ValueError):
    """A request the UI should show as a clear message (bad name, invalid file, conflict)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _roots(project_dir: Path) -> tuple[Path, Path]:
    return project_dir / ENABLED_DIR, project_dir / DISABLED_DIR


def check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name or ""):
        raise SkillError("Skill names use 1-64 lowercase letters, digits and '-', starting with "
                         "a letter or digit.")
    return name


def frontmatter(content: str) -> dict[str, Any]:
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def validate(name: str, content: str) -> None:
    if len(content.encode("utf-8")) > MAX_SKILL_BYTES:
        raise SkillError(f"SKILL.md is larger than {MAX_SKILL_BYTES // 1000} KB.")
    if not FRONTMATTER_RE.match(content):
        raise SkillError("SKILL.md must start with a front matter block: '---', 'name: ...', "
                         "'description: ...', '---'.")
    meta = frontmatter(content)
    if not meta:
        raise SkillError("The front matter is not valid YAML.")
    if meta.get("name") != name:
        raise SkillError(f"The front matter 'name' must be {name!r} (the skill's folder name).")
    if not isinstance(meta.get("description"), str) or not meta["description"].strip():
        raise SkillError("The front matter needs a 'description' - the agent uses it to decide "
                         "when to load the skill.")


def _locate(project_dir: Path, name: str) -> tuple[Path, bool]:
    """(folder, enabled) of an existing skill."""
    check_name(name)
    enabled_root, disabled_root = _roots(project_dir)
    for root, enabled in ((enabled_root, True), (disabled_root, False)):
        folder = root / name
        if (folder / SKILL_FILE).is_file():
            return folder, enabled
    raise SkillError(f"No skill named {name!r}.", 404)


def _info(folder: Path, enabled: bool) -> dict[str, Any]:
    path = folder / SKILL_FILE
    content = path.read_text(encoding="utf-8", errors="replace")
    stat = path.stat()
    return {"name": folder.name, "description": str(frontmatter(content).get("description", "")),
            "enabled": enabled, "size": stat.st_size,
            "updatedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}


def list_skills(project_dir: Path) -> list[dict[str, Any]]:
    enabled_root, disabled_root = _roots(project_dir)
    skills: dict[str, dict[str, Any]] = {}
    for root, enabled in ((disabled_root, False), (enabled_root, True)):
        for path in sorted(root.glob(f"*/{SKILL_FILE}")):
            if NAME_RE.fullmatch(path.parent.name):
                skills[path.parent.name] = _info(path.parent, enabled)
    return sorted(skills.values(), key=lambda s: s["name"])


def read_skill(project_dir: Path, name: str) -> dict[str, Any]:
    folder, enabled = _locate(project_dir, name)
    return {**_info(folder, enabled),
            "content": (folder / SKILL_FILE).read_text(encoding="utf-8", errors="replace")}


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def create_skill(project_dir: Path, name: str, content: str) -> dict[str, Any]:
    check_name(name)
    try:
        _locate(project_dir, name)
    except SkillError as exc:
        if exc.status != 404:
            raise
    else:
        raise SkillError(f"A skill named {name!r} already exists.", 409)
    validate(name, content)
    _write(_roots(project_dir)[0] / name / SKILL_FILE, content)
    return read_skill(project_dir, name)


def update_skill(project_dir: Path, name: str, content: str) -> dict[str, Any]:
    folder, _ = _locate(project_dir, name)
    validate(name, content)
    _write(folder / SKILL_FILE, content)
    return read_skill(project_dir, name)


def set_enabled(project_dir: Path, name: str, enabled: bool) -> dict[str, Any]:
    folder, is_enabled = _locate(project_dir, name)
    if is_enabled != enabled:
        target = _roots(project_dir)[0 if enabled else 1] / name
        if target.exists():
            raise SkillError(f"{target.relative_to(project_dir)} already exists.", 409)
        target.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(target)
    return read_skill(project_dir, name)


def delete_skill(project_dir: Path, name: str) -> None:
    folder, _ = _locate(project_dir, name)
    shutil.rmtree(folder)
