"""Pydantic models that define the agent's structured output contract.

Gemini is forced to return JSON matching AgentOutput (via response_schema). We use
ONE Action model with optional fields rather than a union of action types — this
keeps the JSON Schema simple, which Flash-Lite-class models follow far more
reliably than nested oneOf/anyOf schemas.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Action(BaseModel):
    """A single action. `name` selects the behavior; only the relevant params are set."""

    name: str = Field(
        description=(
            "One of: navigate, click, double_click, input_text, send_keys, "
            "scroll, extract_content, wait, go_back, done"
        )
    )
    index: Optional[int] = Field(
        default=None, description="Element index for click/double_click/input_text"
    )
    text: Optional[str] = Field(
        default=None, description="Text for input_text, or answer text for done"
    )
    url: Optional[str] = Field(default=None, description="URL for navigate")
    keys: Optional[str] = Field(
        default=None, description="Key/chord for send_keys, e.g. 'Enter', 'Tab', 'Control+A'"
    )
    direction: Optional[str] = Field(default=None, description="'down' or 'up' for scroll")
    amount: Optional[int] = Field(default=None, description="Pixels to scroll (default 600)")
    seconds: Optional[float] = Field(default=None, description="Seconds for wait")
    goal: Optional[str] = Field(
        default=None, description="What to extract for extract_content"
    )
    success: Optional[bool] = Field(
        default=None, description="Whether the task succeeded, for done"
    )


class CurrentState(BaseModel):
    evaluation_previous_goal: str = Field(
        description="Did the previous action achieve its goal? Success/Failed/Unknown + why."
    )
    memory: str = Field(
        description="Concise running notes: what has been done, what remains, collected data."
    )
    next_goal: str = Field(description="What the next action(s) aim to accomplish.")


class AgentOutput(BaseModel):
    current_state: CurrentState
    action: list[Action] = Field(
        description="Ordered actions to run this step (usually 1). Stop early if the page will change."
    )
