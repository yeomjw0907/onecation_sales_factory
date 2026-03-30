from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sales_factory.brand_proof import DEFAULT_ONECATION_PROOF_POINTS, load_onecation_proof_points


class BrandProofTests(unittest.TestCase):
    def test_load_onecation_proof_points_reads_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            knowledge_dir = root_dir / "knowledge"
            knowledge_dir.mkdir(parents=True, exist_ok=True)
            proof_path = knowledge_dir / "onecation_proof_points.md"
            proof_path.write_text("Approved proof.", encoding="utf-8")

            self.assertEqual(load_onecation_proof_points(root_dir), "Approved proof.")

    def test_load_onecation_proof_points_prefers_env_override(self) -> None:
        with patch.dict("os.environ", {"SALES_FACTORY_ONECATION_PROOF_POINTS": "Env proof."}, clear=False):
            self.assertEqual(load_onecation_proof_points(), "Env proof.")

    def test_load_onecation_proof_points_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict("os.environ", {}, clear=True):
            self.assertEqual(load_onecation_proof_points(Path(temp_dir)), DEFAULT_ONECATION_PROOF_POINTS)


if __name__ == "__main__":
    unittest.main()
