"""Thin async wrapper around the google-genai SDK.

Responsibilities:
  * Configure the client from settings (api key, optional gateway base_url).
  * Force structured JSON output against a pydantic schema (response_schema).
  * Retry on transient/rate-limit errors with exponential backoff — important
    because Flash-Lite tiers have tight RPM/RPD limits.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Type, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from config import settings

logger = logging.getLogger("agent")

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        http_options = (
            types.HttpOptions(base_url=settings.gemini_base_url)
            if settings.gemini_base_url
            else None
        )
        self.client = genai.Client(api_key=settings.gemini_api_key, http_options=http_options)
        self.model = settings.gemini_model

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        schema: Type[T],
        max_retries: int = 4,
    ) -> T:
        """Return an instance of `schema`, retrying transient failures."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.2,
            # Bound the response so a degenerate generation can't blow up into an
            # unparseable multi-thousand-line blob; plenty for an action decision.
            max_output_tokens=8192,
        )

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )
                # SDK parses response_schema into .parsed when possible.
                parsed = getattr(resp, "parsed", None)
                if isinstance(parsed, schema):
                    return parsed
                # Fallback: validate the raw JSON text ourselves.
                return schema.model_validate_json(resp.text)
            except Exception as exc:  # noqa: BLE001 - we classify below
                last_exc = exc
                msg = str(exc).lower()
                transient = any(
                    k in msg
                    for k in ("429", "rate", "quota", "resource_exhausted", "503", "500", "unavailable", "timeout", "deadline")
                )
                wait = min(2 ** attempt, 30)
                logger.warning(
                    "Gemini call failed (attempt %d/%d)%s: %s",
                    attempt + 1,
                    max_retries,
                    " [transient, backing off]" if transient else "",
                    exc,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(wait if transient else 1)

        raise RuntimeError(f"Gemini call failed after {max_retries} attempts: {last_exc}")

    async def extract(self, instruction: str, content: str, max_retries: int = 3) -> str:
        """Free-form text generation, used by the extract_content action."""
        config = types.GenerateContentConfig(temperature=0.1)
        prompt = f"{instruction}\n\n--- PAGE CONTENT ---\n{content[:28000]}"
        for attempt in range(max_retries):
            try:
                resp = await self.client.aio.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return resp.text or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning("extract() failed (attempt %d): %s", attempt + 1, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(min(2 ** attempt, 15))
        return "(extraction failed)"
