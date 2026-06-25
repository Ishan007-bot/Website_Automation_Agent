"""Controller — executes the LLM's high-level actions by reducing them to the
required primitive tools.

This is where the index→coordinate bridge happens: the LLM says click(5); we look
up element 5's center in the SelectorMap and call the primitive click_on_screen(x, y).
Every action returns a short human-readable result string that is fed back to the
LLM as the observation for its next step.
"""
from __future__ import annotations

import logging
from typing import Protocol

from agent.views import Action
from browser.dom_service import DomState
from tools.actions import Tools

logger = logging.getLogger("agent")


class LLM(Protocol):
    """The minimal LLM surface the controller needs — satisfied by both the
    Groq and Gemini clients, so neither SDK is imported here."""

    async def extract(self, instruction: str, content: str) -> str: ...


class ActionResult:
    def __init__(self, message: str, is_done: bool = False, success: bool = False,
                 extracted: str | None = None):
        self.message = message
        self.is_done = is_done
        self.success = success
        self.extracted = extracted


class Controller:
    def __init__(self, tools: Tools, llm: LLM, task: str = "") -> None:
        self.tools = tools
        self.llm = llm
        self.task = task

    async def execute(self, action: Action, dom: DomState) -> ActionResult:
        name = (action.name or "").strip().lower()
        try:
            return await self._dispatch(name, action, dom)
        except Exception as exc:  # noqa: BLE001 - surface errors to the agent, don't crash
            logger.warning("Action %s failed: %s", name, exc)
            return ActionResult(f"action '{name}' raised an error: {exc}")

    async def _dispatch(self, name: str, action: Action, dom: DomState) -> ActionResult:
        if name == "navigate":
            if not action.url:
                return ActionResult("navigate requires a url")
            return ActionResult(await self.tools.navigate_to_url(action.url))

        if name in ("click", "double_click"):
            el = self._resolve(action, dom)
            if el is None:
                return ActionResult(
                    f"no element with index {action.index}; the page may have changed — re-checking elements"
                )
            if name == "click":
                await self.tools.click_on_screen(el.x, el.y)
            else:
                await self.tools.double_click(el.x, el.y)
            return ActionResult(f"{name} on [{el.index}] {el.descriptor()}")

        if name == "input_text":
            el = self._resolve(action, dom)
            if el is None:
                return ActionResult(f"no element with index {action.index}; re-checking elements")
            if action.text is None:
                return ActionResult("input_text requires text")
            # Focus the field, select-all, then type — robust against pre-filled values.
            await self.tools.click_on_screen(el.x, el.y)
            await self.tools.press_key("Control+A")
            await self.tools.press_key("Delete")
            await self.tools.send_keys(action.text)
            return ActionResult(f'typed "{action.text}" into [{el.index}] {el.descriptor()}')

        if name == "send_keys":
            if not action.keys:
                return ActionResult("send_keys requires keys")
            await self.tools.press_key(action.keys)
            return ActionResult(f"pressed {action.keys}")

        if name == "scroll":
            amount = action.amount or 600
            dy = -amount if (action.direction or "down").lower() == "up" else amount
            await self.tools.scroll(0, dy)
            return ActionResult(f"scrolled {'up' if dy < 0 else 'down'} {abs(dy)}px")

        if name == "extract_content":
            content = await self.tools.session.get_page_content()
            goal = action.goal or "the information relevant to the task"
            extracted = await self.llm.extract(
                f"From the page content below, extract: {goal}. Be precise and include all items. "
                "When the task needs a link/URL, return the EXACT absolute URL from the LINKS "
                "section verbatim — never guess, shorten, or invent a URL.",
                content,
            )
            return ActionResult(f"extracted content for goal '{goal}'", extracted=extracted)

        if name == "wait":
            secs = action.seconds or 2
            await self.tools.session.settle(int(secs * 1000))
            return ActionResult(f"waited {secs}s")

        if name == "go_back":
            await self.tools.session.go_back()
            return ActionResult("navigated back")

        if name == "done":
            text = (action.text or "").strip()
            # Guard: the model often finishes without writing the answer. Rather than
            # bounce it back (which can loop), synthesize the answer from the page so
            # the user always gets a real result.
            if not text:
                content = await self.tools.session.get_page_content()
                text = await self.llm.extract(
                    f"The user's task was: {self.task}\n"
                    "Write the final answer for the user. If the task asked for information, "
                    "list it completely and concisely. If it asked for a link/URL, return the "
                    "EXACT absolute URL from the LINKS section verbatim — never invent one. "
                    "If it was an action, summarize what was done.",
                    content,
                )
            return ActionResult(text or "Task finished.", is_done=True, success=bool(action.success))

        return ActionResult(f"unknown action '{name}' — ignored")

    @staticmethod
    def _resolve(action: Action, dom: DomState):
        if action.index is None:
            return None
        return dom.selector_map.get(action.index)
