"""LLM client interface and OpenRouter-backed implementation.

The client wraps the Navigator call: given a Screen's screenshot and UI
hierarchy, it returns structured JSON describing the Screen (at minimum a
Use Case description, per CONTEXT.md). Defined as a `Protocol` so the
ticket-2 `run_crawl` orchestrator can be built and tested against it without
depending on this module's concrete implementation.
"""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from dotenv import load_dotenv
from PIL import Image

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
NAVIGATOR_MODEL = "qwen/qwen2.5-vl-32b-instruct:free"

_DEFAULT_NAVIGATOR_PROMPT = (
    "You are the Navigator for an app-crawling pipeline. You are shown a "
    "screenshot and the UI hierarchy XML of the current screen of an "
    "Android trading app. Respond with a single JSON object only "
    '(no markdown fences), with at least this field:\n'
    '{"use_case": "<a short, client-facing description of what this screen '
    'is for and what a user does on it>"}\n'
    "You may include additional fields (screen_id, action, done) if useful, "
    "but use_case is required."
)


@dataclass
class NavigatorResult:
    """Structured result of a Navigator call.

    `use_case` is the one field this ticket relies on. `raw` keeps the full
    parsed JSON response so later tickets (which need `action`/`done`/
    `screen_id` per the Navigator contract in issue #1) can read it without
    a shape change here.
    """

    use_case: str
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMClient(Protocol):
    """LLM call needed to describe a Screen from a screenshot + hierarchy."""

    def describe_screen(
        self,
        screenshot: Image.Image,
        hierarchy_xml: str,
        prompt: str | None = None,
    ) -> NavigatorResult:
        """Send a screenshot and UI hierarchy to the Navigator and return
        its structured description of the Screen."""
        ...


class OpenRouterLLMClient:
    """Concrete `LLMClient` calling OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = NAVIGATOR_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
    ) -> None:
        load_dotenv()
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add it to a git-ignored .env "
                "file (see .env.example)."
            )
        from openai import OpenAI

        self._model = model
        self._client = OpenAI(api_key=resolved_key, base_url=base_url)

    def describe_screen(
        self,
        screenshot: Image.Image,
        hierarchy_xml: str,
        prompt: str | None = None,
    ) -> NavigatorResult:
        image_b64 = _image_to_base64(screenshot)
        text_prompt = prompt or _DEFAULT_NAVIGATOR_PROMPT

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"{text_prompt}\n\nUI hierarchy:\n{hierarchy_xml}",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                }
            ],
        )

        content = response.choices[0].message.content or ""
        parsed = _parse_json_response(content)
        use_case = parsed.get("use_case", "")
        return NavigatorResult(use_case=use_case, raw=parsed)


def _image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _parse_json_response(content: str) -> dict[str, Any]:
    """Parse the model's JSON response, tolerating markdown code fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[len("json") :]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Navigator response was not valid JSON: {content!r}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"Navigator response was not a JSON object: {content!r}")
    return parsed
