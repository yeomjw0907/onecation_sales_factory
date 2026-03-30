from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REQUIRED_HEADINGS: list[tuple[str, int]] = [
    ("## Greeting", 6),
    ("## Executive Summary", 8),
    ("## What We Found", 8),
    ("## Why This Matters", 8),
    ("## Market And Competitor Snapshot", 10),
    ("## Your Hidden Strengths", 8),
    ("## Recommended Direction", 8),
    ("## 30-60-90 Day Execution Plan", 12),
    ("## Recommended Packages", 12),
    ("## Pricing Guidance", 6),
    ("## Why Onecation", 6),
    ("## Suggested Next Step", 4),
    ("## Closing", 2),
]


def normalize_heading(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip()).lower()
    return normalized


def collect_h2_headings(text: str) -> set[str]:
    return {
        normalize_heading(match.group(1))
        for match in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
    }


def _label(score: int) -> str:
    if score >= 85:
        return "강함"
    if score >= 70:
        return "양호"
    if score >= 55:
        return "보완 필요"
    return "낮음"


def evaluate_proposal_text(text: str) -> dict[str, Any]:
    score = 0
    missing_sections: list[str] = []
    detected_h2 = collect_h2_headings(text)

    for heading, weight in REQUIRED_HEADINGS:
        heading_text = heading.replace("## ", "", 1)
        if normalize_heading(heading_text) in detected_h2:
            score += weight
        else:
            missing_sections.append(heading_text)

    table_count = len(re.findall(r"^\|.+\|$", text, flags=re.MULTILINE))
    bullet_count = len(re.findall(r"^\s*[-*]\s+", text, flags=re.MULTILINE))
    paragraph_count = len([chunk for chunk in re.split(r"\n\s*\n", text) if chunk.strip()])
    evidence_hits = len(re.findall(r"\b(why|because|risk|opportunity|proof|market|competitor|pricing)\b", text, flags=re.IGNORECASE))

    bonus = 0
    if table_count >= 2:
        bonus += 6
    elif table_count == 1:
        bonus += 3
    if bullet_count >= 10:
        bonus += 5
    elif bullet_count >= 5:
        bonus += 3
    if paragraph_count >= 8:
        bonus += 4
    if evidence_hits >= 8:
        bonus += 5

    score = min(100, score + bonus)

    return {
        "score": score,
        "label": _label(score),
        "missing_sections": missing_sections,
        "table_count": table_count,
        "bullet_count": bullet_count,
        "paragraph_count": paragraph_count,
    }


def evaluate_proposal_path(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "score": 0,
            "label": "파일 없음",
            "missing_sections": [],
            "table_count": 0,
            "bullet_count": 0,
            "paragraph_count": 0,
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    return evaluate_proposal_text(text)
