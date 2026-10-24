"""Robot agent web server settings (environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    project_dir: Path = PROJECT_DIR
    model: str = field(default_factory=lambda: os.environ.get("CC_MODEL", "claude-opus-5.5"))
    gateway_url: str = field(
        default_factory=lambda: os.environ.get("CC_BASE_URL", "http://127.0.0.1:43783"))
    gateway_token: str = field(
        default_factory=lambda: os.environ.get("CC_AUTH_TOKEN", "sk-cc-github-litellm"))
    max_turns: int = field(default_factory=lambda: int(os.environ.get("CC_MAX_TURNS", "40")))
    approval_timeout: int = field(
        default_factory=lambda: int(os.environ.get("ROBOT_APPROVAL_TIMEOUT", "120")))
    # When set, the API, WebSocket and artifacts require this token (?token= or X-Robot-Token).
    access_token: str = field(default_factory=lambda: os.environ.get("ROBOT_AGENT_TOKEN", ""))
    # Chats and Claude transcripts are saved here and restored when the server restarts.
    sessions_dir: Path = field(default_factory=lambda: Path(
        os.environ.get("ROBOT_SESSIONS_DIR") or PROJECT_DIR / ".claude" / "sessions"))

    def agent_env(self) -> dict[str, str]:
        return {
            "ANTHROPIC_BASE_URL": self.gateway_url,
            "ANTHROPIC_AUTH_TOKEN": self.gateway_token,
            "ANTHROPIC_API_KEY": "",
            # Used by `./robot camera look` to describe images.
            "ROBOT_VISION_MODEL": os.environ.get("ROBOT_VISION_MODEL", self.model),
        }
