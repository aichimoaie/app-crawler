# Setup

Step-by-step guide to get App Crawler running and to operate it. There is no CLI entrypoint yet for the crawl/annotate/PRD steps beyond `capture_and_describe.py` — those are invoked with a short Python snippet each, shown below. See `CONTEXT.md` for the domain vocabulary (Screen, Crawl, Navigator, Writer, Flow Graph) used throughout.

## 1. Install dependencies

```bash
cd app-crawler
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

(`uv sync` works too if you use `uv`.)

## 2. Get an OpenRouter API key

1. Open https://openrouter.ai and sign in / create an account.
2. Go to https://openrouter.ai/keys → **Create Key**.
3. Copy the key (starts with `sk-or-`).

No paid credits are required — the project uses `qwen/qwen2.5-vl-32b-instruct:free`, a free-tier model. Free tier is capped at **20 requests/minute** and **50 requests/day** (rising to 1000/day if you ever fund the account with $10+) — see ADR 0002 for why the Crawl hard-stops at ~40 screens instead of resuming across days.

## 3. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and set:

```
OPENROUTER_API_KEY=sk-or-...
```

`.env` is git-ignored — never commit it.

## 4. Connect your Android phone

You need `adb` installed (comes with Android Studio's platform-tools, or install standalone: `sudo apt install android-tools-adb` on Debian/Ubuntu).

**Option A — USB (simplest):**

1. On the phone: **Settings → About phone → tap "Build number" 7 times** to unlock Developer Options.
2. **Settings → Developer Options → enable USB debugging.**
3. Plug the phone into your computer via USB.
4. Accept the "Allow USB debugging?" prompt on the phone.
5. Confirm: `adb devices` — should list your phone's serial.

**Option B — Wireless debugging (no cable, same Wi-Fi network):**

1. **Settings → Developer Options → Wireless debugging → turn on.**
2. Tap **Pair device with pairing code** — note the IP:port and 6-digit code shown.
3. On your computer: `adb pair <ip>:<pairing-port>`, enter the code.
4. Then `adb connect <ip>:<connect-port>` (the IP:port shown on the main Wireless debugging screen — different from the pairing port).
5. Confirm: `adb devices` — should list the phone.

Either way, **keep the phone's screen on and unlocked** while a script runs (disable auto-lock or enable "stay awake while charging" in Developer Options) — a locked screen stalls automation, adb/uiautomator2 can't tap through it.

## 5. Verify the target app is present

The pipeline is scoped to `com.smctrading.android` (see spec issue #1). Confirm it's installed and you're already logged in inside the app on the phone — no credentials are scripted for the app itself (see ADR 0001).

```bash
adb shell pm list packages | grep smctrading
```

## Operating the pipeline

Run each step from the project root, with `.venv` activated.

### Step 1 — Single-screen capture and describe (sanity check)

Connects to the phone, launches the app, takes one screenshot, and prints the Navigator's Use Case for that screen. Good first check that everything's wired up before running a full Crawl.

```bash
python -m app_crawler.capture_and_describe
```

### Step 2 — Run a Crawl

Produces `graph.json`: the Flow Graph of Screens and the taps connecting them. Hard-stops at ~40 Screens (`CrawlConfig.step_cap`, default) or when the Navigator reports nothing new.

```bash
python - <<'PY'
from app_crawler.driver import UiAutomator2Driver
from app_crawler.llm_client import OpenRouterLLMClient
from app_crawler.crawl import run_crawl, CrawlConfig

driver = UiAutomator2Driver()
llm_client = OpenRouterLLMClient()
graph = run_crawl(driver, llm_client, CrawlConfig())
graph.save("graph.json")
print(f"Crawled {len(graph.nodes)} screens -> graph.json")
PY
```

### Step 3 — Annotate screenshots

Draws a bounding box on each Screen's raw screenshot around the element that was tapped to leave it, and updates `graph.json` to point at the annotated images.

```bash
python -c "from app_crawler.annotate import annotate_graph; annotate_graph('graph.json')"
```

### Step 4 — Generate the PRD

Reads `graph.json` and writes `PRD.md`: an architecture/flow summary plus one section per Screen (annotated screenshot + Use Case). Runnable standalone, without re-crawling — safe to re-run after tweaking the Writer prompt.

```bash
python -c "from app_crawler.prd import write_prd; write_prd('graph.json', 'PRD.md')"
```

Open `PRD.md` when done — that's the finished product, meant to be handed to an AI coding agent for the rebuild.

## Running tests

No device or API key needed — everything is tested against faked driver/LLM clients.

```bash
pytest
```

## Known gaps (see code review on PR #6)

- `driver.tap`/`driver.back` calls aren't wrapped in the per-action timeout yet (only `screenshot`/`dump_hierarchy` are) — a hung tap can still stall a Crawl.
- No logging when hallucination-retries are exhausted; the Crawl silently falls back to `back`.
- No script-level denylist on financial-action elements — see ADR 0001, an explicit accepted risk since the target app is a live trading account.
