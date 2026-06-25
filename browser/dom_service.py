"""DomService — runs buildDomTree.js inside the page and turns the result into a
typed, indexed element map the agent reasons over.

The SelectorMap (index -> DomElement) is the bridge between the LLM's
"click element 5" and the controller's click_on_screen(x, y): each DomElement
carries the viewport-relative center coordinates needed for the primitive tools.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from browser.session import BrowserSession

logger = logging.getLogger("agent")

_JS_PATH = os.path.join(os.path.dirname(__file__), "buildDomTree.js")
with open(_JS_PATH, "r", encoding="utf-8") as _f:
    _BUILD_DOM_TREE_JS = _f.read()


@dataclass
class DomElement:
    index: int
    tag: str
    type: str
    text: str
    placeholder: str
    aria_label: str
    name: str
    value: str
    label: str
    x: int
    y: int
    width: int
    height: int
    in_viewport: bool

    def descriptor(self) -> str:
        """Compact one-line description shown to the LLM."""
        # Prefer the most human-meaningful identifier available.
        bits: list[str] = []
        meaning = self.label or self.aria_label or self.text or self.placeholder
        if meaning:
            bits.append(meaning[:80])
        if self.type:
            bits.append(f"type={self.type}")
        if self.value:
            bits.append(f'value="{self.value[:40]}"')
        elif self.placeholder and self.placeholder != meaning:
            bits.append(f'placeholder="{self.placeholder[:40]}"')
        inner = " ".join(bits) if bits else ""
        marker = "" if self.in_viewport else " (scroll to reach)"
        return f"[{self.index}]<{self.tag}> {inner}{marker}".rstrip()


@dataclass
class DomState:
    elements: list[DomElement]
    selector_map: dict[int, DomElement]
    scroll_x: int
    scroll_y: int
    scroll_max_y: int

    def elements_text(self) -> str:
        if not self.elements:
            return "(no interactive elements detected)"
        return "\n".join(e.descriptor() for e in self.elements)


class DomService:
    def __init__(self, session: BrowserSession) -> None:
        self.session = session

    async def get_state(self, draw_highlights: bool = True) -> DomState:
        """Inject the JS, parse the result, and build the SelectorMap."""
        page = self.session._require_page()
        try:
            raw = await page.evaluate(_BUILD_DOM_TREE_JS, {"drawHighlights": draw_highlights})
        except Exception as exc:
            logger.warning("buildDomTree evaluation failed: %s", exc)
            raw = {"elements": [], "scroll": {"x": 0, "y": 0, "maxY": 0}}

        elements: list[DomElement] = []
        for e in raw.get("elements", []):
            elements.append(
                DomElement(
                    index=e["index"],
                    tag=e.get("tag", ""),
                    type=e.get("type", ""),
                    text=e.get("text", ""),
                    placeholder=e.get("placeholder", ""),
                    aria_label=e.get("ariaLabel", ""),
                    name=e.get("name", ""),
                    value=e.get("value", ""),
                    label=e.get("label", ""),
                    x=e.get("x", 0),
                    y=e.get("y", 0),
                    width=e.get("width", 0),
                    height=e.get("height", 0),
                    in_viewport=e.get("inViewport", True),
                )
            )

        scroll = raw.get("scroll", {})
        return DomState(
            elements=elements,
            selector_map={e.index: e for e in elements},
            scroll_x=int(scroll.get("x", 0)),
            scroll_y=int(scroll.get("y", 0)),
            scroll_max_y=int(scroll.get("maxY", 0)),
        )
