import os
import unittest
from unittest.mock import patch

from sales_factory.crew import resolve_llm_model


class CrewFallbackTests(unittest.TestCase):
    def test_keeps_anthropic_when_provider_and_key_exist(self) -> None:
        with patch("sales_factory.crew.importlib.util.find_spec", return_value=object()):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
                self.assertEqual(
                    resolve_llm_model("anthropic/claude-sonnet-4-5"),
                    "anthropic/claude-sonnet-4-5",
                )

    def test_falls_back_when_anthropic_package_missing(self) -> None:
        with patch("sales_factory.crew.importlib.util.find_spec", return_value=None):
            with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
                self.assertEqual(
                    resolve_llm_model("anthropic/claude-sonnet-4-5"),
                    "gemini/gemini-2.5-pro",
                )

    def test_falls_back_when_anthropic_key_missing(self) -> None:
        with patch("sales_factory.crew.importlib.util.find_spec", return_value=object()):
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(
                    resolve_llm_model("anthropic/claude-sonnet-4-5"),
                    "gemini/gemini-2.5-pro",
                )


if __name__ == "__main__":
    unittest.main()
