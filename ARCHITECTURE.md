# Architecture

## Goal

A **general-purpose** autonomous web agent — a mini [browser-use](https://github.com/browser-use/browser-use).
The user states a task in natural language; the agent perceives the page, decides what to do with
an LLM, acts, observes the result, and repeats until the task is done. Nothing about any specific
site is hardcoded.

## The core idea: index-based perception, coordinate-based action

A vision model *could* be asked to "click at pixel (734, 210)", but that is unreliable and burns
tokens. Instead we use the approach that makes browser-use robust:

1. **Detect & number elements.** On every step we inject [`browser/buildDomTree.js`](browser/buildDomTree.js)
   into the page. It finds the elements that are both *interactive* (links, buttons, inputs,
   textareas, selects, ARIA roles, clickable handlers…) and *visible*, assigns each a numeric
   **index**, computes its **bounding box / center coordinates**, and draws a labeled highlight box
   so the screenshot matches what the model "sees".
2. **Describe them as text.** [`dom_service.py`](browser/dom_service.py) turns the JS result into a
   `SelectorMap` (`index -> DomElement`) and a compact text list given to the LLM:
   ```
   [0]<button> Submit
   [3]<input> Bug Title type=text placeholder="Login button not working..."
   [7]<textarea> Description
   ```
3. **The LLM reasons by index.** It returns actions like `input_text(index=3, text=...)` — never raw
   pixels. This works even with a **text-only** model and keeps token use low (important for the
   Flash-Lite rate limits).
4. **The controller maps index → coordinates → primitive tool.**
   [`controller.py`](agent/controller.py) looks up element 3's center `(x, y)` in the `SelectorMap`
   and calls the required primitive [`click_on_screen(x, y)`](tools/actions.py). This is the bridge
   between intelligent reasoning and the assignment's coordinate-based tool contract.

## The agent loop

```
                 ┌──────────────────────────────────────────────┐
   task ───────▶ │  Agent (agent/agent.py)                       │
                 │                                               │
                 │  1. DomService.get_state()  ── inject JS ──▶  │  numbered elements + boxes
                 │  2. take_screenshot()                         │  (Web-UI live view)
                 │  3. build prompt (state + history)            │
                 │  4. Gemini.generate_structured(AgentOutput) ─▶│  {current_state, action[]}
                 │  5. emit StepEvent ──────────────────────────▶│  CLI print / SSE to browser
                 │  6. Controller.execute(action) ──▶ primitives │  click/type/scroll/extract
                 │  7. record observation in history             │
                 │     loop until `done` or MAX_STEPS            │
                 └──────────────────────────────────────────────┘
```

The model's structured output (enforced via Gemini `response_schema`, see
[`agent/views.py`](agent/views.py)) is:

```jsonc
{
  "current_state": {
    "evaluation_previous_goal": "Success/Failed/Unknown - why",
    "memory": "what's done, data collected, what's left",
    "next_goal": "what the next action(s) achieve"
  },
  "action": [ { "name": "input_text", "index": 3, "text": "..." } ]
}
```

A step may contain multiple actions, but the loop **stops the batch at the first page-changing
action** (navigate/click/send-keys) so the next step always reasons over fresh, valid element
numbers — this prevents stale-index bugs.

## Action vocabulary

High-level actions the LLM emits, all reduced to the required primitives by the controller:

| LLM action | Reduces to primitive(s) |
|---|---|
| `navigate(url)` | `navigate_to_url` |
| `click(index)` | `click_on_screen(x, y)` |
| `double_click(index)` | `double_click(x, y)` |
| `input_text(index, text)` | `click_on_screen` → select-all → `send_keys` |
| `send_keys(keys)` | keyboard press (Enter, Tab, …) |
| `scroll(direction, amount)` | `scroll(dx, dy)` |
| `extract_content(goal)` | read page text → LLM extraction (for info tasks) |
| `wait` / `go_back` / `done` | session helpers / terminate |

`extract_content` is what lets the agent answer questions like "top 10 trending phones": it pulls
the visible page text and asks the model to extract the structured answer.

## Design decisions

- **Python + Playwright + FastAPI** — matches the browser-use reference, mature Gemini SDK, simple
  async server for the live UI.
- **Async throughout** — one event loop drives the browser, the LLM calls, and the SSE stream.
- **Text DOM-index over vision** — reliability + low token cost; vision could be layered on later by
  also sending the highlighted screenshot, but isn't needed for correctness.
- **One `Action` model with optional fields** instead of a union of action types — Flash-Lite-class
  models follow a flat JSON Schema far more reliably than nested `oneOf`/`anyOf`.
- **Single shared `StepEvent` bus** — CLI and Web-UI consume identical events, so logs and the live
  view never drift.

## Error handling & robustness

- **LLM:** retry with exponential backoff on 429/5xx/timeouts (rate-limit aware); validate/parse the
  structured response, with a JSON fallback.
- **Actions:** every action is wrapped — failures (e.g. a stale index after the page changed) become
  an *observation* fed back to the model so it can adapt, rather than crashing the run.
- **Navigation:** tolerant `goto` (doesn't abort on slow SPAs) + a settle wait.
- **Loop:** hard `MAX_STEPS` cap; honest `evaluation_previous_goal` nudges the model off dead ends.
- **Lifecycle:** browser is always closed in a `finally`, even on cancel (Web-UI Stop button).
