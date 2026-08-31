"""Device driver interface and uiautomator2-backed implementation.

The driver wraps device I/O for a physical Android phone connected over USB.
It is defined as a `Protocol` so the ticket-2 `run_crawl(driver, llm_client,
config) -> FlowGraph` orchestrator can be built and tested against it without
depending on this module's concrete implementation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image


@runtime_checkable
class Driver(Protocol):
    """Device I/O needed to capture and act on a Screen.

    Methods intentionally mirror the vocabulary in CONTEXT.md: a call
    captures a Screen's screenshot/hierarchy, or acts on the device
    (launching the target app). Tap-by-selector/back are out of scope for
    this ticket and will be added when the crawl loop (ticket 2) needs them.
    """

    def connect(self) -> None:
        """Connect to the physical device over USB (via adb)."""
        ...

    def app_start(self, package_name: str) -> None:
        """Launch the target app by package name (activity-manager launch,
        not a home-screen tap)."""
        ...

    def screenshot(self) -> Image.Image:
        """Capture a screenshot of the current Screen."""
        ...

    def dump_hierarchy(self) -> str:
        """Dump the current Screen's UI hierarchy as XML."""
        ...


class UiAutomator2Driver:
    """Concrete `Driver` backed by `uiautomator2`, for a real device."""

    def __init__(self, serial: str | None = None) -> None:
        self._serial = serial
        self._device = None

    def connect(self) -> None:
        import uiautomator2 as u2

        self._device = u2.connect(self._serial) if self._serial else u2.connect()

    def app_start(self, package_name: str) -> None:
        if self._device is None:
            raise RuntimeError("Driver.connect() must be called before app_start()")
        self._device.app_start(package_name)

    def screenshot(self) -> Image.Image:
        if self._device is None:
            raise RuntimeError("Driver.connect() must be called before screenshot()")
        return self._device.screenshot()

    def dump_hierarchy(self) -> str:
        if self._device is None:
            raise RuntimeError("Driver.connect() must be called before dump_hierarchy()")
        return self._device.dump_hierarchy()
