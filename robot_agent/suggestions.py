"""Custom suggested prompts for the web UI welcome screen, per UI language.

Languages without a saved list use the built-in prompts in index.html. The lists are kept on
the server so every operator of the robot sees the same prompts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LANGS = ("en", "zh")
MAX_ITEMS = 24
MAX_LABEL = 40
MAX_TEXT = 1000


class SuggestionStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, list[dict[str, str]]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {lang: items for lang, items in data.items()
                if lang in LANGS and isinstance(items, list)}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def set(self, lang: str, items: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
        data = self.load()
        data[lang] = items
        self._save(data)
        return data

    def reset(self, lang: str) -> dict[str, list[dict[str, str]]]:
        data = self.load()
        if data.pop(lang, None) is not None:
            self._save(data)
        return data
