from __future__ import annotations

import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"


def load_local_env(path: Path | None = None) -> None:
    """Load simple KEY=VALUE entries from .env without overriding shell env vars."""
    if os.getenv("TASKRADAR_DISABLE_ENV_FILE", "").lower() in ("1", "true", "yes", "on"):
        return

    env_path = path or ENV_PATH
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def configured_provider_label() -> str:
    load_local_env()
    if _truthy_env("TASKRADAR_USE_OPENCODE"):
        command = os.getenv("TASKRADAR_OPENCODE_COMMAND", "opencode")
        if not _command_exists(command):
            return "AI 설정 확인 필요 · opencode 실행 파일 없음"
        if is_debug_mode():
            model = os.getenv("TASKRADAR_OPENCODE_MODEL", "anthropic/claude-haiku-4-5")
            required = " · opencode 필수" if _truthy_env("TASKRADAR_REQUIRE_OPENCODE") else ""
            return f"AI 분석 준비됨 · opencode OAuth{required} · 모델: {model}"
        return "AI 분석 준비됨"
    if os.getenv("OPENAI_API_KEY"):
        if is_debug_mode():
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            return f"AI 분석 준비됨 · OpenAI · 모델: {model}"
        return "AI 분석 준비됨"
    if os.getenv("ANTHROPIC_API_KEY"):
        if is_debug_mode():
            model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
            return f"AI 분석 준비됨 · Anthropic · 모델: {model}"
        return "AI 분석 준비됨"
    if os.getenv("GEMMA_API_URL"):
        return "AI 분석 준비됨"
    return "AI 설정 없음 · 임시 분석 모드"


def is_debug_mode() -> bool:
    return _truthy_env("TASKRADAR_DEBUG")


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").lower() in ("1", "true", "yes", "on")


def _command_exists(command: str) -> bool:
    if os.path.isabs(command) or os.sep in command or (os.altsep and os.altsep in command):
        return Path(command).exists()
    return shutil.which(command) is not None
