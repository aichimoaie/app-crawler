"""Tests for the ticket-2 `run_crawl` orchestrator.

Uses faked Driver/LLMClient implementations (no real device, no real HTTP
call), extending the fake pattern from ticket 1's
`tests/test_capture_and_describe.py`. Per issue #1's testing philosophy,
these assert on `run_crawl`'s external behavior -- the returned FlowGraph
(nodes, edges) and calls made to the fakes -- not on internal helpers.
"""

from __future__ import annotations

from PIL import Image

from app_crawler.crawl import CrawlConfig, run_crawl
from app_crawler.llm_client import NavigatorResult

HIERARCHY_A = (
    '<hierarchy><node clickable="true" resource-id="btn_next" text="Next" '
    'bounds="[0,0][10,10]"/></hierarchy>'
)
HIERARCHY_B = (
    '<hierarchy><node clickable="true" resource-id="btn_back_home" text="Home" '
    'bounds="[0,0][10,10]"/></hierarchy>'
)


class FakeDriver:
    """Cycles through a fixed script of (screenshot, hierarchy) pairs,
    recording every call made to it."""

    def __init__(self, hierarchy_script: list[str]) -> None:
        self.hierarchy_script = hierarchy_script
        self._index = 0
        self.calls: list[tuple] = []
        self.connected = False
        self.started_package: str | None = None

    def connect(self) -> None:
        self.connected = True
        self.calls.append(("connect",))

    def app_start(self, package_name: str) -> None:
        self.started_package = package_name
        self.calls.append(("app_start", package_name))

    def screenshot(self) -> Image.Image:
        self.calls.append(("screenshot",))
        return Image.new("RGB", (2, 2))

    def dump_hierarchy(self) -> str:
        xml = self.hierarchy_script[min(self._index, len(self.hierarchy_script) - 1)]
        self._index += 1
        self.calls.append(("dump_hierarchy", xml))
        return xml

    def tap(self, resource_id: str | None = None, text: str | None = None) -> None:
        self.calls.append(("tap", resource_id, text))

    def back(self) -> None:
        self.calls.append(("back",))


class FakeLLMClient:
    """Returns a scripted sequence of NavigatorResults, one per call, and
    records every prompt it was called with."""

    def __init__(self, results: list[NavigatorResult]) -> None:
        self.results = results
        self._index = 0
        self.calls: list[str | None] = []

    def describe_screen(
        self,
        screenshot: Image.Image,
        hierarchy_xml: str,
        prompt: str | None = None,
    ) -> NavigatorResult:
        self.calls.append(prompt)
        result = self.results[min(self._index, len(self.results) - 1)]
        self._index += 1
        return result


def test_new_screen_calls_navigator_and_records_node_and_edge() -> None:
    driver = FakeDriver([HIERARCHY_A, HIERARCHY_B])
    llm_client = FakeLLMClient(
        [
            NavigatorResult(
                use_case="Home screen",
                raw={
                    "use_case": "Home screen",
                    "action": {"type": "tap", "target": "btn_next"},
                    "done": False,
                },
            ),
            NavigatorResult(
                use_case="Settings screen",
                raw={"use_case": "Settings screen", "action": {"type": "back"}, "done": True},
            ),
        ]
    )

    graph = run_crawl(driver, llm_client, CrawlConfig(step_cap=5))

    assert driver.connected is True
    assert driver.started_package
    assert len(graph.nodes) == 2
    assert graph.nodes[0].use_case == "Home screen"
    assert graph.nodes[1].use_case == "Settings screen"
    assert len(graph.edges) == 1
    assert graph.edges[0]["from"] == graph.nodes[0].id
    assert graph.edges[0]["to"] == graph.nodes[1].id
    assert graph.edges[0]["action"]["type"] == "tap"
    assert len(llm_client.calls) == 2


def test_dedup_by_fingerprint_skips_llm_and_records_edge() -> None:
    # Same hierarchy every step -> every step after the first is a repeat.
    driver = FakeDriver([HIERARCHY_A, HIERARCHY_A, HIERARCHY_A])
    llm_client = FakeLLMClient(
        [
            NavigatorResult(
                use_case="Home screen",
                raw={
                    "use_case": "Home screen",
                    "action": {"type": "tap", "target": "btn_next"},
                    "done": False,
                },
            )
        ]
    )

    graph = run_crawl(driver, llm_client, CrawlConfig(step_cap=3))

    # Only the first (new) screen ever reaches the Navigator.
    assert len(llm_client.calls) == 1
    assert len(graph.nodes) == 1
    # Repeats still record an edge back to the same, already-visited node.
    assert len(graph.edges) >= 1
    for edge in graph.edges:
        assert edge["to"] == graph.nodes[0].id


def test_fallback_action_on_repeated_screen_is_back() -> None:
    driver = FakeDriver([HIERARCHY_A, HIERARCHY_A])
    llm_client = FakeLLMClient(
        [
            NavigatorResult(
                use_case="Home screen",
                raw={
                    "use_case": "Home screen",
                    "action": {"type": "tap", "target": "btn_next"},
                    "done": False,
                },
            )
        ]
    )

    run_crawl(driver, llm_client, CrawlConfig(step_cap=2))

    # First step's chosen action was "tap"; on hitting the repeat, the
    # orchestrator must fall back to "back" instead of asking the LLM again.
    assert ("back",) in driver.calls
    tap_calls = [c for c in driver.calls if c[0] == "tap"]
    assert len(tap_calls) == 1  # only the first, genuinely new step tapped


def test_step_cap_enforcement_stops_crawl() -> None:
    # A fresh, never-repeating hierarchy every step, and the Navigator never
    # reports done -- only the step cap should stop the crawl.
    hierarchies = [
        f'<hierarchy><node clickable="true" resource-id="n{i}" text="N{i}" '
        f'bounds="[0,0][10,10]"/></hierarchy>'
        for i in range(10)
    ]
    driver = FakeDriver(hierarchies)
    results = [
        NavigatorResult(
            use_case=f"Screen {i}",
            raw={
                "use_case": f"Screen {i}",
                "action": {"type": "tap", "target": f"n{i}"},
                "done": False,
            },
        )
        for i in range(10)
    ]
    llm_client = FakeLLMClient(results)

    graph = run_crawl(driver, llm_client, CrawlConfig(step_cap=4))

    assert len(graph.nodes) == 4
    assert len(llm_client.calls) == 4


def test_retry_not_crash_on_hallucinated_element() -> None:
    driver = FakeDriver([HIERARCHY_A])
    llm_client = FakeLLMClient(
        [
            NavigatorResult(
                use_case="Home screen",
                raw={
                    "use_case": "Home screen",
                    # This target does not exist in HIERARCHY_A's elements.
                    "action": {"type": "tap", "target": "does_not_exist"},
                    "done": False,
                },
            ),
            NavigatorResult(
                use_case="Home screen",
                raw={
                    "use_case": "Home screen",
                    "action": {"type": "tap", "target": "btn_next"},
                    "done": True,
                },
            ),
        ]
    )

    # Must not raise, even though the first Navigator response hallucinated
    # an element that isn't present on screen.
    graph = run_crawl(driver, llm_client, CrawlConfig(step_cap=3, max_retries=2))

    assert len(graph.nodes) == 1
    # Retried once and got a valid target on the second attempt.
    assert len(llm_client.calls) == 2
    # The retry prompt should carry a corrective note.
    assert llm_client.calls[1] is not None
    assert "does_not_exist" in llm_client.calls[1]


def test_retry_exhausted_falls_back_to_back_without_crashing() -> None:
    driver = FakeDriver([HIERARCHY_A])
    always_hallucinated = NavigatorResult(
        use_case="Home screen",
        raw={
            "use_case": "Home screen",
            "action": {"type": "tap", "target": "does_not_exist"},
            "done": False,
        },
    )
    llm_client = FakeLLMClient([always_hallucinated])

    graph = run_crawl(driver, llm_client, CrawlConfig(step_cap=2, max_retries=1))

    assert len(graph.nodes) == 1
    # 1 initial call + 1 retry = 2, then falls back to "back" rather than
    # crashing or looping forever on a bad target.
    assert len(llm_client.calls) == 2
    assert ("back",) in driver.calls


def test_fakes_satisfy_the_driver_and_llm_client_protocols() -> None:
    from app_crawler.driver import Driver
    from app_crawler.llm_client import LLMClient

    assert isinstance(FakeDriver([HIERARCHY_A]), Driver)
    assert isinstance(FakeLLMClient([]), LLMClient)
