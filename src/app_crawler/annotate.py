"""Ticket 3: screenshot annotation.

For each Screen in a Flow Graph that has an outgoing edge, draw a bounding
box on its raw screenshot at the exact `bounds` rectangle (from the UI
hierarchy) of the element that was tapped to leave that Screen -- not an
LLM-estimated region -- using Pillow. The Screen's `screenshot_path` is then
updated to point at the annotated image.

A Screen with no outgoing edge (a leaf/terminal Screen) is left unannotated,
not treated as an error.

This is invocable as a standalone step, independent of the Crawl step, via
`annotate_graph(graph_json_path)`, consistent with spec #1's requirement
that later steps (PRD generation, and now annotation) can run from an
existing `graph.json` alone.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw

from app_crawler.crawl import FlowGraph

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")

_BOX_COLOR = (255, 0, 0)
_BOX_WIDTH = 4


def parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    """Parse a hierarchy `bounds="[x1,y1][x2,y2]"` string into an
    `(x1, y1, x2, y2)` pixel rectangle."""
    match = _BOUNDS_RE.search(bounds)
    if not match:
        raise ValueError(f"Malformed bounds string: {bounds!r}")
    x1, y1, x2, y2 = (int(g) for g in match.groups())
    return x1, y1, x2, y2


def draw_bounding_box(image: Image.Image, bounds: str) -> Image.Image:
    """Return a copy of `image` with a bounding box drawn at `bounds`."""
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    rect = parse_bounds(bounds)
    draw.rectangle(rect, outline=_BOX_COLOR, width=_BOX_WIDTH)
    return annotated


def _annotated_path(screenshot_path: str) -> Path:
    src = Path(screenshot_path)
    return src.with_name(f"{src.stem}_annotated{src.suffix}")


def _outgoing_edge_bounds(graph: FlowGraph, screen_id: str) -> str | None:
    """The `bounds` of the tap target on the edge(s) leaving `screen_id`, if
    any. A Screen with no outgoing edge (or whose outgoing action carries no
    `bounds`, e.g. a "back" fallback) has nothing to annotate."""
    for edge in graph.edges:
        if edge.get("from") != screen_id:
            continue
        action = edge.get("action") or {}
        bounds = action.get("bounds")
        if bounds:
            return bounds
    return None


def annotate_flow_graph(graph: FlowGraph, screenshots_dir: str | Path | None = None) -> FlowGraph:
    """Annotate every Screen in `graph` that has an outgoing edge with a
    known tap-target `bounds`, in place, and return it.

    `screenshots_dir`, if given, is joined with each Screen's
    `screenshot_path` to resolve the raw image on disk (useful when
    `graph.json` stores paths relative to a screenshots directory that has
    since moved). Screens with no outgoing edge, or whose outgoing action
    has no `bounds` (e.g. a "back" fallback), are skipped gracefully.
    """
    base = Path(screenshots_dir) if screenshots_dir is not None else None

    for screen in graph.nodes:
        bounds = _outgoing_edge_bounds(graph, screen.id)
        if bounds is None:
            continue  # leaf/terminal Screen, or no bounds recorded -- skip.
        if not screen.screenshot_path:
            continue

        raw_path = Path(screen.screenshot_path)
        resolved_path = base / raw_path if base is not None else raw_path
        if not resolved_path.exists():
            continue  # screenshot file unavailable -- skip gracefully.

        image = Image.open(resolved_path)
        annotated = draw_bounding_box(image, bounds)

        out_path = _annotated_path(resolved_path)
        annotated.save(out_path)

        # Keep screenshot_path in the same "namespace" (relative vs
        # absolute, with/without screenshots_dir prefix) it was already in.
        new_path = _annotated_path(raw_path)
        screen.screenshot_path = str(new_path)

    return graph


def annotate_graph(graph_json_path: str | Path, screenshots_dir: str | Path | None = None) -> FlowGraph:
    """Load a Flow Graph from `graph_json_path`, annotate it in place, and
    re-save `graph_json_path`. Standalone step: does not require a Crawl to
    be running, only an existing `graph.json` and its raw screenshots."""
    graph = FlowGraph.load(graph_json_path)
    annotate_flow_graph(graph, screenshots_dir=screenshots_dir)
    graph.save(graph_json_path)
    return graph
