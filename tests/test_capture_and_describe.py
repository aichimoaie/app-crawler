"""Tests for the ticket-1 capture-and-describe entrypoint.

Uses fake Driver/LLMClient implementations (no real device, no real HTTP
call) to verify the entrypoint's wiring: connect -> app_start -> screenshot
+ hierarchy -> describe_screen -> returned Use Case. Per issue #1's testing
philosophy, this asserts on external behavior at the seam (calls made,
value returned), not on internals of either fake.
"""

from __future__ import annotations

from PIL import Image

from app_crawler.capture_and_describe import TARGET_PACKAGE, capture_and_describe
from app_crawler.llm_client import NavigatorResult


class FakeDriver:
    def __init__(self) -> None:
        self.connected = False
        self.started_package: str | None = None
        self.calls: list[str] = []

    def connect(self) -> None:
        self.connected = True
        self.calls.append("connect")

    def app_start(self, package_name: str) -> None:
        self.started_package = package_name
        self.calls.append("app_start")

    def screenshot(self) -> Image.Image:
        self.calls.append("screenshot")
        return Image.new("RGB", (2, 2))

    def dump_hierarchy(self) -> str:
        self.calls.append("dump_hierarchy")
        return "<hierarchy/>"


class FakeLLMClient:
    def __init__(self) -> None:
        self.received_hierarchy: str | None = None
        self.received_screenshot: Image.Image | None = None

    def describe_screen(
        self,
        screenshot: Image.Image,
        hierarchy_xml: str,
        prompt: str | None = None,
    ) -> NavigatorResult:
        self.received_screenshot = screenshot
        self.received_hierarchy = hierarchy_xml
        return NavigatorResult(
            use_case="Login screen where the user enters credentials to sign in.",
            raw={"use_case": "Login screen where the user enters credentials to sign in."},
        )


def test_capture_and_describe_wires_driver_and_llm_client() -> None:
    driver = FakeDriver()
    llm_client = FakeLLMClient()

    result = capture_and_describe(driver, llm_client)

    assert driver.connected is True
    assert driver.started_package == TARGET_PACKAGE
    assert driver.calls == ["connect", "app_start", "screenshot", "dump_hierarchy"]

    assert llm_client.received_hierarchy == "<hierarchy/>"
    assert llm_client.received_screenshot is not None

    assert result.use_case == "Login screen where the user enters credentials to sign in."


def test_fakes_satisfy_the_driver_and_llm_client_protocols() -> None:
    from app_crawler.driver import Driver
    from app_crawler.llm_client import LLMClient

    assert isinstance(FakeDriver(), Driver)
    assert isinstance(FakeLLMClient(), LLMClient)
