"""Logging setup + a lightweight event bus.

`configure_logging()` wires console + rotating-file handlers.

`StepEvent` / `EventSink` give the agent a single place to emit structured
per-step events. The CLI prints them; the Web-UI streams them over SSE. Both
consume the exact same events, so console and browser stay in sync.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("agent")
    if logger.handlers:  # already configured
        return logger
    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "agent.log"), maxBytes=1_000_000, backupCount=3
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


@dataclass
class StepEvent:
    """One structured event emitted during an agent run."""

    type: str  # "step" | "result" | "error" | "info"
    step: int = 0
    evaluation: str = ""
    memory: str = ""
    next_goal: str = ""
    actions: list[str] = field(default_factory=list)
    url: str = ""
    screenshot: str = ""  # base64 PNG (no data: prefix)
    message: str = ""
    success: Optional[bool] = None

    def to_dict(self) -> dict:
        return asdict(self)


# An EventSink is any function that consumes a StepEvent.
EventSink = Callable[[StepEvent], None]


def noop_sink(_event: StepEvent) -> None:
    """Default sink that does nothing (used when no UI is listening)."""
    return None
