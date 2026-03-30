from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ONECATION_PROOF_POINTS = (
    "No approved Onecation case studies were supplied. "
    "Do not invent named clients, case studies, revenue lifts, conversion metrics, awards, or years. "
    "In `## Why Onecation`, use only factual execution strengths, cross-border fit, and process credibility."
)


def load_onecation_proof_points(project_root: Path | None = None) -> str:
    env_value = os.environ.get("SALES_FACTORY_ONECATION_PROOF_POINTS", "").strip()
    if env_value:
        return env_value

    root_dir = project_root or Path(__file__).resolve().parents[2]
    proof_path = root_dir / "knowledge" / "onecation_proof_points.md"
    if proof_path.exists():
        proof_text = proof_path.read_text(encoding="utf-8", errors="replace").strip()
        if proof_text:
            return proof_text

    return DEFAULT_ONECATION_PROOF_POINTS
