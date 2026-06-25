"""Picks the LLM client based on LLM_PROVIDER.

Both clients expose the same interface (generate_structured / extract), so the
rest of the app just calls make_llm() and never cares which backend is active.
"""
from __future__ import annotations

from config import settings


def make_llm():
    """Return the configured LLM client (Groq by default, or Gemini)."""
    if settings.provider == "gemini":
        from llm.gemini import GeminiClient

        return GeminiClient()
    if settings.provider == "groq":
        from llm.groq_client import GroqClient

        return GroqClient()
    raise RuntimeError(
        f"Unknown LLM_PROVIDER '{settings.provider}'. Use 'groq' or 'gemini'."
    )
