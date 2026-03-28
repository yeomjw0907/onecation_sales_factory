from __future__ import annotations

import re
import uuid
from pathlib import Path

from sales_factory.runtime_db import ASSET_ROOT, PROJECT_ROOT, create_approval_item, create_asset, now_iso
from sales_factory.runtime_supabase import upload_asset_file


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE).strip().lower()
    return re.sub(r"[-\s]+", "-", cleaned) or "item"


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("# "):
            if current_title and current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line[2:].strip()
            current_lines = [line]
            continue

        if current_title:
            current_lines.append(line)

    if current_title and current_lines:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return sections


def parse_company_names_from_table(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if "---" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if first in {"company_name", "Company Name"}:
            continue
        if first:
            names.append(first)
    return names


def normalize_company_key(value: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\s*（[^）]*）", "", text)
    text = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", "", text)
    return text


def load_canonical_company_names() -> dict[str, str]:
    canonical_names: dict[str, str] = {}
    for source_path in [PROJECT_ROOT / "website_audit.md", PROJECT_ROOT / "lead_research.md"]:
        if not source_path.exists():
            continue
        text = source_path.read_text(encoding="utf-8", errors="replace")
        for company_name in parse_company_names_from_table(text):
            canonical_names.setdefault(normalize_company_key(company_name), company_name)
    return canonical_names


def canonicalize_company_name(company_name: str, canonical_names: dict[str, str]) -> str:
    if not canonical_names:
        return company_name

    normalized = normalize_company_key(company_name)
    if normalized in canonical_names:
        return canonical_names[normalized]

    for key, canonical in canonical_names.items():
        if normalized and (normalized in key or key in normalized):
            return canonical

    return company_name


def _write_text_asset(run_id: str, company_name: str, asset_type: str, title: str, content: str) -> str:
    company_slug = slugify(company_name)
    target_dir = ASSET_ROOT / run_id / company_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{asset_type}.md"
    target_path.write_text(content, encoding="utf-8")
    storage_metadata = upload_asset_file(
        target_path,
        storage_path=f"{run_id}/{company_slug}/{asset_type}.md",
        content_type="text/markdown",
    )

    asset_id = str(uuid.uuid4())
    create_asset(
        asset_id,
        {
            "run_id": run_id,
            "company_name": company_name,
            "asset_type": asset_type,
            "title": title,
            "path": str(target_path),
            "created_at": now_iso(),
            "metadata_json": {
                "source": "derived",
                "inline_content": content,
                **storage_metadata,
            },
        },
    )
    return asset_id


def _match_pdf(company_name: str) -> Path | None:
    output_dir = PROJECT_ROOT / "output"
    if not output_dir.exists():
        return None

    company_slug = slugify(company_name).replace("-", "")
    for candidate in sorted(output_dir.glob("*.pdf"), key=lambda item: item.stat().st_mtime, reverse=True):
        stem = slugify(candidate.stem).replace("-", "")
        if company_slug and company_slug in stem:
            return candidate
    return None


def build_company_assets(run_id: str) -> dict[str, list[str]]:
    company_assets: dict[str, list[str]] = {}
    canonical_names = load_canonical_company_names()
    sources = [
        ("proposal", PROJECT_ROOT / "proposal.md", "Proposal"),
        ("email_sequence", PROJECT_ROOT / "outreach_emails.md", "Email Sequence"),
        ("marketing_plan", PROJECT_ROOT / "marketing_plan.md", "Marketing Plan"),
        ("competitor_analysis", PROJECT_ROOT / "competitor_analysis.md", "Competitor Analysis"),
    ]

    for asset_type, source_path, title_prefix in sources:
        if not source_path.exists():
            continue

        text = source_path.read_text(encoding="utf-8", errors="replace")
        for company_name, content in split_markdown_sections(text):
            canonical_company_name = canonicalize_company_name(company_name, canonical_names)
            asset_id = _write_text_asset(
                run_id=run_id,
                company_name=canonical_company_name,
                asset_type=asset_type,
                title=f"{canonical_company_name} {title_prefix}",
                content=content,
            )
            company_assets.setdefault(canonical_company_name, []).append(asset_id)

    for company_name in list(company_assets.keys()):
        pdf_path = _match_pdf(company_name)
        if not pdf_path:
            continue
        asset_id = str(uuid.uuid4())
        create_asset(
            asset_id,
            {
                "run_id": run_id,
                "company_name": company_name,
                "asset_type": "proposal_pdf",
                "title": f"{company_name} Proposal PDF",
                "path": str(pdf_path),
                "created_at": now_iso(),
                "metadata_json": {
                    "source": "output",
                    **upload_asset_file(
                        pdf_path,
                        storage_path=f"{run_id}/{slugify(company_name)}/proposal_pdf{pdf_path.suffix.lower()}",
                    ),
                },
            },
        )
        company_assets[company_name].append(asset_id)

    return company_assets


def create_approval_queue(run_id: str, company_assets: dict[str, list[str]]) -> int:
    count = 0
    for company_name, asset_ids in sorted(company_assets.items()):
        approval_id = str(uuid.uuid4())
        create_approval_item(
            approval_id,
            {
                "run_id": run_id,
                "company_name": company_name,
                "title": f"{company_name} outbound package",
                "asset_bundle_json": asset_ids,
                "status": "waiting_approval",
                "priority": 100,
                "created_at": now_iso(),
                "metadata_json": {"gatekeeper": "external_package", "asset_type": "proposal_package"},
            },
        )
        count += 1
    return count


def route_rejection(asset_type: str, reason: str) -> list[str]:
    lowered = (reason or "").lower()

    if "email" in lowered or "\uba54\uc77c" in lowered:
        return ["email_outreach_task"]

    if (
        "competitor" in lowered
        or "market" in lowered
        or "country" in lowered
        or "\uacbd\uc7c1" in lowered
        or "\uc2dc\uc7a5" in lowered
        or "\uad6d\uac00" in lowered
    ):
        return ["competitor_analysis_task", "marketing_recommendation_task", "proposal_task"]

    if (
        "pricing" in lowered
        or "package" in lowered
        or "\uac00\uaca9" in lowered
        or "\ud328\ud0a4\uc9c0" in lowered
    ):
        return ["marketing_recommendation_task", "proposal_task"]

    if (
        "tone" in lowered
        or "message" in lowered
        or "\ubb38\uccb4" in lowered
        or "\ud1a4" in lowered
    ):
        return ["proposal_task", "email_outreach_task"]

    if asset_type == "proposal_package":
        return ["competitor_analysis_task", "marketing_recommendation_task", "proposal_task", "email_outreach_task"]

    return ["proposal_task"]
