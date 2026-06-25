# Website Automation Agent — a mini *browser-use*

An intelligent, **general-purpose** browser automation agent. Give it a task in plain
English and it autonomously drives a real Chromium browser to complete it — filling forms,
searching, navigating, scrolling, and extracting information.

It is **not** a hardcoded script. The same agent can:

- *"Fill in the Bug Title and Description fields on the shadcn form."*
- *"Go to Flipkart and list the top 10 trending phones."*
- *"Get the top 5 Hacker News story titles."*

It is modeled on the architecture of [browser-use](https://github.com/browser-use/browser-use):
the page's interactive elements are detected, numbered, and given to the LLM as text; the LLM
reasons by index; the controller translates each choice into low-level mouse/keyboard actions.

---

## Features

- 🧠 **LLM-driven** by Google **Gemini 3.1 Flash Lite** (configurable).
- 🎯 **Reliable element detection** — DOM-index + bounding boxes (works without vision).
- 🧰 **All assignment-required tools**: `open_browser`, `navigate_to_url`, `take_screenshot`,
  `click_on_screen(x, y)`, `double_click`, `send_keys`, `scroll`.
- 🖥️ **Web-UI** with a live browser view, streaming thought/action log, and final result.
- ⌨️ **CLI** for quick runs and demos.
- 🛡️ **Robust**: retries with backoff (rate-limit aware), stale-element recovery, timeouts,
  step caps, graceful teardown, and full logging.

---

## Setup

Requires **Python 3.10+** (tested on Windows with 3.12 and on macOS with 3.14).

A virtual environment is **per-platform** — one built on macOS will not run on Windows
and vice-versa (the binaries differ). Always create the venv on the machine you'll run on.

### Windows (PowerShell)

```powershell
# 1. Create and populate a virtual environment
python -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install --upgrade pip
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt

# 2. Install the Chromium browser Playwright drives
.\.venv-win\Scripts\python.exe -m playwright install chromium

# 3. Configure credentials
Copy-Item .env.example .env
#   then edit .env and set GEMINI_API_KEY (and GEMINI_MODEL if your access differs)
```

For brevity the rest of this README writes `python` for `.\.venv-win\Scripts\python.exe` —
either activate the venv (`.\.venv-win\Scripts\Activate.ps1`) or use the full path.

### macOS / Linux (bash)

```bash
# 1. Create and populate a virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Install the Chromium browser Playwright drives
playwright install chromium

# 3. Configure credentials
cp .env.example .env
#   then edit .env and set GEMINI_API_KEY (and GEMINI_MODEL if your access differs)
```

### Verify the LLM connection first

```bash
python smoke_test.py
```

This confirms your key, model id, and structured output work **before** touching the
browser — run it first to rule out a bad key or unavailable model. A pass looks like:

```
Structured response: {'ok': True, 'message': 'Gemini structured output is working'}
✅ Gemini is reachable and structured output works.
```

---

## Usage

### CLI

```bash
# The assignment's target task (visible browser window):
python main.py "Fill the Bug Title with 'Login button unresponsive' and write a Description of at least 20 characters" \
    --url https://ui.shadcn.com/docs/forms/react-hook-form --headed

# A general task (proves it isn't a script):
python main.py "Go to Flipkart and list the top 10 trending phones with prices"
```

Flags: `--url` (start URL), `--headed` / `--headless`, `--max-steps N`.

### Web-UI

```bash
# macOS/Linux (venv activated)
uvicorn webui.server:app --reload

# Windows (full path)
.\.venv-win\Scripts\uvicorn.exe webui.server:app --reload
```

Open <http://localhost:8000>, type a task (or click an example), and press **Run**. You'll see
the live screenshot, the agent's reasoning and actions streaming step-by-step, and the final
answer. (Tip: leave "Run headless" **unchecked** to also watch the real browser window.)

---

## Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio API key | — (required) |
| `GEMINI_MODEL` | Model id | `gemini-3.1-flash-lite` |
| `GEMINI_BASE_URL` | Optional gateway/proxy base URL | (Google default) |
| `HEADLESS` | Run browser without a window | `false` |
| `VIEWPORT_WIDTH` / `VIEWPORT_HEIGHT` | Screenshot/coordinate viewport | `1280` / `800` |
| `MAX_STEPS` | Max agent steps before giving up | `25` |
| `ACTION_TIMEOUT_MS` | Per-action / navigation timeout | `15000` |

---

## Project layout

```
config.py            Settings from .env
logging_conf.py      Logging + StepEvent bus (CLI + Web-UI share events)
main.py              CLI entrypoint
smoke_test.py        LLM connectivity check
llm/gemini.py        Gemini client: structured output + retry/backoff
browser/
  session.py         Playwright lifecycle + primitive operations
  buildDomTree.js    Injected JS: find/number visible interactive elements + boxes
  dom_service.py     Parses the JS result into an indexed SelectorMap
tools/actions.py     The assignment's required primitive tools
agent/
  views.py           Pydantic schema for the LLM's structured output
  prompts.py         System prompt + per-step prompt builder
  controller.py      Maps index actions -> primitive coordinate tools
  agent.py           The perceive -> think -> act loop
webui/
  server.py          FastAPI: /run, /stream (SSE), /stop
  static/index.html  Single-page live UI
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design rationale and workflow diagram.

---

## Troubleshooting

- **`GEMINI_API_KEY not set`** — create `.env` from `.env.example` and add your key.
- **Model 404 / not found** — set `GEMINI_MODEL` in `.env` to the exact model string your key can access.
- **Rate-limit (429)** — Flash-Lite tiers have low RPM/RPD; the agent backs off and retries. Increase
  waits or reduce `MAX_STEPS` for heavy demos.
- **`playwright` errors about a missing browser** — run `playwright install chromium` (use the venv's
  Python on Windows: `.\.venv-win\Scripts\python.exe -m playwright install chromium`).
- **`'.venv\Scripts\python.exe' is not recognized` / venv won't run** — the virtual environment is
  platform-specific. A `.venv` created on macOS/Linux cannot run on Windows. Delete it and rebuild with
  the Windows steps above (this repo uses `.venv-win` for the Windows env).
- **`UnicodeEncodeError: 'charmap' codec can't encode ...`** — older Windows consoles default to cp1252
  and can't print the ✅/──/❌ glyphs. The entrypoints reconfigure stdout/stderr to UTF-8 to prevent this;
  if you add new print sites, keep that in mind.
- **`Page.screenshot: Timeout ... exceeded`** — some pages (e.g. the shadcn docs) animate continuously and
  never reach Playwright's stability check. Screenshots are best-effort and **non-fatal**: a capture
  failure is logged as a warning and the run continues (the live view simply skips that frame).
