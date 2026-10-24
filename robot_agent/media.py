"""Media artifacts the web UI can preview: images, short videos and point clouds.

Robot tools announce files with one line per file, e.g. ``IMAGE: artifacts/captures/x.jpg``,
``VIDEO: artifacts/videos/clip.mp4`` or ``POINTCLOUD: artifacts/maps/lab.pcd``. The kind shown
in the UI is decided by the file extension, so any of the prefixes works for any file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ARTIFACT_DIRS = ("captures", "maps", "videos", "pointclouds")
KINDS = {
    "jpg": "image", "jpeg": "image", "png": "image", "gif": "image", "webp": "image",
    "mp4": "video", "webm": "video",
    "pcd": "pointcloud", "ply": "pointcloud",
}

_EXT = "|".join(KINDS)
NAME_RE = re.compile(rf"[\w.\-]+\.({_EXT})", re.I)
MEDIA_LINE = re.compile(
    rf"^(?:IMAGE|VIDEO|POINTCLOUD|MEDIA):\s*(artifacts/(?:{'|'.join(ARTIFACT_DIRS)})/[\w.\-]+\.(?:{_EXT}))\s*$",
    re.M | re.I)


def kind_of(name: str) -> str | None:
    match = NAME_RE.fullmatch(name)
    return KINDS[match.group(1).lower()] if match else None


def media_item(path: Path, project_dir: Path) -> dict[str, Any]:
    rel = path.relative_to(project_dir).as_posix()
    stat = path.stat()
    return {"url": "/" + rel, "kind": kind_of(path.name), "name": path.name,
            "dir": path.parent.name, "size": stat.st_size, "mtime": stat.st_mtime}


def media_in_output(text: str, project_dir: Path) -> list[dict[str, Any]]:
    """Media files announced in tool output that exist on disk, without duplicates."""
    seen, items = set(), []
    for rel in MEDIA_LINE.findall(text):
        path = project_dir / rel
        if rel not in seen and path.is_file():
            seen.add(rel)
            items.append(media_item(path, project_dir))
    return items


def list_media(project_dir: Path, limit: int = 300) -> list[dict[str, Any]]:
    """Newest media files under artifacts/, newest first."""
    files = []
    for sub in ARTIFACT_DIRS:
        folder = project_dir / "artifacts" / sub
        if folder.is_dir():
            files += [p for p in folder.iterdir() if p.is_file() and kind_of(p.name)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [media_item(p, project_dir) for p in files[:limit]]
