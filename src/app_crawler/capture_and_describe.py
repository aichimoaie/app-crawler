"""Ticket 1 entrypoint: single-Screen capture and describe.

Connects to a physical device, launches the target app, captures one
screenshot and UI hierarchy dump for the launched Screen, sends both to the
Navigator, and prints the returned Use Case description to stdout.

This proves the two external integrations (device driver, LLM client) work
end to end before the crawl loop (ticket 2) is built on top of the `Driver`
and `LLMClient` interfaces in `driver.py` / `llm_client.py`.
"""

from __future__ import annotations

from app_crawler.driver import Driver, UiAutomator2Driver
from app_crawler.llm_client import LLMClient, NavigatorResult, OpenRouterLLMClient

TARGET_PACKAGE = "com.smctrading.android"


def capture_and_describe(driver: Driver, llm_client: LLMClient) -> NavigatorResult:
    """Launch the target app, capture its screen, and describe it.

    Kept as a plain function (not folded into `main`) so it is the seam a
    test exercises with fake `driver`/`llm_client` implementations.
    """
    driver.connect()
    driver.app_start(TARGET_PACKAGE)

    screenshot = driver.screenshot()
    hierarchy_xml = driver.dump_hierarchy()

    return llm_client.describe_screen(screenshot, hierarchy_xml)


def main() -> None:
    driver = UiAutomator2Driver()
    llm_client = OpenRouterLLMClient()

    result = capture_and_describe(driver, llm_client)
    print(result.use_case)


if __name__ == "__main__":
    main()
