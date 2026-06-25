"""CLI entrypoint.

Examples:
    python main.py "Fill the Bug Title and Description fields" \\
        --url https://ui.shadcn.com/docs/forms/react-hook-form --headed

    python main.py "Find the top 10 trending phones on Flipkart and list them"
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Windows consoles default to cp1252, which can't encode the ✅/──/❌ glyphs we
# print. Force UTF-8 so the live demo renders cleanly on every platform.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from agent.agent import Agent
from browser.session import BrowserSession
from config import settings
from logging_conf import StepEvent, configure_logging


def _print_event(event: StepEvent) -> None:
    """Pretty console renderer for live agent events."""
    if event.type == "step":
        print(f"\n── Step {event.step} " + "─" * 50)
        if event.evaluation:
            print(f"  eval : {event.evaluation}")
        if event.next_goal:
            print(f"  goal : {event.next_goal}")
        for a in event.actions:
            print(f"  act  : {a}")
    elif event.type == "result":
        print("\n" + "=" * 60)
        status = "✅ SUCCESS" if event.success else "⚠️  ENDED"
        print(f"{status}\n{event.message}")
        print("=" * 60)
    elif event.type == "error":
        print(f"\n❌ {event.message}")
    elif event.type == "info":
        print(f"· {event.message}")


async def _run(task: str, url: str | None, headless: bool, max_steps: int) -> int:
    session = BrowserSession(headless=headless)
    agent = Agent(task=task, start_url=url, sink=_print_event, max_steps=max_steps, session=session)
    result = await agent.run()
    return 0 if result.success else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="General-purpose website automation agent (mini browser-use).")
    parser.add_argument("task", help="Natural-language task for the agent to perform.")
    parser.add_argument("--url", default=None, help="Optional start URL.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument("--headless", action="store_true", help="Force headless mode.")
    parser.add_argument("--max-steps", type=int, default=settings.max_steps, help="Max agent steps.")
    args = parser.parse_args()

    configure_logging()

    if args.headed:
        headless = False
    elif args.headless:
        headless = True
    else:
        headless = settings.headless

    if not settings.gemini_api_key:
        print("ERROR: GEMINI_API_KEY not set. Copy .env.example to .env and add your key.", file=sys.stderr)
        sys.exit(2)

    # Playwright on some setups needs the selector event loop policy on Windows; on
    # macOS/Linux the default is fine.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    exit_code = asyncio.run(_run(args.task, args.url, headless, args.max_steps))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
