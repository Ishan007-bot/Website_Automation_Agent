"""Primitive tools — the exact capabilities the assignment requires.

Each is a thin, logged, error-handled wrapper over BrowserSession. They are the
only things that actually touch the browser; everything higher up (the controller,
the agent) composes these. This keeps the tool surface small, testable, and an
obvious 1:1 match to the assignment checklist:

    open_browser, navigate_to_url, take_screenshot,
    click_on_screen(x, y), double_click(x, y), send_keys, scroll
"""
from __future__ import annotations

import logging

from browser.session import BrowserSession

logger = logging.getLogger("agent")


class Tools:
    def __init__(self, session: BrowserSession) -> None:
        self.session = session

    async def open_browser(self) -> str:
        await self.session.open_browser()
        return "browser opened"

    async def navigate_to_url(self, url: str) -> str:
        await self.session.navigate_to_url(url)
        return f"navigated to {await self.session.current_url()}"

    async def take_screenshot(self) -> str:
        """Returns base64 PNG of the current viewport."""
        return await self.session.take_screenshot()

    async def click_on_screen(self, x: float, y: float) -> str:
        logger.info("click_on_screen(%s, %s)", x, y)
        await self.session.click_on_screen(x, y)
        return f"clicked at ({x}, {y})"

    async def double_click(self, x: float, y: float) -> str:
        logger.info("double_click(%s, %s)", x, y)
        await self.session.double_click(x, y)
        return f"double-clicked at ({x}, {y})"

    async def send_keys(self, text: str) -> str:
        logger.info("send_keys(%r)", text)
        await self.session.send_keys(text)
        return f"typed {len(text)} chars"

    async def press_key(self, key: str) -> str:
        logger.info("press_key(%s)", key)
        await self.session.press_key(key)
        return f"pressed {key}"

    async def scroll(self, dx: int = 0, dy: int = 0) -> str:
        logger.info("scroll(dx=%s, dy=%s)", dx, dy)
        await self.session.scroll(dx, dy)
        return f"scrolled ({dx}, {dy})"
