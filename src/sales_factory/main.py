#!/usr/bin/env python
import json
import os
import subprocess
import sys
import warnings
from datetime import datetime
from pathlib import Path

# .env 로드 (Notion 등 API 키 사용 — 프로젝트 루트에서 실행 시 cwd 기준)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    load_dotenv()
except ImportError:
    pass

from sales_factory.brand_proof import load_onecation_proof_points
from sales_factory.crew import SalesFactory
from sales_factory.output_validation import resolve_sender_name

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run_notion_postprocess() -> None:
    """PDF 생성 → Notion 아웃리치 동기화 → PDF 업로드 순서로 후처리."""

    project_root = Path(__file__).resolve().parents[2]

    # 1단계: 제안서 PDF 생성
    pdf_script = project_root / "generate_pdf_playwright.py"
    if pdf_script.exists():
        command = [sys.executable, str(pdf_script)]
        require_pdf = os.environ.get("SALES_FACTORY_REQUIRE_PDF", "").strip().lower() in {"1", "true", "yes"}
        if require_pdf:
            command.append("--require-pdf")
        subprocess.run(
            command,
            cwd=str(project_root),
            check=False,
        )

    # 2단계: Notion 동기화 (아웃리치 + PDF 업로드 포함)
    sync_script = project_root / "sync_notion_pipeline.py"
    if not sync_script.exists():
        return

    subprocess.run([sys.executable, str(sync_script)], cwd=str(project_root), check=False)


def default_inputs() -> dict:
    """업종 순환 목록에서 다음 업종을 자동 선택해 실행 인풋을 반환."""

    project_root = Path(__file__).resolve().parents[2]
    state_file = project_root / "industry_targets.json"

    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            industries = state.get("industries", [])
            idx = int(state.get("current_index", 0))
            if industries:
                current = industries[idx % len(industries)]
                # 다음 실행을 위해 index 저장
                state["current_index"] = (idx + 1) % len(industries)
                state_file.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"[업종 순환] {idx + 1}/{len(industries)} - {current['name']} : {current['query']}")
                return {
                    "lead_mode": "region_or_industry",
                    "lead_query": current["query"],
                    "max_companies": "15",
                    "current_year": str(datetime.now().year),
                    "sender_name": resolve_sender_name(),
                    "onecation_proof_points": load_onecation_proof_points(project_root),
                }
        except Exception as e:
            print(f"[업종 순환] industry_targets.json 읽기 실패: {e}")

    # fallback
    return {
        "lead_mode": "region_or_industry",
        "lead_query": "서울 소규모 자영업 홈페이지 없는 업체",
        "max_companies": "15",
        "current_year": str(datetime.now().year),
        "sender_name": resolve_sender_name(),
        "onecation_proof_points": load_onecation_proof_points(project_root),
    }


def run():
    """Run the crew."""

    inputs = default_inputs()

    try:
        SalesFactory().crew().kickoff(inputs=inputs)
        run_notion_postprocess()
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def train():
    """Train the crew for a given number of iterations."""

    inputs = default_inputs()

    try:
        SalesFactory().crew().train(
            n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """Replay the crew execution from a specific task."""

    try:
        SalesFactory().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """Test the crew execution and return the results."""

    inputs = default_inputs()

    try:
        SalesFactory().crew().test(
            n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


def run_with_trigger():
    """Run the crew with trigger payload."""

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "lead_mode": trigger_payload.get("lead_mode", "region_or_industry"),
        "lead_query": trigger_payload.get("lead_query", ""),
        "max_companies": str(trigger_payload.get("max_companies", "10")),
        "current_year": str(datetime.now().year),
        "sender_name": trigger_payload.get("sender_name") or resolve_sender_name(),
        "onecation_proof_points": trigger_payload.get("onecation_proof_points") or load_onecation_proof_points(),
    }

    try:
        result = SalesFactory().crew().kickoff(inputs=inputs)
        run_notion_postprocess()
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
