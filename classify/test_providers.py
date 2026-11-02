"""Checks for the real provider without calling the real AI. Run: python -m unittest classify.test_providers -v"""
import unittest
from types import SimpleNamespace

from classify.providers import AnthropicProvider


class FakeClient:
    def __init__(self, blocks):
        self.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(content=blocks))


class ProviderTests(unittest.TestCase):
    def test_returns_the_text_blocks(self):
        blocks = [SimpleNamespace(type="text", text='{"cause": "unknown"}')]
        self.assertEqual(AnthropicProvider(client=FakeClient(blocks)).complete("x"), '{"cause": "unknown"}')

    def test_empty_reply_is_an_empty_string_not_a_crash(self):
        self.assertEqual(AnthropicProvider(client=FakeClient([])).complete("x"), "")

    def test_non_text_blocks_are_ignored(self):
        blocks = [SimpleNamespace(type="thinking", text="x"), SimpleNamespace(type="text", text="ok")]
        self.assertEqual(AnthropicProvider(client=FakeClient(blocks)).complete("x"), "ok")

    def test_records_why_the_call_ended(self):
        provider = AnthropicProvider(client=FakeClient([]))
        provider._client.messages.create = lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(type="thinking", text="")], stop_reason="max_tokens",
            usage=SimpleNamespace(input_tokens=900, output_tokens=300))
        self.assertEqual(provider.complete("x"), "")
        self.assertEqual(provider.last_meta["stop_reason"], "max_tokens")
        self.assertEqual(provider.last_meta["block_types"], ["thinking"])

    def test_model_defaults_to_the_small_model(self):
        self.assertEqual(AnthropicProvider(client=FakeClient([])).model, "claude-haiku-5-5")


if __name__ == "__main__":
    unittest.main()
