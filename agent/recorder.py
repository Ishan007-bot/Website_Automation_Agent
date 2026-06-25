"""RunRecorder — persists every agent run to its own timestamped folder.

Each run produces:
    runs/run_YYYYMMDD_HHMMSS/
        step_00.png, step_01.png, ...   one screenshot per step
        trace.jsonl                     one JSON line per StepEvent (full trace)
        summary.json                    task, url, success, steps, final answer

Screenshots are decoded from the base64 the agent already captures, so recording
adds no extra browser work. Recording is best-effort: any disk error is logged
and swallowed so it can never abort an agent run.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime

from logging_conf import StepEvent

logger = logging.getLogger("agent")

# Sibling of the package root, alongside logs/.
RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "runs")


class RunRecorder:
    def __init__(self, task: str, url: str | None) -> None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = os.path.join(RUNS_DIR, f"run_{stamp}")
        self.task = task
        self.url = url
        self._trace_path = os.path.join(self.dir, "trace.jsonl")
        self._n_screenshots = 0
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError as exc:  # pragma: no cover - best-effort
            logger.warning("Could not create run dir %s: %s", self.dir, exc)

    def record(self, event: StepEvent) -> None:
        """Append the event to trace.jsonl and, for step events, save its screenshot."""
        try:
            self._append_trace(event)
            if event.type == "step" and event.screenshot:
                self._save_screenshot(event)
        except Exception as exc:  # noqa: BLE001 - recording must never break a run
            logger.warning("Recorder error: %s", exc)

    def finish(self, success: bool, answer: str, steps: int) -> None:
        """Write summary.json once the run ends."""
        summary = {
            "task": self.task,
            "start_url": self.url,
            "success": success,
            "steps": steps,
            "screenshots": self._n_screenshots,
            "final_answer": answer,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            with open(os.path.join(self.dir, "summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            logger.info("Run recorded to %s", self.dir)
        except OSError as exc:  # pragma: no cover - best-effort
            logger.warning("Could not write summary.json: %s", exc)

    # ── internals ────────────────────────────────────────────────────────
    def _append_trace(self, event: StepEvent) -> None:
        row = event.to_dict()
        row.pop("screenshot", None)  # the heavy base64 lives in the .png, not the trace
        with open(self._trace_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _save_screenshot(self, event: StepEvent) -> None:
        # step is 1-based in the loop; name files step_00, step_01, ... by save order.
        name = f"step_{self._n_screenshots:02d}.png"
        with open(os.path.join(self.dir, name), "wb") as f:
            f.write(base64.b64decode(event.screenshot))
        self._n_screenshots += 1
