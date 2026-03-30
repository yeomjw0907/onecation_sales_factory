from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from sales_factory.delivery_manager import collect_delivery_guard_issues, load_verified_company_facts
from sales_factory.output_validation import collect_validation_issues, normalize_customer_text
from sales_factory.runtime_db import ASSET_ROOT, create_approval_item, create_asset, now_iso
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


def load_canonical_company_names(workspace_dir: Path) -> dict[str, str]:
    canonical_names: dict[str, str] = {}
    for source_path in [
        workspace_dir / "website_audit.md",
        workspace_dir / "lead_verification.md",
        workspace_dir / "identity_disambiguation.md",
        workspace_dir / "lead_research.md",
    ]:
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


def _match_output_file(output_dir: Path, company_name: str, suffix: str) -> Path | None:
    if not output_dir.exists():
        return None

    company_slug = slugify(company_name).replace("-", "")
    for candidate in sorted(output_dir.glob(f"*{suffix}"), key=lambda item: item.stat().st_mtime, reverse=True):
        stem = slugify(candidate.stem).replace("-", "")
        if company_slug and company_slug in stem:
            return candidate
    return None


def _register_binary_asset(run_id: str, company_name: str, asset_type: str, title: str, file_path: Path, storage_name: str) -> str:
    company_slug = slugify(company_name)
    target_dir = ASSET_ROOT / run_id / company_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{asset_type}{file_path.suffix.lower()}"
    shutil.copy2(file_path, target_path)

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
                "source": "output_copy",
                "original_path": str(file_path),
                **upload_asset_file(
                    target_path,
                    storage_path=f"{run_id}/{company_slug}/{storage_name}{file_path.suffix.lower()}",
                ),
            },
        },
    )
    return asset_id


def build_company_assets(
    run_id: str,
    *,
    workspace_dir: Path,
    output_dir: Path,
    proposal_language: str | None = None,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    company_assets: dict[str, list[str]] = {}
    validation_issues: dict[str, list[str]] = {}
    canonical_names = load_canonical_company_names(workspace_dir)
    verified_facts = load_verified_company_facts(workspace_dir)
    sources = [
        ("proposal", workspace_dir / "proposal.md", "Proposal"),
        ("email_sequence", workspace_dir / "outreach_emails.md", "Email Sequence"),
        ("marketing_plan", workspace_dir / "marketing_plan.md", "Marketing Plan"),
        ("competitor_analysis", workspace_dir / "competitor_analysis.md", "Competitor Analysis"),
    ]

    for asset_type, source_path, title_prefix in sources:
        if not source_path.exists():
            continue

        text = source_path.read_text(encoding="utf-8", errors="replace")
        for company_name, content in split_markdown_sections(text):
            canonical_company_name = canonicalize_company_name(company_name, canonical_names)
            normalized_content = normalize_customer_text(content, asset_type=asset_type)
            issues = collect_validation_issues(
                normalized_content,
                asset_type=asset_type,
                proposal_language=proposal_language,
            )
            issues.extend(
                collect_delivery_guard_issues(
                    normalized_content,
                    asset_type=asset_type,
                    facts=verified_facts.get(normalize_company_key(canonical_company_name)),
                )
            )
            if issues:
                validation_issues.setdefault(canonical_company_name, []).extend(issues)
            asset_id = _write_text_asset(
                run_id=run_id,
                company_name=canonical_company_name,
                asset_type=asset_type,
                title=f"{canonical_company_name} {title_prefix}",
                content=normalized_content,
            )
            company_assets.setdefault(canonical_company_name, []).append(asset_id)

    for company_name in list(company_assets.keys()):
        docx_path = _match_output_file(output_dir, company_name, ".docx")
        if docx_path:
            asset_id = _register_binary_asset(
                run_id=run_id,
                company_name=company_name,
                asset_type="proposal_docx",
                title=f"{company_name} Proposal DOCX",
                file_path=docx_path,
                storage_name="proposal_docx",
            )
            company_assets[company_name].append(asset_id)

        pdf_path = _match_output_file(output_dir, company_name, ".pdf")
        if not pdf_path:
            continue
        asset_id = _register_binary_asset(
            run_id=run_id,
            company_name=company_name,
            asset_type="proposal_pdf",
            title=f"{company_name} Proposal PDF",
            file_path=pdf_path,
            storage_name="proposal_pdf",
        )
        company_assets[company_name].append(asset_id)

    deduped_issues = {company: sorted(set(issues)) for company, issues in validation_issues.items() if issues}
    return company_assets, deduped_issues


def create_approval_queue(
    run_id: str,
    company_assets: dict[str, list[str]],
    validation_issues: dict[str, list[str]] | None = None,
) -> int:
    count = 0
    issues_by_company = validation_issues or {}
    for company_name, asset_ids in sorted(company_assets.items()):
        company_issues = issues_by_company.get(company_name, [])
        approval_id = str(uuid.uuid4())
        create_approval_item(
            approval_id,
            {
                "run_id": run_id,
                "company_name": company_name,
                "title": f"{company_name} outbound package",
                "asset_bundle_json": asset_ids,
                "status": "waiting_approval",
                "priority": 120 if company_issues else 100,
                "created_at": now_iso(),
                "metadata_json": {
                    "gatekeeper": "external_package",
                    "asset_type": "proposal_package",
                    "validation_issues": company_issues,
                },
            },
        )
        count += 1
    return count


def route_rejection(asset_type: str, reason: str) -> list[str]:
    lowered = (reason or "").lower()

    if (
        "translation" in lowered
        or "localization" in lowered
        or "locale" in lowered
        or "language" in lowered
        or "\ubc88\uc5ed" in lowered
        or "\ud604\uc9c0\ud654" in lowered
        or "\uc5b8\uc5b4" in lowered
    ):
        return ["proposal_localization_task", "email_localization_task"]

    if (
        "wrong company" in lowered
        or "different company" in lowered
        or "same name" in lowered
        or "address" in lowered
        or "email domain" in lowered
        or "contact mismatch" in lowered
        or "identity" in lowered
        or "location mismatch" in lowered
        or "다른 회사" in lowered
        or "동명이" in lowered
        or "주소" in lowered
        or "이메일 도메인" in lowered
        or "회사 식별" in lowered
        or "지역 오류" in lowered
    ):
        return ["identity_disambiguation_task", "lead_verification_task"]

    if "email" in lowered or "\uba54\uc77c" in lowered:
        return ["email_outreach_task", "email_localization_task"]

    if (
        "competitor" in lowered
        or "market" in lowered
        or "country" in lowered
        or "\uacbd\uc7c1" in lowered
        or "\uc2dc\uc7a5" in lowered
        or "\uad6d\uac00" in lowered
    ):
        return [
            "competitor_analysis_task",
            "marketing_recommendation_task",
            "proposal_task",
            "proposal_localization_task",
            "email_outreach_task",
            "email_localization_task",
        ]

    if (
        "pricing" in lowered
        or "package" in lowered
        or "\uac00\uaca9" in lowered
        or "\ud328\ud0a4\uc9c0" in lowered
    ):
        return ["marketing_recommendation_task", "proposal_task", "proposal_localization_task"]

    if (
        "tone" in lowered
        or "message" in lowered
        or "\ubb38\uccb4" in lowered
        or "\ud1a4" in lowered
    ):
        return ["proposal_localization_task", "email_localization_task"]

    if asset_type == "proposal_package":
        return [
            "competitor_analysis_task",
            "marketing_recommendation_task",
            "proposal_task",
            "proposal_localization_task",
            "email_outreach_task",
            "email_localization_task",
        ]

    return ["proposal_task", "proposal_localization_task"]
