from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.runtime_supabase import (
    cached_asset_path,
    get_runtime_backend,
    get_supabase_key_candidates,
    materialize_local_asset,
    read_asset_text,
    verify_schema,
)


class RuntimeSupabaseTests(unittest.TestCase):
    def test_runtime_backend_defaults_to_supabase_when_credentials_exist(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "secret",
            },
            clear=True,
        ):
            with patch("sales_factory.runtime_supabase.load_project_env", return_value=None):
                self.assertEqual(get_runtime_backend(), "supabase")

    def test_runtime_backend_respects_explicit_sqlite(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SALES_FACTORY_RUNTIME_BACKEND": "sqlite",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "secret",
            },
            clear=True,
        ):
            with patch("sales_factory.runtime_supabase.load_project_env", return_value=None):
                self.assertEqual(get_runtime_backend(), "sqlite")

    def test_get_supabase_key_candidates_returns_both_keys_in_priority_order(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SUPABASE_SECRET_KEY": "secret-key",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            },
            clear=True,
        ):
            with patch("sales_factory.runtime_supabase.load_project_env", return_value=None):
                self.assertEqual(
                    get_supabase_key_candidates(),
                    [
                        ("SUPABASE_SECRET_KEY", "secret-key"),
                        ("SUPABASE_SERVICE_ROLE_KEY", "service-role-key"),
                    ],
                )

    def test_verify_schema_falls_back_to_service_role_when_secret_key_fails(self) -> None:
        class FakeQuery:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail

            def select(self, *_args, **_kwargs):
                return self

            def limit(self, *_args, **_kwargs):
                return self

            def execute(self):
                if self.should_fail:
                    raise RuntimeError("invalid key")
                return type("Response", (), {"data": []})()

        class FakeClient:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail

            def table(self, _name: str):
                return FakeQuery(self.should_fail)

        def fake_create_client(_url: str, key: str):
            return FakeClient(should_fail=(key == "bad-secret"))

        with patch.dict(
            "os.environ",
            {
                "SALES_FACTORY_RUNTIME_BACKEND": "supabase",
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "bad-secret",
                "SUPABASE_SERVICE_ROLE_KEY": "good-service-role",
            },
            clear=True,
        ):
            with patch("sales_factory.runtime_supabase.load_project_env", return_value=None), patch(
                "sales_factory.runtime_supabase.create_client",
                side_effect=fake_create_client,
            ):
                import sales_factory.runtime_supabase as runtime_supabase

                runtime_supabase._CLIENT = None
                verify_schema()
                self.assertIsNotNone(runtime_supabase._CLIENT)

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
