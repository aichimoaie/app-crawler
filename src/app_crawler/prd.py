"""Ticket 4: standalone Writer step -- generate `PRD.md` from `graph.json`.

Design choice: the acceptance criteria require the *structure* of the PRD
(one section per Screen, a screenshot reference, and the Use Case text
directly below it) to be reliably testable without asserting on any LLM
prose. Rather than asking the LLM to produce the whole Markdown document --
which would make that structure only probabilistically correct -- this
module has Python deterministically assemble the per-screen sections
(screenshot path + use case are already known, structured data on the
FlowGraph) and uses the LLM call only for the free-text architecture/flow
summary at the top, where creative synthesis is actually needed and exact
structure doesn't matter. This mirrors the Navigator/Writer split in
CONTEXT.md while keeping the acceptance-tested structure deterministic.

Runnable standalone, independent of `run_crawl`/`annotate`, per the spec
requirement that PRD regeneration doesn't require re-crawling.
"""

from __future__ import annotations

from pathlib import Path

from app_crawler.crawl import FlowGraph
from app_crawler.llm_client import WriterLLMClient

_FALLBACK_SUMMARY = (
    "This document summarizes the Screens discovered during the Crawl and "
    "the taps that connect them."
)


def generate_prd_markdown(graph: FlowGraph, llm_client: WriterLLMClient) -> str:
    """Build the full PRD Markdown body for a Flow Graph: an
    architecture/flow summary (from the Writer LLM call) followed by one
    deterministically-assembled section per Screen."""
    try:
        summary = llm_client.write_summary(graph)
    except AttributeError:
        summary = _FALLBACK_SUMMARY
    summary = (summary or _FALLBACK_SUMMARY).strip()

    lines = ["# PRD", "", "## Architecture & Flow Summary", "", summary, ""]

    lines.append("## Screens")
    lines.append("")
    for node in graph.nodes:
        lines.append(f"### {node.id}")
        lines.append("")
        if node.screenshot_path:
            lines.append(f"![{node.id}]({node.screenshot_path})")
            lines.append("")
        lines.append(node.use_case)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_prd(
    graph_json_path: str | Path,
    output_path: str | Path = "PRD.md",
    llm_client: WriterLLMClient | None = None,
) -> Path:
    """Load `graph.json` and write the generated `PRD.md`, standalone --
    no device access, no re-crawling. Returns the path written."""
    if llm_client is None:
        from app_crawler.llm_client import OpenRouterLLMClient

        llm_client = OpenRouterLLMClient()

    graph = FlowGraph.load(graph_json_path)
    markdown = generate_prd_markdown(graph, llm_client)

    out_path = Path(output_path)
    out_path.write_text(markdown)
    return out_path
