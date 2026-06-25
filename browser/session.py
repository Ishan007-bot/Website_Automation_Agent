"""BrowserSession — owns the Playwright browser/page lifecycle and the raw
primitive operations the agent's tools build on.

Uses the async Playwright API so it composes with the asyncio agent loop and the
FastAPI Web-UI without blocking.
"""
from __future__ import annotations

import base64
import logging

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from config import settings

logger = logging.getLogger("agent")


class BrowserSession:
    def __init__(
        self,
        headless: bool | None = None,
        viewport_width: int | None = None,
        viewport_height: int | None = None,
    ) -> None:
        self.headless = settings.headless if headless is None else headless
        self.vw = viewport_width or settings.viewport_width
        self.vh = viewport_height or settings.viewport_height

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    # ── lifecycle ────────────────────────────────────────────────────────
    async def open_browser(self) -> None:
        """Launch Chromium and open a blank page. (Required tool: open_browser)"""
        logger.info("Launching Chromium (headless=%s)", self.headless)
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": self.vw, "height": self.vh},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        self._context.set_default_timeout(settings.action_timeout_ms)
        self.page = await self._context.new_page()

    async def close(self) -> None:
        """Tear everything down. Safe to call multiple times."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            logger.warning("Error during browser teardown: %s", exc)
        finally:
            self._pw = self._browser = self._context = self.page = None

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("Browser not open. Call open_browser() first.")
        return self.page

    # ── navigation & state ───────────────────────────────────────────────
    async def navigate_to_url(self, url: str) -> None:
        """Go to a URL, tolerating slow pages. (Required tool: navigate_to_url)"""
        page = self._require_page()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        logger.info("Navigating to %s", url)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=settings.action_timeout_ms)
        except Exception as exc:
            # domcontentloaded can still time out on heavy SPAs; keep going so the
            # agent can observe whatever rendered rather than crashing.
            logger.warning("Navigation warning for %s: %s", url, exc)
        await self.settle()

    async def settle(self, ms: int = 800) -> None:
        """Small wait for network/render to calm down before snapshotting.

        The networkidle wait is best-effort with a SHORT cap: many real pages
        (analytics, telemetry, fonts) never reach true network-idle, and waiting
        the full timeout on every click/keystroke made each step crawl. 800ms is
        plenty to catch the common "click triggered a quick fetch" case; we never
        block longer than that here.
        """
        page = self._require_page()
        try:
            await page.wait_for_load_state("networkidle", timeout=ms)
        except Exception:
            pass
        await page.wait_for_timeout(min(ms, 400))

    async def current_url(self) -> str:
        return self._require_page().url

    async def title(self) -> str:
        try:
            return await self._require_page().title()
        except Exception:
            return ""

    # ── screenshot (Required tool: take_screenshot) ───────────────────────
    async def take_screenshot(self) -> str:
        """Return the current viewport as a base64 PNG string (no data: prefix).

        The screenshot is only for the live view, never for the agent's logic, so a
        capture failure must NOT abort the run. We disable animations (some sites —
        e.g. the shadcn docs — never reach Playwright's default stability check and
        would otherwise time out) and fall back to an empty string on any error.
        """
        page = self._require_page()
        try:
            png = await page.screenshot(type="png", animations="disabled", timeout=5000)
            return base64.b64encode(png).decode("ascii")
        except Exception as exc:  # pragma: no cover - best-effort, non-critical
            logger.warning("Screenshot failed (continuing without it): %s", exc)
            return ""

    # ── raw input primitives (Required tools) ─────────────────────────────
    async def click_on_screen(self, x: float, y: float) -> None:
        """Mouse click at viewport coordinates. (Required tool: click_on_screen)"""
        page = self._require_page()
        await page.mouse.click(x, y)
        await self.settle(400)

    async def double_click(self, x: float, y: float) -> None:
        """Double click at viewport coordinates. (Required tool: double_click)"""
        page = self._require_page()
        await page.mouse.dblclick(x, y)
        await self.settle(400)

    async def send_keys(self, text: str) -> None:
        """Type literal text at the current focus. (Required tool: send_keys)"""
        await self._require_page().keyboard.type(text, delay=20)

    async def press_key(self, key: str) -> None:
        """Press a named key / chord, e.g. 'Enter', 'Tab', 'Control+A'."""
        await self._require_page().keyboard.press(key)
        await self.settle(300)

    async def scroll(self, dx: int = 0, dy: int = 0) -> None:
        """Scroll the page by a pixel delta. (Required tool: scroll)"""
        await self._require_page().mouse.wheel(dx, dy)
        await self.settle(400)

    async def go_back(self) -> None:
        page = self._require_page()
        try:
            await page.go_back(wait_until="domcontentloaded")
        except Exception as exc:
            logger.warning("go_back failed: %s", exc)
        await self.settle()

    async def get_page_text(self) -> str:
        """Visible text of the page, for content extraction tasks."""
        page = self._require_page()
        try:
            return await page.evaluate("() => document.body.innerText")
        except Exception:
            return ""

    async def get_links(self, limit: int = 120) -> list[dict]:
        """Visible links as {text, href} with ABSOLUTE urls, deduped.

        innerText alone never contains URLs, so for "give me the link" tasks the
        model had nothing real to return and would fabricate one. Surfacing the
        actual hrefs fixes that.
        """
        page = self._require_page()
        try:
            return await page.evaluate(
                """(limit) => {
                  const seen = new Set(); const out = [];
                  for (const a of document.querySelectorAll('a[href]')) {
                    const href = a.href;  // absolute
                    if (!href || href.startsWith('javascript:') || href.startsWith('#')) continue;
                    const text = (a.innerText || a.getAttribute('aria-label') || a.title || '')
                      .trim().replace(/\\s+/g, ' ');
                    if (!text) continue;
                    if (seen.has(href)) continue;
                    seen.add(href);
                    out.push({ text: text.slice(0, 140), href });
                    if (out.length >= limit) break;
                  }
                  return out;
                }""",
                limit,
            )
        except Exception:
            return []

    async def get_page_content(self) -> str:
        """Page text PLUS the list of links — what content/extraction tasks should see.

        Links come first so a long page's text can't truncate them away.
        """
        text = await self.get_page_text()
        links = await self.get_links()
        if not links:
            return text
        links_block = "\n".join(f"- {l['text']} -> {l['href']}" for l in links)
        return (
            "LINKS ON PAGE (anchor text -> absolute URL; use these exact URLs, never invent one):\n"
            f"{links_block}\n\nPAGE TEXT:\n{text}"
        )
