"""Async Groq client — a drop-in alternative to GeminiClient.

Exposes the SAME interface the agent/controller already use:
  * generate_structured(system, prompt, schema) -> validated pydantic instance
  * extract(instruction, content) -> free-form text

Two things make this robust for a live demo:

  1. MULTIPLE API KEYS as fallbacks. Groq's free tier is rate-limited; when the
     active key returns a 429 / rate-limit / quota error we rotate to the next key
     and retry, so one exhausted key doesn't end the run.
  2. SCHEMA via prompt + JSON mode. Groq's Llama models support `json_object`
     (valid JSON) but not strict json_schema, so we embed the schema in the prompt
     and validate the result with pydantic — retrying (and rotating keys) on any
     failure. The same exponential backoff as the Gemini client applies.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Type, TypeVar

from groq import AsyncGroq
from pydantic import BaseModel

from config import settings

logger = logging.getLogger("agent")

T = TypeVar("T", bound=BaseModel)

# Substrings that mark an error as a rate-limit/quota problem -> rotate the key.
_RATE_LIMIT_MARKERS = ("429", "rate", "quota", "resource_exhausted", "too many requests")
# Substrings that mark an error as transient -> back off and retry (same key).
_TRANSIENT_MARKERS = _RATE_LIMIT_MARKERS + ("503", "500", "502", "unavailable", "timeout", "deadline")


class GroqClient:
    def __init__(self) -> None:
        self.keys = list(settings.groq_api_keys)
        if not self.keys:
            raise RuntimeError(
                "No Groq API key set. Add GROQ_API_KEY (and optionally GROQ_API_KEY_2) "
                "to .env, or set LLM_PROVIDER=gemini to use Gemini instead."
            )
        self.model = settings.groq_model
        self._key_idx = 0
        # One client per key, created lazily.
        self._clients: dict[int, AsyncGroq] = {}
        logger.info("Groq client ready: model=%s, %d key(s) available", self.model, len(self.keys))

    def _client(self) -> AsyncGroq:
        if self._key_idx not in self._clients:
            self._clients[self._key_idx] = AsyncGroq(api_key=self.keys[self._key_idx])
        return self._clients[self._key_idx]

    def _rotate_key(self) -> bool:
        """Advance to the next key. Returns False if there isn't one."""
        if self._key_idx + 1 < len(self.keys):
            self._key_idx += 1
            logger.warning("Rotating to Groq API key #%d (rate-limited)", self._key_idx + 1)
            return True
        return False

    async def generate_structured(
        self,
        system_instruction: str,
        user_prompt: str,
        schema: Type[T],
        max_retries: int = 4,
    ) -> T:
        """Return an instance of `schema`, rotating keys on rate limits."""
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        system = (
            f"{system_instruction}\n\n"
            "You MUST reply with a single JSON object — no prose, no markdown fences — "
            "that conforms to this JSON Schema:\n"
            f"{schema_json}"
        )

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self._client().chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=8192,
                )
                content = resp.choices[0].message.content or ""
                return schema.model_validate_json(content)
            except Exception as exc:  # noqa: BLE001 - classified below
                last_exc = exc
                if not await self._after_error(exc, attempt, max_retries):
                    break
        raise RuntimeError(f"Groq call failed after {max_retries} attempts: {last_exc}")

    async def extract(self, instruction: str, content: str, max_retries: int = 3) -> str:
        """Free-form text generation, used by the extract_content / done actions."""
        prompt = f"{instruction}\n\n--- PAGE CONTENT ---\n{content[:28000]}"
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self._client().chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not await self._after_error(exc, attempt, max_retries):
                    break
        logger.warning("Groq extract() failed: %s", last_exc)
        return "(extraction failed)"

    async def _after_error(self, exc: Exception, attempt: int, max_retries: int) -> bool:
        """Decide what to do after a failed call, sleeping if a backoff is needed.

        On a rate-limit error, rotate to the next key and retry immediately (a
        fresh key is usable right away). On other transient errors, back off
        exponentially. Returns True if another attempt should be made.
        """
        msg = str(exc).lower()
        is_rate_limit = any(k in msg for k in _RATE_LIMIT_MARKERS)
        is_transient = any(k in msg for k in _TRANSIENT_MARKERS)

        if is_rate_limit and self._rotate_key():
            return True  # retry immediately on the fresh key, no wait

        logger.warning(
            "Groq call failed (attempt %d/%d)%s: %s",
            attempt + 1,
            max_retries,
            " [transient, backing off]" if is_transient else "",
            exc,
        )
        if attempt >= max_retries - 1:
            return False
        await asyncio.sleep(min(2 ** attempt, 30) if is_transient else 1)
        return True
