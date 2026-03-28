from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.runtime_supabase import cached_asset_path, materialize_local_asset, read_asset_text


class RuntimeSupabaseTests(unittest.TestCase):
    def test_materialize_local_asset_uses_inline_content(self) -> None:
        target_path = ROOT_DIR / "missing-inline-preview.md"
        cached_path = cached_asset_path(target_path)
        if cached_path.exists():
            cached_path.unlink()

        materialized = materialize_local_asset(
            target_path,
            {"inline_content": "# Inline Preview\nhello"},
        )

        self.assertIsNotNone(materialized)
        self.assertTrue(materialized.exists())
        self.assertEqual(materialized.read_text(encoding="utf-8"), "# Inline Preview\nhello")

        if cached_path.exists():
            cached_path.unlink()

    def test_read_asset_text_falls_back_to_inline_content(self) -> None:
        target_path = ROOT_DIR / "missing-inline-read.md"
        cached_path = cached_asset_path(target_path)
        if cached_path.exists():
            cached_path.unlink()

        text = read_asset_text(
            target_path,
            {"inline_content": "fallback body"},
        )

        self.assertEqual(text, "fallback body")

        if cached_path.exists():
            cached_path.unlink()


if __name__ == "__main__":
    unittest.main()
