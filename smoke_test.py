"""LLM smoke test — confirms the configured provider's key(s), model id, and
structured output are working, BEFORE launching the browser.

Honors LLM_PROVIDER (groq | gemini). Run:  python smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys

# Windows consoles default to cp1252 and choke on the ✅ glyph below. Force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from pydantic import BaseModel

from config import settings
from llm.factory import make_llm


class Ping(BaseModel):
    ok: bool
    message: str


async def main() -> None:
    provider = settings.provider
    if provider == "groq":
        model = settings.groq_model
        keys = f"{len(settings.groq_api_keys)} key(s)" if settings.groq_api_keys else "MISSING"
    else:
        model = settings.gemini_model
        keys = "set" if settings.gemini_api_key else "MISSING"

    print(f"Provider  : {provider}")
    print(f"Model     : {model}")
    print(f"API key(s): {keys}\n")

    client = make_llm()
    result = await client.generate_structured(
        system_instruction="You are a connectivity tester. Always reply in the required JSON.",
        user_prompt=f'Reply with ok=true and message="{provider} structured output is working".',
        schema=Ping,
    )
    print("Structured response:", result.model_dump())
    print(f"\n✅ {provider} is reachable and structured output works.")


if __name__ == "__main__":
    asyncio.run(main())
