"""Tests for the ticket-4 Writer step (`app_crawler.prd`).

Uses a small canned FlowGraph fixture and a fake LLMClient (no real HTTP
call). Per the issue's acceptance criteria, these assert on Markdown
*structure* -- one section per Screen, a screenshot reference present, and
the Use Case text present -- not on exact LLM-generated prose.
"""

from __future__ import annotations

from pathlib import Path

from app_crawler.crawl import FlowGraph, Screen
from app_crawler.prd import generate_prd_markdown, write_prd


class FakeWriterLLMClient:
    """Records calls and returns a canned architecture/flow summary."""

    def __init__(self, summary: str = "This is a fake architecture summary.") -> None:
        self.summary = summary
        self.calls: list[FlowGraph] = []

    def write_summary(self, graph: FlowGraph, prompt: str | None = None) -> str:
        self.calls.append(graph)
        return self.summary

    def describe_screen(self, *args, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError


def _make_graph() -> FlowGraph:
    nodes = [
        Screen(
            id="screen_0",
            fingerprint="fp0",
            screenshot_path="out/screen_0.png",
            use_case="Log in with a username and password.",
        ),
        Screen(
            id="screen_1",
            fingerprint="fp1",
            screenshot_path="out/screen_1_annotated.png",
            use_case="View the portfolio dashboard and account balance.",
        ),
        Screen(
            id="screen_2",
            fingerprint="fp2",
            screenshot_path="out/screen_2.png",
            use_case="Place a buy order for a selected instrument.",
        ),
    ]
    edges = [
        {"from": "screen_0", "action": {"type": "tap", "target": "btn_login"}, "to": "screen_1"},
        {"from": "screen_1", "action": {"type": "tap", "target": "btn_trade"}, "to": "screen_2"},
    ]
    return FlowGraph(nodes=nodes, edges=edges)


def test_generate_prd_markdown_has_one_section_per_screen():
    graph = _make_graph()
    llm_client = FakeWriterLLMClient()

    markdown = generate_prd_markdown(graph, llm_client)

    for node in graph.nodes:
        assert f"### {node.id}" in markdown


def test_generate_prd_markdown_includes_screenshot_and_use_case_per_screen():
    graph = _make_graph()
    llm_client = FakeWriterLLMClient()

    markdown = generate_prd_markdown(graph, llm_client)

    for node in graph.nodes:
        assert node.screenshot_path in markdown
        assert node.use_case in markdown


def test_generate_prd_markdown_includes_architecture_summary():
    graph = _make_graph()
    llm_client = FakeWriterLLMClient(summary="A distinctive canned summary sentence.")

    markdown = generate_prd_markdown(graph, llm_client)

    assert "## Architecture & Flow Summary" in markdown
    assert "A distinctive canned summary sentence." in markdown
    assert llm_client.calls == [graph]


def test_generate_prd_markdown_use_case_appears_after_its_own_screenshot():
    graph = _make_graph()
    llm_client = FakeWriterLLMClient()

    markdown = generate_prd_markdown(graph, llm_client)

    for node in graph.nodes:
        screenshot_index = markdown.index(node.screenshot_path)
        use_case_index = markdown.index(node.use_case)
        assert use_case_index > screenshot_index


def test_write_prd_loads_graph_json_and_writes_prd_md(tmp_path: Path):
    graph = _make_graph()
    graph_path = tmp_path / "graph.json"
    graph.save(graph_path)

    output_path = tmp_path / "PRD.md"
    llm_client = FakeWriterLLMClient()

    result_path = write_prd(graph_path, output_path=output_path, llm_client=llm_client)

    assert result_path == output_path
    content = output_path.read_text()
    for node in graph.nodes:
        assert f"### {node.id}" in content
        assert node.screenshot_path in content
        assert node.use_case in content
