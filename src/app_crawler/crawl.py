"""Ticket 2: multi-step Crawl loop with dedup and a hard step cap.

Implements the single seam named in spec #1:

    run_crawl(driver, llm_client, config) -> FlowGraph

Each step: capture the current Screen (screenshot + hierarchy) -> compute
its Fingerprint -> if already visited, skip the Navigator call, record the
graph edge, and fall back to `back` -> if new, call the Navigator, record
the Screen and edge, then execute the Navigator's chosen action. The Crawl
stops when the Navigator reports `done`, when the step cap is hit, or when
there is no fallback action left to take.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app_crawler.driver import Driver
from app_crawler.llm_client import LLMClient, build_navigator_prompt

TARGET_PACKAGE = "com.smctrading.android"

_DEFAULT_STEP_CAP = 40
_DEFAULT_ACTION_TIMEOUT = 10.0
_DEFAULT_MAX_RETRIES = 2


@dataclass
class CrawlConfig:
    """Orchestrator knobs. Per ADR 0002, the step cap is hard and the Crawl
    is not resumable."""

    step_cap: int = _DEFAULT_STEP_CAP
    package_name: str = TARGET_PACKAGE
    action_timeout: float = _DEFAULT_ACTION_TIMEOUT
    max_retries: int = _DEFAULT_MAX_RETRIES
    output_dir: Path | None = None
    model: str | None = None


@dataclass
class Screen:
    """A Flow Graph node: one distinct app UI state, per CONTEXT.md."""

    id: str
    fingerprint: str
    screenshot_path: str
    use_case: str


@dataclass
class FlowGraph:
    """The complete map of Screens (nodes) and the taps connecting them
    (edges), built incrementally during a Crawl."""

    nodes: list[Screen] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": n.id,
                    "fingerprint": n.fingerprint,
                    "screenshot_path": n.screenshot_path,
                    "use_case": n.use_case,
                }
                for n in self.nodes
            ],
            "edges": list(self.edges),
        }

    def save(self, path: str | Path) -> None:
        """Write this Flow Graph to `graph.json` (or any given path)."""
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))


class DeviceTimeoutError(RuntimeError):
    """Raised when a device action does not complete within the configured
    per-action timeout."""


def _with_timeout(func, timeout: float, *args, **kwargs):
    """Run a driver call with a hard timeout so a hung device action can't
    stall the Crawl indefinitely."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise DeviceTimeoutError(
                f"Device action {getattr(func, '__name__', func)!r} timed out "
                f"after {timeout}s"
            ) from exc


# Numeric-only text/bounds noise is stripped before hashing so blinking
# cursors, ad banners, and scroll offsets don't spuriously create a new
# fingerprint for a structurally identical Screen.
_NUMERIC_TEXT_RE = re.compile(r'text="[^"]*\d[^"]*"')
_BOUNDS_RE = re.compile(r'bounds="\[[^\]]*\]\[[^\]]*\]"')


def fingerprint_hierarchy(hierarchy_xml: str) -> str:
    """Hash the normalized UI hierarchy XML into a Screen Fingerprint.

    Deliberately NOT a hash of the screenshot image, per CONTEXT.md.
    """
    normalized = _NUMERIC_TEXT_RE.sub('text=""', hierarchy_xml)
    normalized = _BOUNDS_RE.sub('bounds=""', normalized)
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


_CLICKABLE_ELEMENT_RE = re.compile(
    r'<node[^>]*\bclickable="true"[^>]*>', re.IGNORECASE
)
_ATTR_RE = re.compile(r'(\w[\w-]*)="([^"]*)"')


def clickable_elements(hierarchy_xml: str) -> list[dict[str, str]]:
    """Parse the `clickable="true"` elements out of a hierarchy dump, each
    as its `resource-id`/`text`/`bounds` attributes."""
    elements = []
    for match in _CLICKABLE_ELEMENT_RE.finditer(hierarchy_xml):
        attrs = dict(_ATTR_RE.findall(match.group(0)))
        elements.append(
            {
                "resource-id": attrs.get("resource-id", ""),
                "text": attrs.get("text", ""),
                "bounds": attrs.get("bounds", ""),
            }
        )
    return elements


def _target_exists(target: str | None, elements: list[dict[str, str]]) -> bool:
    if not target:
        return True
    return any(e["resource-id"] == target or e["text"] == target for e in elements)


def _extract_action(raw: dict[str, Any]) -> dict[str, Any]:
    action = raw.get("action") or {}
    if not isinstance(action, dict):
        action = {}
    action_type = action.get("type") or "back"
    target = action.get("target")
    return {"type": action_type, "target": target}


def _visited_summary(graph: FlowGraph) -> str:
    if not graph.nodes:
        return "(none yet)"
    return "\n".join(f"- {n.id}: {n.use_case}" for n in graph.nodes)


def _next_screen_id(graph: FlowGraph) -> str:
    return f"screen_{len(graph.nodes)}"


def run_crawl(driver: Driver, llm_client: LLMClient, config: CrawlConfig | None = None) -> FlowGraph:
    """Run one Crawl: launch the app and explore it screen by screen,
    deduping by hierarchy Fingerprint, until the Navigator reports nothing
    new to explore or the hard step cap is hit.
    """
    config = config or CrawlConfig()
    graph = FlowGraph()

    driver.connect()
    driver.app_start(config.package_name)

    visited: dict[str, str] = {}  # fingerprint -> screen id
    last_screen_id: str | None = None
    pending_action: dict[str, Any] | None = None  # action that led to the current step

    for _step in range(config.step_cap):
        screenshot = _with_timeout(driver.screenshot, config.action_timeout)
        hierarchy_xml = _with_timeout(driver.dump_hierarchy, config.action_timeout)
        fp = fingerprint_hierarchy(hierarchy_xml)

        if fp in visited:
            # Already-seen Screen: skip the Navigator call entirely, record
            # the edge via the action that led here, and fall back to a
            # different action instead of re-describing it.
            existing_id = visited[fp]
            if last_screen_id is not None and pending_action is not None:
                graph.edges.append(
                    {
                        "from": last_screen_id,
                        "action": pending_action,
                        "to": existing_id,
                    }
                )
            last_screen_id = existing_id
            pending_action = {"type": "back", "target": None}
            driver.back()
            continue

        # New Screen: call the Navigator, with retries if it hallucinates a
        # tap target that isn't present in the current hierarchy.
        elements = clickable_elements(hierarchy_xml)
        note = None
        raw: dict[str, Any] = {}
        action: dict[str, Any] = {"type": "back", "target": None}
        for attempt in range(config.max_retries + 1):
            prompt = build_navigator_prompt(
                visited_summary=_visited_summary(graph), note=note
            )
            result = llm_client.describe_screen(screenshot, hierarchy_xml, prompt=prompt)
            raw = result.raw
            action = _extract_action(raw)
            if _target_exists(action.get("target"), elements):
                break
            note = (
                f"Your previous action target {action.get('target')!r} does not "
                "exist in the current UI hierarchy. Pick a resource-id or text "
                "value that is actually present, or use action type 'back'."
            )
            if attempt == config.max_retries:
                # Exhausted retries: treat as retryable-handled, not a crash.
                action = {"type": "back", "target": None}

        screen_id = _next_screen_id(graph)
        screenshot_path = _save_screenshot(screenshot, screen_id, config)
        screen = Screen(
            id=screen_id,
            fingerprint=fp,
            screenshot_path=screenshot_path,
            use_case=result.use_case,
        )
        graph.nodes.append(screen)
        visited[fp] = screen_id

        if last_screen_id is not None and pending_action is not None:
            graph.edges.append(
                {"from": last_screen_id, "action": pending_action, "to": screen_id}
            )

        last_screen_id = screen_id
        pending_action = action

        if bool(raw.get("done")):
            break

        _execute_action(driver, action)

    if config.output_dir is not None:
        graph.save(Path(config.output_dir) / "graph.json")

    return graph


def _execute_action(driver: Driver, action: dict[str, Any]) -> None:
    if action.get("type") == "tap" and action.get("target"):
        target = action["target"]
        # Prefer resource-id-shaped targets over free text, but either way
        # pass the same value through both selectors so the fake/real
        # driver can match on whichever it supports.
        driver.tap(resource_id=target, text=target)
    else:
        driver.back()


def _save_screenshot(screenshot, screen_id: str, config: CrawlConfig) -> str:
    if config.output_dir is None:
        return ""
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{screen_id}.png"
    screenshot.save(path)
    return str(path)
