"""Central configuration, loaded once from environment / .env.

Every tunable (credentials, model id, browser flags, agent limits) is read here
so the rest of the codebase never touches os.environ directly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env from the project root (no-op if the file is absent).
load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _get_keys(*names: str) -> tuple[str, ...]:
    """Collect non-empty API keys from the given env var names, in order, deduped.

    Lets you provide GROQ_API_KEY plus GROQ_API_KEY_2 (etc.) as ordered fallbacks.
    """
    keys: list[str] = []
    for name in names:
        val = os.getenv(name, "").strip()
        if val and val not in keys:
            keys.append(val)
    return tuple(keys)


@dataclass(frozen=True)
class Settings:
    # --- Provider selection ---
    provider: str  # "groq" or "gemini"

    # --- Gemini ---
    gemini_api_key: str
    gemini_model: str
    gemini_base_url: str | None

    # --- Groq (supports multiple keys for rate-limit fallback) ---
    groq_api_keys: tuple[str, ...]
    groq_model: str

    # --- Browser ---
    headless: bool
    viewport_width: int
    viewport_height: int

    # --- Agent ---
    max_steps: int
    action_timeout_ms: int

    @classmethod
    def load(cls) -> "Settings":
        base_url = os.getenv("GEMINI_BASE_URL", "").strip()
        return cls(
            provider=os.getenv("LLM_PROVIDER", "groq").strip().lower() or "groq",
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip(),
            gemini_base_url=base_url or None,
            groq_api_keys=_get_keys("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
            headless=_get_bool("HEADLESS", False),
            viewport_width=_get_int("VIEWPORT_WIDTH", 1280),
            viewport_height=_get_int("VIEWPORT_HEIGHT", 800),
            max_steps=_get_int("MAX_STEPS", 25),
            action_timeout_ms=_get_int("ACTION_TIMEOUT_MS", 15000),
        )


# Singleton used across the app.
settings = Settings.load()
