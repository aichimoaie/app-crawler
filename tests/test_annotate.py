"""Tests for ticket-3 screenshot annotation.

Per issue #4's testing guidance: assert on output image dimensions and that
pixel data changed at the expected `bounds` region, given a fixed input
image and a fixed `bounds` rectangle -- not on exact pixel values, which
would be brittle.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app_crawler.annotate import annotate_flow_graph, annotate_graph, draw_bounding_box, parse_bounds
from app_crawler.crawl import FlowGraph, Screen

BOUNDS = "[10,10][40,40]"


def _solid_image(size: tuple[int, int] = (100, 100), color=(255, 255, 255)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_parse_bounds() -> None:
    assert parse_bounds("[10,20][30,40]") == (10, 20, 30, 40)


def test_draw_bounding_box_preserves_dimensions_and_changes_pixels_in_bounds() -> None:
    image = _solid_image()
    annotated = draw_bounding_box(image, BOUNDS)

    assert annotated.size == image.size

    x1, y1, x2, y2 = parse_bounds(BOUNDS)
    before = image.load()
    after = annotated.load()

    # The box outline touches the rectangle's border pixels -- assert at
    # least one pixel along the border changed, without pinning exact color.
    border_pixels = [(x1, y1), (x2 - 1, y1), (x1, y2 - 1), ((x1 + x2) // 2, y1)]
    changed = any(before[px] != after[px] for px in border_pixels)
    assert changed

    # Pixels well outside the box are untouched.
    assert before[90, 90] == after[90, 90]


def test_annotate_flow_graph_skips_leaf_screen(tmp_path: Path) -> None:
    img_path = tmp_path / "screen_0.png"
    _solid_image().save(img_path)

    graph = FlowGraph(
        nodes=[
            Screen(id="screen_0", fingerprint="fp0", screenshot_path=str(img_path), use_case="Leaf"),
        ],
        edges=[],  # no outgoing edge -> leaf screen
    )

    annotate_flow_graph(graph)

    # Left unannotated, screenshot_path unchanged, no error raised.
    assert graph.nodes[0].screenshot_path == str(img_path)
    assert not (tmp_path / "screen_0_annotated.png").exists()


def test_annotate_flow_graph_annotates_screen_with_outgoing_edge(tmp_path: Path) -> None:
    img_path = tmp_path / "screen_0.png"
    _solid_image().save(img_path)

    graph = FlowGraph(
        nodes=[
            Screen(id="screen_0", fingerprint="fp0", screenshot_path=str(img_path), use_case="Home"),
            Screen(id="screen_1", fingerprint="fp1", screenshot_path="", use_case="Next"),
        ],
        edges=[
            {
                "from": "screen_0",
                "action": {"type": "tap", "target": "btn_next", "bounds": BOUNDS},
                "to": "screen_1",
            }
        ],
    )

    annotate_flow_graph(graph)

    expected_path = tmp_path / "screen_0_annotated.png"
    assert graph.nodes[0].screenshot_path == str(expected_path)
    assert expected_path.exists()

    original = Image.open(img_path)
    annotated = Image.open(expected_path)
    assert annotated.size == original.size

    x1, y1, x2, y2 = parse_bounds(BOUNDS)
    before = original.load()
    after = annotated.load()
    assert before[x1, y1] != after[x1, y1]
    assert before[90, 90] == after[90, 90]


def test_annotate_graph_updates_graph_json_screenshot_path(tmp_path: Path) -> None:
    img_path = tmp_path / "screen_0.png"
    _solid_image().save(img_path)

    graph = FlowGraph(
        nodes=[
            Screen(id="screen_0", fingerprint="fp0", screenshot_path=str(img_path), use_case="Home"),
            Screen(id="screen_1", fingerprint="fp1", screenshot_path="", use_case="Leaf"),
        ],
        edges=[
            {
                "from": "screen_0",
                "action": {"type": "tap", "target": "btn_next", "bounds": BOUNDS},
                "to": "screen_1",
            }
        ],
    )
    graph_path = tmp_path / "graph.json"
    graph.save(graph_path)

    result = annotate_graph(graph_path)

    expected_path = str(tmp_path / "screen_0_annotated.png")
    assert result.nodes[0].screenshot_path == expected_path

    reloaded = FlowGraph.load(graph_path)
    assert reloaded.nodes[0].screenshot_path == expected_path
    # Leaf screen (screen_1) untouched.
    assert reloaded.nodes[1].screenshot_path == ""


def test_annotate_graph_leaf_screen_graceful_no_error(tmp_path: Path) -> None:
    img_path = tmp_path / "screen_0.png"
    _solid_image().save(img_path)

    graph = FlowGraph(
        nodes=[Screen(id="screen_0", fingerprint="fp0", screenshot_path=str(img_path), use_case="Leaf")],
        edges=[],
    )
    graph_path = tmp_path / "graph.json"
    graph.save(graph_path)

    result = annotate_graph(graph_path)

    assert result.nodes[0].screenshot_path == str(img_path)
