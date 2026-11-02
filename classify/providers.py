"""The real AI behind the provider slot in llm_step.py.

The model is picked here, as a string, and not in the Console. To try another
model, change MODEL (or pass model=...) and nothing else needs to change.
The key is read from ANTHROPIC_API_KEY in .env and is never printed or logged.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = "claude-haiku-5-5"  # the small, cheap model. Plenty for a short classification.


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = MODEL, max_tokens: int = 1500, timeout: float = 30.0, client=None):
        self.model = model
        self.max_tokens = max_tokens
        if client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env.")
            import anthropic  # imported here so the tests do not need the package
            client = anthropic.Anthropic(timeout=timeout)  # picks the key up from the environment
        self._client = client
        self.last_meta = None  # why the last call ended and what it used, for the audit log

    def complete(self, prompt: str) -> str:
        message = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = getattr(message, "usage", None)
        self.last_meta = {
            "stop_reason": getattr(message, "stop_reason", None),
            "block_types": [block.type for block in message.content],
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        }
        # If the model declines or returns no text, this is an empty string, which
        # the step turns into unknown instead of crashing.
        return "".join(block.text for block in message.content if block.type == "text")
