"""Agent — the perceive→think→act loop.

Each step:
  1. Capture state: URL, title, screenshot, and the numbered interactive elements.
  2. Build the prompt and ask Gemini for a structured AgentOutput.
  3. Emit a StepEvent (consumed by the CLI and/or Web-UI).
  4. Execute the action(s) via the controller, stopping the batch at the first
     page-changing action so the next step gets fresh element numbers.
  5. Repeat until `done` or MAX_STEPS.
"""
from __future__ import annotations

import logging

from agent.controller import Controller
from agent.prompts import SYSTEM_PROMPT, build_step_prompt
from agent.recorder import RunRecorder
from agent.views import AgentOutput
from browser.dom_service import DomService
from browser.session import BrowserSession
from config import settings
from llm.factory import make_llm
from logging_conf import EventSink, StepEvent, noop_sink
from tools.actions import Tools

logger = logging.getLogger("agent")

# Actions that change the page; we stop a multi-action batch right after one of these.
_PAGE_CHANGING = {"navigate", "click", "double_click", "go_back", "send_keys"}


class AgentRunResult:
    def __init__(self, success: bool, answer: str, steps: int):
        self.success = success
        self.answer = answer
        self.steps = steps


class Agent:
    def __init__(
        self,
        task: str,
        start_url: str | None = None,
        sink: EventSink = noop_sink,
        max_steps: int | None = None,
        session: BrowserSession | None = None,
    ) -> None:
        self.task = task
        self.start_url = start_url
        self.sink = sink
        self.max_steps = max_steps or settings.max_steps

        self.session = session or BrowserSession()
        self.tools = Tools(self.session)
        self.dom = DomService(self.session)
        self.llm = make_llm()
        self.controller = Controller(self.tools, self.llm, task=self.task)

        self.history: list[str] = []
        # Persists each run to runs/run_<timestamp>/ (screenshots + trace + summary).
        self.recorder = RunRecorder(task=self.task, url=self.start_url)

        # Repeat-detection: weaker models can loop on the same action that isn't
        # working. We track the previous step's first-action label and how many
        # times in a row it has repeated, escalate a warning, and abort if stuck.
        self._last_action_label: str | None = None
        self._repeat_count = 0

    def _emit(self, event: StepEvent) -> None:
        # Record before fanning out to the UI sink so artifacts persist even if the
        # sink raises.
        self.recorder.record(event)
        try:
            self.sink(event)
        except Exception as exc:  # pragma: no cover - a UI error must not kill the run
            logger.warning("event sink error: %s", exc)

    async def run(self) -> AgentRunResult:
        await self.session.open_browser()
        self._emit(StepEvent(type="info", message="Browser opened."))
        result = AgentRunResult(False, "Run did not complete.", 0)
        try:
            if self.start_url:
                await self.session.navigate_to_url(self.start_url)
            result = await self._loop()
            return result
        finally:
            await self.session.close()
            self._emit(StepEvent(type="info", message="Browser closed."))
            # Write summary.json last, on every exit path (success, error, or cancel).
            self.recorder.finish(result.success, result.answer, result.steps)

    async def _loop(self) -> AgentRunResult:
        for step in range(1, self.max_steps + 1):
            dom_state = await self.dom.get_state(draw_highlights=True)
            screenshot = await self.session.take_screenshot()
            url = await self.session.current_url()
            title = await self.session.title()

            scroll_hint = ""
            if dom_state.scroll_max_y > 0:
                pct = int(100 * dom_state.scroll_y / dom_state.scroll_max_y) if dom_state.scroll_max_y else 0
                scroll_hint = f"SCROLL: at {pct}% of page (more content below if < 100%)."

            # If the last action has already repeated, warn the model before it
            # decides again (escalating in force with the repeat count).
            repeat_warning = ""
            if self._repeat_count >= 1 and self._last_action_label:
                repeat_warning = (
                    f"⚠️ REPEAT WARNING: your previous action `{self._last_action_label}` "
                    f"has not changed anything {self._repeat_count + 1} time(s) in a row. "
                    "Do NOT issue that same action again. Try something different: a DIFFERENT "
                    "element index, scroll to find the right element, or a different approach. "
                    "If you cannot make progress, call done with success=false and an explanation."
                )

            prompt = build_step_prompt(
                task=self.task,
                url=url,
                title=title,
                elements_text=dom_state.elements_text(),
                history="\n".join(self.history[-12:]),
                step=step,
                max_steps=self.max_steps,
                scroll_hint=scroll_hint,
                repeat_warning=repeat_warning,
            )

            try:
                output: AgentOutput = await self.llm.generate_structured(
                    SYSTEM_PROMPT, prompt, AgentOutput
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("LLM step failed: %s", exc)
                self._emit(StepEvent(type="error", step=step, message=f"LLM error: {exc}"))
                return AgentRunResult(False, f"LLM error: {exc}", step)

            cs = output.current_state
            action_labels = [self._label(a) for a in output.action]
            logger.info("STEP %d | goal: %s | actions: %s", step, cs.next_goal, action_labels)

            # Track whether the model is repeating the same first action.
            first_label = action_labels[0] if action_labels else None
            if first_label is not None and first_label == self._last_action_label:
                self._repeat_count += 1
            else:
                self._repeat_count = 0
            self._last_action_label = first_label

            # Hard stop if it's truly stuck (same action 4×) so we don't burn every
            # step looping; end honestly rather than pretending success.
            if self._repeat_count >= 3:
                msg = (
                    f"Stuck: repeated `{first_label}` {self._repeat_count + 1} times "
                    "without progress. Stopping."
                )
                logger.info(msg)
                self._emit(StepEvent(type="result", step=step, message=msg, success=False, url=url))
                return AgentRunResult(False, msg, step)
            self._emit(
                StepEvent(
                    type="step",
                    step=step,
                    evaluation=cs.evaluation_previous_goal,
                    memory=cs.memory,
                    next_goal=cs.next_goal,
                    actions=action_labels,
                    url=url,
                    screenshot=screenshot,
                )
            )

            if not output.action:
                self.history.append(f"step {step}: model returned no action")
                continue

            # Execute the batch, stopping after the first page-changing action.
            for action in output.action:
                result = await self.controller.execute(action, dom_state)
                label = self._label(action)
                note = result.message
                if result.extracted:
                    note = f"{result.message}\nEXTRACTED:\n{result.extracted}"
                self.history.append(f"step {step}: {label} -> {note}")

                if result.is_done:
                    logger.info("DONE (success=%s): %s", result.success, result.message)
                    self._emit(
                        StepEvent(
                            type="result",
                            step=step,
                            message=result.message,
                            success=result.success,
                            url=url,
                            screenshot=screenshot,
                        )
                    )
                    return AgentRunResult(result.success, result.message, step)

                if (action.name or "").lower() in _PAGE_CHANGING:
                    break

        msg = f"Reached the step limit ({self.max_steps}) without finishing."
        logger.info(msg)
        self._emit(StepEvent(type="result", step=self.max_steps, message=msg, success=False))
        return AgentRunResult(False, msg, self.max_steps)

    @staticmethod
    def _label(action) -> str:
        name = action.name or "?"
        parts = []
        if action.index is not None:
            parts.append(f"index={action.index}")
        if action.url:
            parts.append(action.url)
        if action.text is not None:
            parts.append(f'text="{action.text[:40]}"')
        if action.keys:
            parts.append(f"keys={action.keys}")
        if action.direction:
            parts.append(action.direction)
        if action.goal:
            parts.append(f'goal="{action.goal[:40]}"')
        if action.success is not None:
            parts.append(f"success={action.success}")
        return f"{name}({', '.join(parts)})"
