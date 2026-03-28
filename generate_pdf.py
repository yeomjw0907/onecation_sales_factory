#!/usr/bin/env python3
"""
generate_pdf.py — Sales Factory: 마케팅 제안서 PDF 자동 생성
(인포그래픽 · 성장 차트 · 홈페이지 링크 포함)
"""

import argparse
import io
import math
import re
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
# ── 그래픽/차트
from reportlab.graphics.shapes import (
    Drawing, Rect, Circle, Line, String, Wedge, Polygon,
)
from reportlab.graphics.charts.piecharts import Pie

# ═══════════════════════════════════════════════════════════════════════════════
# 브랜드 & 상수
# ═══════════════════════════════════════════════════════════════════════════════

BRAND = {
    "name":    "Onecation",
    "tagline": "데이터 기반 마케팅 파트너",
    "phone":   "010-6333-4649",
    "email":   "yeomjw0907@onecation.co.kr",
    "website": "onecation.co.kr",
    "url":     "https://onecation.co.kr",
}

TODAY      = date.today().strftime("%Y년 %m월 %d일")
TODAY_FILE = date.today().strftime("%Y-%m-%d")

PAGE_W, PAGE_H = (960.0, 540.0)   # 16:9 widescreen (pts)
MARGIN    = 2.2 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
FOOTER_H  = 1.4 * cm

BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
FONT_REG   = Path("C:/Windows/Fonts/malgun.ttf")
FONT_BOLD  = Path("C:/Windows/Fonts/malgunbd.ttf")

C = {
    "navy":    colors.HexColor("#0D1B2A"),
    "navy2":   colors.HexColor("#1B3358"),
    "teal":    colors.HexColor("#0B7285"),
    "teal_lt": colors.HexColor("#EAF6F8"),
    "gold":    colors.HexColor("#C8920A"),
    "gold_lt": colors.HexColor("#FEF8E7"),
    "green":   colors.HexColor("#2A7D5E"),
    "red":     colors.HexColor("#B83232"),
    "amber":   colors.HexColor("#D97706"),
    "bg":      colors.HexColor("#F4F7FB"),
    "bg2":     colors.HexColor("#FAFBFD"),
    "border":  colors.HexColor("#D5DEE8"),
    "border2": colors.HexColor("#E8EEF5"),
    "text":    colors.HexColor("#1A202C"),
    "text2":   colors.HexColor("#374151"),
    "muted":   colors.HexColor("#6B7A8D"),
    "white":   colors.white,
    "row_alt": colors.HexColor("#F8FAFC"),
}

# ─── 섹션 매핑 ────────────────────────────────────────────────────────────────
SECTION_MAP = {
    "executive":   ["executive summary", "실행 요약", "요약"],
    "market":      ["시장 현황", "market overview", "시장 규모"],
    "competitor":  ["경쟝사 분석", "경쟁사 분석", "competitor"],
    "positioning": ["포지셔닝 기회", "positioning"],
    "current":     ["현황 진단", "현황", "current state", "진단"],
    "opportunity": ["기회", "opportunity"],
    "solution":    ["제안 솔루션", "solution", "솔루션"],
    "channel":     ["채널 전략", "channel strategy", "채널"],
    "roadmap":     ["30/60/90", "로드맵", "roadmap"],
    "kpi":         ["kpi 예측 및 roi", "kpi", "roi", "예측", "forecast"],
    "offer":       ["투자 및 가격", "투자", "offer", "가격", "pricing"],
    "case":        ["적용 사례", "case study", "사례"],
    "landing":     ["랜딩", "landing", "suggested landing"],
    "next":        ["다음 단계", "next step", "다음"],
}
SECTION_LABEL = {
    "executive": "실행 요약",   "market": "시장 현황",
    "competitor": "경쟁사 분석", "current": "현황 진단",
    "opportunity": "기회",       "solution": "제안 솔루션",
    "channel": "채널 전략",      "roadmap": "30 / 60 / 90일 로드맵",
    "kpi": "KPI 예측 및 ROI",    "offer": "투자 및 가격",
    "case": "적용 사례",         "next": "다음 단계",
}
SECTION_ICONS = {
    "executive": "01", "market": "02", "competitor": "03",
    "current": "04",   "opportunity": "05", "solution": "06",
    "channel": "07",   "roadmap": "08",     "kpi": "09",
    "offer": "10",     "case": "11",        "next": "12",
}
DETAIL_ORDER = [
    "market", "competitor", "current", "opportunity",
    "solution", "channel", "roadmap", "kpi", "offer", "case", "next",
]

CHART_COLORS = [C["navy"], C["teal"], C["gold"], C["green"],
                C["navy2"], colors.HexColor("#7C4DFF")]


# ═══════════════════════════════════════════════════════════════════════════════
# 폰트 & 스타일
# ═══════════════════════════════════════════════════════════════════════════════

def register_fonts() -> tuple[str, str]:
    if FONT_REG.exists():
        pdfmetrics.registerFont(TTFont("KR",   str(FONT_REG)))
        bp = FONT_BOLD if FONT_BOLD.exists() else FONT_REG
        pdfmetrics.registerFont(TTFont("KR-B", str(bp)))
        return "KR", "KR-B"
    return "Helvetica", "Helvetica-Bold"


def make_styles(font: str, bold: str) -> dict:
    def p(name, fn=None, **kw) -> ParagraphStyle:
        return ParagraphStyle(name=name, fontName=fn or font, **kw)
    return {
        "body":    p("body",   fontSize=11, textColor=C["text"],  leading=19, spaceAfter=3),
        "body_b":  p("body_b", fn=bold, fontSize=11, textColor=C["text"],  leading=19),
        "bullet":  p("bullet", fontSize=11, textColor=C["text2"], leading=19,
                     leftIndent=12, spaceAfter=3),
        "muted":   p("muted",  fontSize=9,  textColor=C["muted"], leading=14),
        "th":      p("th",     fn=bold, fontSize=10, textColor=C["white"], leading=15),
        "td":      p("td",     fontSize=10, textColor=C["text2"], leading=15),
        "td_b":    p("td_b",   fn=bold, fontSize=10, textColor=C["text"],  leading=15),
        "label":   p("label",  fn=bold, fontSize=9,  textColor=C["muted"], leading=13),
        "value":   p("value",  fontSize=11, textColor=C["text"],  leading=17),
        "cta_val": p("cta_val",fn=bold, fontSize=11, textColor=C["teal"], leading=17),
        "sec_num": p("sec_num",fn=bold, fontSize=9,  textColor=C["gold"], leading=13),
        "sec_h":   p("sec_h",  fn=bold, fontSize=17, textColor=C["navy"], leading=24,
                     spaceAfter=2),
        "sec_sub": p("sec_sub",fn=bold, fontSize=12, textColor=C["teal"], leading=18,
                     spaceBefore=10, spaceAfter=4),
        "case_tag": p("case_tag", fn=bold, fontSize=9, textColor=C["gold"], leading=13),
        "case_body":p("case_body",fontSize=10, textColor=C["text2"], leading=16),
        "step_txt": p("step_txt", fontSize=11, textColor=C["text"],  leading=18),
        "link":     p("link",  fn=bold, fontSize=10, textColor=C["teal"], leading=15),
        "foot_b":   p("foot_b",fn=bold, fontSize=8,  textColor=C["navy2"],leading=11),
        "foot":     p("foot",  fontSize=8,  textColor=C["muted"], leading=11),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 파싱 유틸
# ═══════════════════════════════════════════════════════════════════════════════

def _safe(t: str) -> str:
    t = str(t)
    t = t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def parse_companies(text: str) -> dict[str, str]:
    lines, result, cur = text.splitlines(keepends=True), {}, None
    for line in lines:
        m = re.match(r"^#\s+(.+)", line)
        if m:
            cur = m.group(1).strip(); result[cur] = []
        elif cur:
            result[cur].append(line)
    if not result:
        result["default"] = lines  # type: ignore
    return {k: "".join(v) for k, v in result.items()}


def parse_sections(md: str) -> dict[str, str]:
    lines, sections, cur = md.splitlines(keepends=True), {}, None
    for line in lines:
        m = re.match(r"^##\s+(.+)", line)
        if m:
            cur = m.group(1).strip(); sections[cur] = []
        elif cur:
            sections[cur].append(line)
    result: dict[str, str] = {}
    for heading, body in sections.items():
        key = _norm(heading)
        s = "".join(body).strip()
        result[key] = (result.get(key, "") + "\n" + s).strip() if key in result else s
    return result


def _norm(h: str) -> str:
    h = h.lower()
    for key, kws in SECTION_MAP.items():
        if any(k in h for k in kws):
            return key
    return f"other:{h}"


def parse_exec_bullets(text: str) -> tuple[list[dict], str]:
    FIELDS = ["company_name","current_state","proposal",
              "channels","budget_4w","monthly_cost","cta"]
    data, proof = [], []
    for line in text.splitlines():
        s = line.lstrip("-•* ").strip()
        if "|" in s:
            parts = [p.strip() for p in s.split("|")]
            data.append({FIELDS[i]: parts[i] for i in range(min(len(FIELDS), len(parts)))})
        elif s:
            proof.append(s)
    return data, " ".join(proof[:3])


def parse_md_table(text: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in text.splitlines() if re.match(r"^\s*\|", l)]
    if len(lines) < 2:
        return [], []
    def row(l): return [c.strip() for c in l.strip().strip("|").split("|")]
    headers = row(lines[0])
    rows = [row(l) for l in lines[2:] if not re.match(r"^\s*\|[-| :]+\|\s*$", l)]
    return headers, rows


def find_company_landing(landing_text: str, company_name: str) -> str:
    companies = parse_companies(landing_text)
    if company_name in companies:
        return companies[company_name]
    for name, content in companies.items():
        if company_name in name or name in company_name:
            return content
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# 숫자 추출 (차트 데이터용)
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_num(text: str) -> float | None:
    """'80만원', '1,200명', '2.7%', '+320만원' → float (만원 단위 그대로)."""
    t = re.sub(r"[,\s+]", "", str(text))
    m = re.search(r"([\d.]+)\s*만", t)
    if m: return float(m.group(1))
    m = re.search(r"([\d.]+)", t)
    if m: return float(m.group(1))
    return None


def _fmt_num(val: float, original: str) -> str:
    """차트 레이블 포맷."""
    original = original.strip()
    if "만원" in original:
        return f"{val:.0f}만"
    if "%" in original:
        return f"{val:.1f}%"
    if "건" in original or "명" in original:
        return f"{int(val)}"
    return f"{val:.0f}"


# ═══════════════════════════════════════════════════════════════════════════════
# 인포그래픽 / 차트 함수
# ═══════════════════════════════════════════════════════════════════════════════

def _draw_kpi_bars(headers: list[str], rows: list[list[str]],
                   width: float, font: str, bold: str) -> Drawing | None:
    """
    KPI 성장 추이 바 차트.
    기간 컬럼(현재/4주/3개월) × 최대 3개 지표를 grouped bar로 표현.
    """
    # 기간 컬럼 인덱스 탐지 (0번 = 지표명, 나머지 = 기간)
    if len(headers) < 3 or not rows:
        return None

    period_cols = list(range(1, min(len(headers), 4)))  # 최대 3기간
    period_labels = [headers[i] for i in period_cols]

    # 최대 3개 지표, 숫자 있는 행만
    metrics = []
    for row in rows[:4]:
        vals = []
        for ci in period_cols:
            v = _extract_num(row[ci]) if ci < len(row) else None
            vals.append((v or 0, row[ci] if ci < len(row) else ""))
        if any(v > 0 for v, _ in vals):
            metrics.append((row[0], vals))
    if not metrics:
        return None

    # ── 레이아웃 ──────────────────────────────────────────────────────────────
    H         = 200.0
    BOTTOM    = 42.0
    TOP_PAD   = 20.0
    LEFT      = 14.0
    chart_h   = H - BOTTOM - TOP_PAD
    chart_w   = width - LEFT - 10

    n_periods = len(period_cols)
    n_metrics = len(metrics)
    group_w   = chart_w / n_periods
    bar_pad   = group_w * 0.12
    bar_w     = (group_w - bar_pad * 2) / n_metrics - 2

    all_vals = [v for _, vals in metrics for v, _ in vals if v > 0]
    max_val  = max(all_vals) if all_vals else 1

    d = Drawing(width, H)

    # 배경 그리드 라인 (수평 4개)
    for gi in range(1, 5):
        gy = BOTTOM + chart_h * gi / 4
        d.add(Line(LEFT, gy, LEFT + chart_w, gy,
                   strokeColor=colors.HexColor("#E8EEF5"), strokeWidth=0.5))

    # 바 그리기
    COLORS = [C["navy"], C["teal"], C["gold"], C["green"]]
    for pi in range(n_periods):
        gx = LEFT + pi * group_w + bar_pad
        for mi, (metric_name, vals) in enumerate(metrics):
            val, orig = vals[pi]
            bx  = gx + mi * (bar_w + 2)
            raw_h = (val / max_val) * chart_h if val > 0 else 3
            bh  = max(raw_h, 3)
            col = COLORS[mi % len(COLORS)]

            # 바
            d.add(Rect(bx, BOTTOM, bar_w, bh, fillColor=col, strokeColor=None))

            # 값 레이블 (바 위)
            if val > 0:
                lbl = _fmt_num(val, orig)
                d.add(String(bx + bar_w / 2, BOTTOM + bh + 3, lbl,
                             fontName=bold, fontSize=7.5,
                             fillColor=col.clone() if hasattr(col, 'clone') else col,
                             textAnchor="middle"))

    # X축 기간 레이블
    for pi, plabel in enumerate(period_labels):
        px = LEFT + pi * group_w + group_w / 2
        short = plabel.replace("후", "").replace(" ", "")[:5]
        d.add(String(px, BOTTOM - 14, short,
                     fontName=font, fontSize=8.5,
                     fillColor=C["muted"].hexval() if hasattr(C["muted"], 'hexval') else "#6B7A8D",
                     textAnchor="middle"))

    # X축 라인
    d.add(Line(LEFT, BOTTOM, LEFT + chart_w, BOTTOM,
               strokeColor=C["border"], strokeWidth=1))

    # 범례 (우하단)
    leg_x = LEFT
    leg_y = 6.0
    for mi, (metric_name, _) in enumerate(metrics):
        col = COLORS[mi % len(COLORS)]
        rx  = leg_x + mi * (chart_w / n_metrics)
        d.add(Rect(rx, leg_y, 9, 9, fillColor=col, strokeColor=None))
        short_name = metric_name[:8]
        d.add(String(rx + 12, leg_y + 1, short_name,
                     fontName=font, fontSize=7.5,
                     fillColor="#374151", textAnchor="start"))

    return d


def _draw_roadmap_timeline(rows: list[list[str]],
                           width: float, font: str, bold: str) -> Drawing | None:
    """로드맵 3단계 타임라인 인포그래픽."""
    if not rows:
        return None
    nodes = rows[:3]
    n = len(nodes)

    H       = 145.0
    LINE_Y  = 82.0
    R       = 24.0
    PAD_X   = 40.0
    NODE_COLORS = [C["teal"], C["navy2"], C["gold"]]

    d = Drawing(width, H)

    positions = [PAD_X + (width - 2 * PAD_X) / (n - 1) * i for i in range(n)] \
                if n > 1 else [width / 2]

    # 연결선
    for i in range(n - 1):
        x1 = positions[i] + R
        x2 = positions[i + 1] - R
        d.add(Line(x1, LINE_Y, x2, LINE_Y,
                   strokeColor=C["border"], strokeWidth=2.5,
                   strokeDashArray=[4, 3]))

    for i, (x, row) in enumerate(zip(positions, nodes)):
        col    = NODE_COLORS[i % len(NODE_COLORS)]
        period = (row[0] if row else f"{(i+1)*30}일")[:8]
        act    = (row[1] if len(row) > 1 else "")[:22]
        kpi    = (row[2] if len(row) > 2 else "")[:22]

        # 원 (그림자 효과)
        d.add(Circle(x, LINE_Y, R + 2,
                     fillColor=colors.HexColor("#E0E8F0"), strokeColor=None))
        d.add(Circle(x, LINE_Y, R, fillColor=col, strokeColor=None))

        # 번호
        d.add(String(x, LINE_Y - 6, str(i + 1),
                     fontName=bold, fontSize=16,
                     fillColor=colors.white, textAnchor="middle"))

        # 기간 (위)
        d.add(String(x, LINE_Y + R + 10, period,
                     fontName=bold, fontSize=9,
                     fillColor=col.hexval() if hasattr(col,'hexval') else "#0B7285",
                     textAnchor="middle"))

        # 주요 활동 (아래)
        d.add(String(x, LINE_Y - R - 18, act,
                     fontName=font, fontSize=8,
                     fillColor="#374151", textAnchor="middle"))
        if kpi:
            d.add(String(x, LINE_Y - R - 30, kpi,
                         fontName=font, fontSize=7.5,
                         fillColor="#6B7A8D", textAnchor="middle"))

    return d


def _draw_budget_donut(rows: list[list[str]],
                       width: float, font: str, bold: str) -> Drawing | None:
    """예산 배분 도넛 차트 + 범례."""
    # 합계 행 제외, 금액 있는 행만
    items = []
    for row in rows:
        if not row or len(row) < 2:
            continue
        label = row[0].strip()
        if any(kw in label for kw in ["합계", "총", "total", "sum", "계"]):
            continue
        if label.startswith("**") or not label:
            continue
        val = _extract_num(row[1]) if len(row) > 1 else None
        if val and val > 0:
            items.append((label[:14], val, row[1].strip()))
    if len(items) < 2:
        return None

    H       = 170.0
    PIE_D   = 120.0
    PIE_X   = width - PIE_D / 2 - 30
    PIE_Y   = H / 2

    d   = Drawing(width, H)
    pie = Pie()
    pie.x      = PIE_X - PIE_D / 2
    pie.y      = PIE_Y - PIE_D / 2
    pie.width  = PIE_D
    pie.height = PIE_D
    pie.data   = [it[1] for it in items]
    pie.innerRadiusFraction = 0.52
    pie.startAngle   = 90
    pie.direction    = "clockwise"
    pie.sideLabels   = 0
    pie.simpleLabels = 0

    SLICE_COLORS = [C["navy"], C["teal"], C["gold"], C["green"],
                    C["navy2"], colors.HexColor("#7C4DFF")]
    for i in range(len(items)):
        pie.slices[i].fillColor   = SLICE_COLORS[i % len(SLICE_COLORS)]
        pie.slices[i].strokeColor = C["white"]
        pie.slices[i].strokeWidth = 1.5
    d.add(pie)

    # 총합 텍스트 (도넛 중앙)
    total = sum(it[1] for it in items)
    total_str = f"{total:.0f}만원"
    d.add(String(PIE_X, PIE_Y + 5, total_str,
                 fontName=bold, fontSize=10,
                 fillColor=C["navy"].hexval() if hasattr(C["navy"],'hexval') else "#0D1B2A",
                 textAnchor="middle"))
    d.add(String(PIE_X, PIE_Y - 10, "총 예산",
                 fontName=font, fontSize=8,
                 fillColor="#6B7A8D", textAnchor="middle"))

    # 범례 (좌측)
    leg_x  = 10.0
    leg_y0 = H - 20.0
    row_h  = (H - 30) / max(len(items), 1)
    for i, (label, val, orig) in enumerate(items):
        col = SLICE_COLORS[i % len(SLICE_COLORS)]
        ly  = leg_y0 - i * row_h
        pct = val / total * 100 if total else 0

        # 색 사각형
        d.add(Rect(leg_x, ly - 5, 10, 10, fillColor=col, strokeColor=None))
        # 레이블
        d.add(String(leg_x + 14, ly - 4, label,
                     fontName=font, fontSize=8.5,
                     fillColor="#1A202C", textAnchor="start"))
        # 금액 + 비율
        d.add(String(leg_x + 14, ly - 15, f"{orig}  ({pct:.0f}%)",
                     fontName=font, fontSize=7.5,
                     fillColor="#6B7A8D", textAnchor="start"))

    return d


def _draw_competitor_bars(headers: list[str], rows: list[list[str]],
                          width: float, font: str, bold: str) -> Drawing | None:
    """경쟝사 온라인 현황 수평 바 인포그래픽."""
    if not rows:
        return None

    # 웹사이트 컬럼, 네이버 컬럼 인덱스 탐지
    hdr_low = [h.lower() for h in headers]
    web_col  = next((i for i, h in enumerate(hdr_low)
                     if any(k in h for k in ["웹", "web", "사이트"])), 1)
    rank_col = next((i for i, h in enumerate(hdr_low)
                     if any(k in h for k in ["네이버", "순위", "rank"])), 2)

    def _score(row):
        web = row[web_col].lower() if web_col < len(row) else ""
        rank = row[rank_col].lower() if rank_col < len(row) else ""
        s = 0
        if "없음" in web or "no" in web:       s += 10
        elif "구형" in web or "old" in web:    s += 40
        elif "있음" in web or "활성" in web:   s += 75
        if "상위 3" in rank or "1위" in rank or "2위" in rank or "3위" in rank: s += 20
        elif "상위 5" in rank or "상위 7" in rank: s += 12
        elif "상위 10" in rank: s += 7
        return min(s, 95)

    def _color(score):
        if score < 30:   return C["green"]   # 취약 → 우리 기회
        if score < 60:   return C["amber"]
        return C["red"]                       # 강한 경쟁자

    items = [(row[0][:12] if row else "?", _score(row)) for row in rows[:6]]

    BAR_H = 18
    ROW_H = 30
    LEFT  = 90.0
    MAX_W = width - LEFT - 20
    H     = len(items) * ROW_H + 40

    d = Drawing(width, H)
    # 헤더
    d.add(String(LEFT / 2, H - 18, "경쟁사",
                 fontName=bold, fontSize=8.5, fillColor="#0D1B2A", textAnchor="middle"))
    d.add(String(LEFT + MAX_W / 2, H - 18, "온라인 노출 강도",
                 fontName=bold, fontSize=8.5, fillColor="#0D1B2A", textAnchor="middle"))

    for i, (name, score) in enumerate(items):
        y = H - 40 - i * ROW_H
        # 배경 트랙
        d.add(Rect(LEFT, y, MAX_W, BAR_H,
                   fillColor=colors.HexColor("#EEF1F6"), strokeColor=None))
        # 채워진 바
        bw = MAX_W * score / 100
        d.add(Rect(LEFT, y, bw, BAR_H,
                   fillColor=_color(score), strokeColor=None))
        # 퍼센트 텍스트
        d.add(String(LEFT + bw + 4, y + BAR_H / 2 - 4, f"{score}",
                     fontName=bold, fontSize=8,
                     fillColor=_color(score).hexval() if hasattr(_color(score),'hexval') else "#000",
                     textAnchor="start"))
        # 회사명
        d.add(String(LEFT - 5, y + BAR_H / 2 - 4, name,
                     fontName=font, fontSize=8.5,
                     fillColor="#1A202C", textAnchor="end"))

    # 범례
    for lbl, col, lx in [("취약(기회)", C["green"], 10),
                          ("중간",      C["amber"],  80),
                          ("강함",      C["red"],   140)]:
        d.add(Rect(lx, 5, 8, 8, fillColor=col, strokeColor=None))
        d.add(String(lx + 11, 6, lbl, fontName=font, fontSize=7.5,
                     fillColor="#6B7A8D", textAnchor="start"))

    return d


def _drawing_to_flowable(drawing: Drawing) -> Table:
    """Drawing → Platypus Table (여백 포함)."""
    return Table([[drawing]], colWidths=[CONTENT_W],
                 style=TableStyle([
                     ("TOPPADDING",    (0,0),(-1,-1), 6),
                     ("BOTTOMPADDING", (0,0),(-1,-1), 4),
                     ("LEFTPADDING",   (0,0),(-1,-1), 0),
                 ]))


# ═══════════════════════════════════════════════════════════════════════════════
# 페이지 콜백
# ═══════════════════════════════════════════════════════════════════════════════

def make_cover_cb(font: str, bold: str, company_name: str, exec_data: list[dict]):
    def _cb(canvas, doc):
        canvas.saveState()

        # 네이비 상단 블록
        top_h = PAGE_H * 0.57
        canvas.setFillColor(C["navy"])
        canvas.rect(0, PAGE_H - top_h, PAGE_W, top_h, fill=1, stroke=0)

        # 좌측 골드 세로 바
        canvas.setFillColor(C["gold"])
        canvas.rect(0, PAGE_H - top_h, 5, top_h, fill=1, stroke=0)

        # 회사명
        canvas.setFont(bold, 38)
        canvas.setFillColor(C["white"])
        canvas.drawString(MARGIN + 6, PAGE_H - 3.2 * cm, company_name)

        # 제목
        canvas.setFont(bold, 15)
        canvas.setFillColor(C["gold"])
        canvas.drawString(MARGIN + 6, PAGE_H - 5.0 * cm, "마케팅 성장 제안서")

        # 날짜 + 브랜드
        canvas.setFont(font, 10)
        canvas.setFillColor(colors.HexColor("#7AA0C0"))
        canvas.drawString(MARGIN + 6, PAGE_H - 6.2 * cm, TODAY)
        canvas.setFont(bold, 10)
        canvas.setFillColor(colors.HexColor("#3A6A90"))
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 6.2 * cm, BRAND["name"])

        # 스탯 박스
        stats = []
        if exec_data:
            e = exec_data[0]
            if e.get("budget_4w"):   stats.append(("4주 테스트 예산", e["budget_4w"]))
            if e.get("channels"):    stats.append(("추천 채널", e["channels"]))
            if e.get("monthly_cost"):stats.append(("월 유지비", e["monthly_cost"]))

        if stats:
            n  = len(stats)
            pad = 0.35 * cm
            bw = (CONTENT_W - pad * (n - 1)) / n
            bh = 3.0 * cm
            yt = PAGE_H - top_h - 1.4 * cm
            for i, (lbl, val) in enumerate(stats):
                x = MARGIN + i * (bw + pad)
                canvas.setFillColor(C["white"])
                canvas.setStrokeColor(C["border"])
                canvas.setLineWidth(0.7)
                canvas.roundRect(x, yt - bh, bw, bh, radius=5, fill=1, stroke=1)
                canvas.setFillColor(C["gold"])
                canvas.rect(x + 5, yt - 2.5, bw - 10, 3, fill=1, stroke=0)
                canvas.setFont(bold, 13)
                canvas.setFillColor(C["navy"])
                canvas.drawCentredString(x + bw / 2, yt - bh * 0.47, val[:22])
                canvas.setFont(font, 8.5)
                canvas.setFillColor(C["muted"])
                canvas.drawCentredString(x + bw / 2, yt - bh + 0.55 * cm, lbl)

        # ── 하단 푸터 ────────────────────────────────────────────────────────
        canvas.setFillColor(C["navy"])
        canvas.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)
        canvas.setFillColor(C["gold"])
        canvas.rect(0, FOOTER_H - 2, PAGE_W, 2, fill=1, stroke=0)

        canvas.setFont(bold, 8.5)
        canvas.setFillColor(C["white"])
        canvas.drawString(MARGIN, FOOTER_H * 0.38,
                          f"{BRAND['name']}  |  {BRAND['phone']}  |  {BRAND['email']}")

        # 홈페이지 링크 (클릭 가능)
        canvas.setFont(bold, 8.5)
        canvas.setFillColor(colors.HexColor("#5BB8CC"))
        wx = PAGE_W - MARGIN
        wy = FOOTER_H * 0.38
        canvas.drawRightString(wx, wy, BRAND["website"])
        # 링크 영역 등록
        text_w = pdfmetrics.stringWidth(BRAND["website"], bold, 8.5)
        canvas.linkURL(BRAND["url"],
                       (wx - text_w, wy - 2, wx, wy + 9),
                       relative=0)

        canvas.restoreState()
    return _cb


def make_page_cb(font: str, bold: str, company_name: str):
    def _cb(canvas, doc):
        canvas.saveState()
        y = FOOTER_H + 3 * mm
        canvas.setStrokeColor(C["border"])
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, y, PAGE_W - MARGIN, y)

        canvas.setFont(bold, 8)
        canvas.setFillColor(C["navy2"])
        canvas.drawString(MARGIN, FOOTER_H * 0.3, BRAND["name"])

        canvas.setFont(font, 8)
        canvas.setFillColor(C["muted"])
        canvas.drawCentredString(PAGE_W / 2, FOOTER_H * 0.3,
                                 f"{company_name}  마케팅 성장 제안서  ·  {TODAY}")

        right_text = f"{BRAND['phone']}  ·  {BRAND['website']}  |  {doc.page}"
        canvas.drawRightString(PAGE_W - MARGIN, FOOTER_H * 0.3, right_text)

        canvas.restoreState()
    return _cb


# ═══════════════════════════════════════════════════════════════════════════════
# 공통 컴포넌트
# ═══════════════════════════════════════════════════════════════════════════════

def _section_header(label: str, key: str, styles: dict) -> list:
    num = SECTION_ICONS.get(key, "—")
    return [
        Spacer(1, 6 * mm),
        Paragraph(num, styles["sec_num"]),
        Paragraph(label, styles["sec_h"]),
        HRFlowable(width=CONTENT_W, thickness=1.5, color=C["gold"], spaceAfter=6),
    ]


def _clean_table(data, col_widths, header_color=None, vpad=10, hpad=12) -> Table:
    hc = header_color or C["navy"]
    t  = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0),  hc),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), vpad),
        ("BOTTOMPADDING", (0,0), (-1,-1), vpad),
        ("LEFTPADDING",   (0,0), (-1,-1), hpad),
        ("RIGHTPADDING",  (0,0), (-1,-1), hpad),
        ("LINEBELOW",     (0,0), (-1,-1), 0.5, C["border"]),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [C["white"], C["row_alt"]]),
    ]))
    return t


def _proof_box(text: str, styles: dict) -> Table:
    t = Table([
        [Paragraph("📌  적용 사례 / 근거", styles["case_tag"])],
        [Paragraph(_safe(text), styles["case_body"])],
    ], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C["gold_lt"]),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(-1,-1), 16),
        ("RIGHTPADDING",  (0,0),(-1,-1), 16),
        ("LINERIGHT",     (0,0),(0,-1),  4, C["gold"]),
        ("LINEBELOW",     (0,0),(-1,0),  0.5, colors.HexColor("#F0DFA0")),
    ]))
    return t


def _auto_col_widths(n: int) -> list[float]:
    if n <= 1: return [CONTENT_W]
    first = CONTENT_W * 0.20
    return [first] + [(CONTENT_W - first) / (n - 1)] * (n - 1)


def _md_to_flowables(md: str, styles: dict) -> list:
    result = []
    for line in md.splitlines():
        if not line.strip():
            result.append(Spacer(1, 2 * mm)); continue
        if re.match(r"^\s*\|", line):
            clean = re.sub(r"\|", "  ", line).strip()
            if re.match(r"^[-| :]+$", clean.replace(" ","")): continue
            if clean: result.append(Paragraph(_safe(clean), styles["muted"]))
            continue
        if re.match(r"^###\s+", line):
            result.append(Spacer(1,2*mm))
            result.append(Paragraph(_safe(re.sub(r"^###\s+","",line)), styles["sec_sub"]))
            continue
        sl = _safe(line.lstrip())
        if re.match(r"^\s*[-•*]\s+", line):
            result.append(Paragraph(f"•  {_safe(re.sub(r'^\\s*[-•*]\\s+','',line))}",
                                    styles["bullet"]))
        else:
            result.append(Paragraph(sl, styles["body"]))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 섹션별 빌더
# ═══════════════════════════════════════════════════════════════════════════════

def build_exec_summary(exec_data: list[dict], proof: str, exec_text: str, styles: dict) -> list:
    FIELD_ROWS = [
        ("current_state","현황"), ("proposal","제안 내용"),
        ("channels","추천 채널"), ("budget_4w","4주 예산"),
        ("monthly_cost","월 유지비"), ("cta","다음 단계"),
    ]
    elems = _section_header("실행 요약", "executive", styles)
    rows  = []
    for entry in exec_data:
        for fk, fl in FIELD_ROWS:
            val = entry.get(fk, "")
            if not val: continue
            vs   = styles["cta_val"] if fk == "cta" else styles["value"]
            pref = "→  " if fk == "cta" else ""
            rows.append([Paragraph(fl, styles["label"]),
                         Paragraph(f"{pref}{_safe(val)}", vs)])
    if rows:
        t = Table(rows, colWidths=[CONTENT_W * 0.24, CONTENT_W * 0.76])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(0,-1),  C["bg"]),
            ("BACKGROUND",    (1,0),(1,-1),  C["white"]),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1), 11),
            ("BOTTOMPADDING", (0,0),(-1,-1), 11),
            ("LEFTPADDING",   (0,0),(-1,-1), 14),
            ("LINEBELOW",     (0,0),(-1,-2), 0.5, C["border2"]),
            ("BOX",           (0,0),(-1,-1), 0.7, C["border"]),
        ]))
        elems.append(t); elems.append(Spacer(1, 5*mm))
    else:
        # 파이프 구조 없으면 텍스트 직접 렌더링 (풍부한 카드 형태)
        bullets = [l.lstrip("-•* ").strip() for l in exec_text.splitlines()
                   if re.match(r"^\s*[-•*]\s+", l)]
        paras   = [l.strip() for l in exec_text.splitlines()
                   if l.strip() and not re.match(r"^\s*[-•*]", l)
                   and not re.match(r"^\s*\|", l)]
        # 핵심 요약 박스 (본문 단락)
        if paras:
            summary_box = Table(
                [[Paragraph(_safe(p), ParagraphStyle(
                    "exec_p", fontName=styles["body"].fontName,
                    fontSize=12, textColor=C["text"], leading=21, spaceAfter=5,
                ))] for p in paras],
                colWidths=[CONTENT_W],
            )
            summary_box.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,-1), C["bg"]),
                ("TOPPADDING",    (0,0),(-1,-1), 10),
                ("BOTTOMPADDING", (0,0),(-1,-1), 10),
                ("LEFTPADDING",   (0,0),(-1,-1), 18),
                ("RIGHTPADDING",  (0,0),(-1,-1), 18),
                ("LINERIGHT",     (0,0),(0,-1),  5, C["navy"]),
                ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
            ]))
            elems.append(summary_box); elems.append(Spacer(1, 4*mm))
        # 핵심 포인트 카드 그리드 (불릿)
        if bullets:
            ICONS = ["01", "02", "03", "04", "05", "06"]
            cols  = min(3, len(bullets))
            cw    = [CONTENT_W / cols] * cols
            cards = []
            for i, b in enumerate(bullets[:cols * 2]):  # 최대 2행
                lbl, _, val = (b.partition(":") if ":" in b else ("", "", b))
                card = Table(
                    [[Paragraph(ICONS[i % len(ICONS)], ParagraphStyle(
                        "ei", fontName=styles["sec_num"].fontName,
                        fontSize=10, textColor=C["gold"], leading=13))],
                     [Paragraph(_safe((val or b).strip()), ParagraphStyle(
                        "eb", fontName=styles["body_b"].fontName,
                        fontSize=11, textColor=C["navy"], leading=17))],
                     [Paragraph(_safe(lbl.strip() or "핵심 포인트"), ParagraphStyle(
                        "em", fontName=styles["muted"].fontName,
                        fontSize=9, textColor=C["muted"], leading=13))]],
                    colWidths=[CONTENT_W / cols - 24])
                card.setStyle(TableStyle([
                    ("TOPPADDING",    (0,0),(-1,-1), 4),
                    ("BOTTOMPADDING", (0,0),(-1,-1), 4),
                    ("LEFTPADDING",   (0,0),(-1,-1), 0),
                ]))
                cards.append(card)
            # 카드 배치
            for row_start in range(0, len(cards), cols):
                row_cards = cards[row_start:row_start + cols]
                while len(row_cards) < cols:
                    row_cards.append(Paragraph("", styles["muted"]))
                grid = Table([row_cards], colWidths=cw)
                grid.setStyle(TableStyle([
                    ("BACKGROUND",    (0,0),(-1,-1), C["teal_lt"]),
                    ("TOPPADDING",    (0,0),(-1,-1), 14),
                    ("BOTTOMPADDING", (0,0),(-1,-1), 14),
                    ("LEFTPADDING",   (0,0),(-1,-1), 18),
                    ("RIGHTPADDING",  (0,0),(-1,-1), 18),
                    ("LINEBEFORE",    (1,0),(-1,-1), 0.5, C["border"]),
                    ("BOX",           (0,0),(-1,-1), 0.7, C["border"]),
                ]))
                elems.append(grid); elems.append(Spacer(1, 3*mm))
    if proof.strip():
        elems.append(_proof_box(proof, styles))
    return elems


def build_market_section(text: str, styles: dict) -> list:
    elems = _section_header("시장 현황", "market", styles)
    bullets = [l.lstrip("-•* ").strip() for l in text.splitlines()
               if re.match(r"^\s*[-•*]\s+", l)]
    other   = "\n".join(l for l in text.splitlines()
                        if not re.match(r"^\s*[-•*]\s+",l)
                        and not re.match(r"^\s*\|",l)).strip()
    if bullets:
        per = min(3, len(bullets))
        cw  = [CONTENT_W / per] * per
        cells = []
        for b in bullets[:per]:
            lbl, _, val = b.partition(":") if ":" in b else ("", "", b)
            it = Table([[Paragraph(_safe((val or b).strip()[:50]), styles["body_b"])],
                        [Paragraph(_safe(lbl.strip()[:40]), styles["muted"])]],
                       colWidths=[CONTENT_W/per - 20])
            it.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),4),
                                    ("BOTTOMPADDING",(0,0),(-1,-1),4),
                                    ("LEFTPADDING",(0,0),(-1,-1),0)]))
            cells.append(it)
        outer = Table([cells], colWidths=cw)
        outer.setStyle(TableStyle([
            ("BACKGROUND",   (0,0),(-1,-1), C["teal_lt"]),
            ("TOPPADDING",   (0,0),(-1,-1), 14),
            ("BOTTOMPADDING",(0,0),(-1,-1), 14),
            ("LEFTPADDING",  (0,0),(-1,-1), 16),
            ("RIGHTPADDING", (0,0),(-1,-1), 16),
            ("LINEBEFORE",   (1,0),(-1,-1), 0.5, C["border"]),
            ("BOX",          (0,0),(-1,-1), 0.7, C["border"]),
        ]))
        elems.append(outer); elems.append(Spacer(1,4*mm))
        for b in bullets[per:]:
            elems.append(Paragraph(f"•  {_safe(b)}", styles["bullet"]))
    if other:
        for f in _md_to_flowables(other, styles): elems.append(f)
    return elems


def build_competitor_section(text: str, styles: dict,
                              font="KR", bold="KR-B") -> list:
    elems = _section_header("경쟝사 분석", "competitor", styles)
    headers, rows = parse_md_table(text)
    if headers and rows:
        cw = _auto_col_widths(len(headers))
        tbl_data = [[Paragraph(_safe(h), styles["th"]) for h in headers]]
        for row in rows:
            padded = (row + [""]*len(headers))[:len(headers)]
            tbl_data.append([Paragraph(_safe(c), styles["td"]) for c in padded])
        elems.append(_clean_table(tbl_data, cw, vpad=11, hpad=13))
        elems.append(Spacer(1, 4*mm))

        # ── 경쟝사 온라인 현황 바 차트 ────────────────────────────────────
        d = _draw_competitor_bars(headers, rows, CONTENT_W, font, bold)
        if d:
            elems.append(Paragraph("경쟝사 온라인 노출 강도 비교", styles["sec_sub"]))
            elems.append(_drawing_to_flowable(d))
            elems.append(Spacer(1, 2*mm))
            elems.append(Paragraph(
                "※ 수치가 낮은(초록색) 경쟝사 = 온라인 공백 → 우리의 선점 기회",
                styles["muted"]))

    non_table = "\n".join(l for l in text.splitlines()
                          if not re.match(r"^\s*\|",l)).strip()
    if non_table:
        elems.append(Spacer(1,2*mm))
        for f in _md_to_flowables(non_table, styles): elems.append(f)
    return elems


def build_roadmap_section(text: str, styles: dict,
                           font="KR", bold="KR-B") -> list:
    elems = _section_header("30 / 60 / 90일 로드맵", "roadmap", styles)
    headers, rows = parse_md_table(text)

    # ── 타임라인 인포그래픽 (표 위에 배치) ────────────────────────────────
    if rows:
        d = _draw_roadmap_timeline(rows, CONTENT_W, font, bold)
        if d:
            elems.append(_drawing_to_flowable(d))
            elems.append(Spacer(1, 5*mm))

    ROW_BG = [C["teal"], C["navy2"], C["gold"]]
    if headers and rows:
        n  = len(headers)
        cw = ([CONTENT_W * 0.18] + [(CONTENT_W * 0.82)/(n-1)] * (n-1)
              if n > 1 else [CONTENT_W])
        tbl_data = [[Paragraph(_safe(h), styles["th"]) for h in headers]]
        for row in rows:
            padded = (row + [""]*n)[:n]
            tbl_data.append([Paragraph(_safe(c), styles["td"]) for c in padded])
        t = Table(tbl_data, colWidths=cw, repeatRows=1)
        cmds = [
            ("BACKGROUND",    (0,0),(-1,0),  C["navy"]),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1), 12),
            ("BOTTOMPADDING", (0,0),(-1,-1), 12),
            ("LEFTPADDING",   (0,0),(-1,-1), 13),
            ("LINEBELOW",     (0,0),(-1,-1), 0.5, C["border"]),
        ]
        for i, bg in enumerate(ROW_BG):
            r = i + 1
            if r < len(tbl_data):
                cmds += [("BACKGROUND",(0,r),(0,r), bg),
                         ("TEXTCOLOR", (0,r),(0,r), C["white"]),
                         ("FONTNAME",  (0,r),(0,r), styles["th"].fontName),
                         ("BACKGROUND",(1,r),(-1,r),
                          C["row_alt"] if i%2 else C["white"])]
        t.setStyle(TableStyle(cmds))
        elems.append(t)
    else:
        for f in _md_to_flowables(text, styles): elems.append(f)
    return elems


def build_kpi_section(text: str, styles: dict,
                      font="KR", bold="KR-B") -> list:
    elems = _section_header("KPI 예측 및 ROI", "kpi", styles)
    headers, rows = parse_md_table(text)

    if headers and rows:
        n  = len(headers)
        cw = [CONTENT_W / n] * n
        tbl_data = [[Paragraph(_safe(h), styles["th"]) for h in headers]]
        for row in rows:
            padded = (row + [""]*n)[:n]
            tbl_data.append([Paragraph(_safe(c), styles["td"]) for c in padded])
        elems.append(_clean_table(tbl_data, cw, header_color=C["teal"],
                                  vpad=11, hpad=13))
        elems.append(Spacer(1, 5*mm))

        # ── KPI 성장 바 차트 ──────────────────────────────────────────────
        d = _draw_kpi_bars(headers, rows, CONTENT_W, font, bold)
        if d:
            elems.append(Paragraph("성장 추이 차트", styles["sec_sub"]))
            elems.append(_drawing_to_flowable(d))
            elems.append(Spacer(1, 2*mm))

    non_table = "\n".join(l for l in text.splitlines()
                          if not re.match(r"^\s*\|",l)).strip()
    if non_table:
        roi_box = Table(
            [[Paragraph(_safe(non_table[:250]), styles["body_b"])]],
            colWidths=[CONTENT_W])
        roi_box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C["teal_lt"]),
            ("TOPPADDING",    (0,0),(-1,-1), 12),
            ("BOTTOMPADDING", (0,0),(-1,-1), 12),
            ("LEFTPADDING",   (0,0),(-1,-1), 16),
            ("LINERIGHT",     (0,0),(0,-1),  4, C["teal"]),
        ]))
        elems.append(roi_box)
    return elems


def _is_plan_table(headers: list[str]) -> bool:
    """헤더에 '안' 키워드(A안/B안/스타터/성장/프리미엄 등)가 포함되면 플랜 비교표."""
    plan_kw = ["안", "스타터", "베이직", "성장", "프리미엄", "starter", "basic", "pro", "premium"]
    return sum(1 for h in headers[1:] if any(k in h.lower() for k in plan_kw)) >= 2


def _build_plan_cards(headers: list[str], rows: list[list[str]], styles: dict) -> list:
    """A/B/C 플랜을 가로 3분할 카드로 렌더링."""
    # 첫 컬럼은 항목명, 나머지가 각 플랜
    plan_count = min(len(headers) - 1, 4)
    plan_names = headers[1: plan_count + 1]

    # 색상 & 뱃지 설정 (가운데 플랜 = 추천)
    PLAN_COLORS = [C["navy"], C["teal"], colors.HexColor("#B45309"), colors.HexColor("#374151")]
    PLAN_LIGHT  = [C["bg"],   C["teal_lt"], C["gold_lt"], colors.HexColor("#F3F4F6")]
    rec_idx     = 1 if plan_count >= 3 else 0   # 두 번째 플랜이 추천

    elems = []
    card_w = CONTENT_W / plan_count
    padding = 14

    # ── 헤더 카드 ────────────────────────────────────────────────────────────
    # 가격 행 찾기 (헤더에 '비용'/'가격'/'금액'/'원' 포함)
    price_row = next(
        (r for r in rows if any(kw in r[0] for kw in ["비용","가격","금액","투자"])),
        rows[-1] if rows else None,
    )

    header_cells = []
    for i, name in enumerate(plan_names):
        color = PLAN_COLORS[i % len(PLAN_COLORS)]
        badge = "★ 추천" if i == rec_idx else ""
        price = price_row[i + 1] if price_row and len(price_row) > i + 1 else ""
        inner_rows = []
        if badge:
            inner_rows.append([Paragraph(badge, ParagraphStyle(
                "badge", fontName=styles["sec_num"].fontName,
                fontSize=8, textColor=C["gold"], leading=12))])
        inner_rows.append([Paragraph(_safe(name), ParagraphStyle(
            "ph", fontName=styles["th"].fontName,
            fontSize=13, textColor=C["white"], leading=18))])
        if price:
            inner_rows.append([Paragraph(_safe(price), ParagraphStyle(
                "pp", fontName=styles["body_b"].fontName,
                fontSize=11, textColor=colors.HexColor("#FDE68A"), leading=16))])
        cell_t = Table(inner_rows, colWidths=[card_w - padding * 2])
        cell_t.setStyle(TableStyle([
            ("TOPPADDING",    (0,0),(-1,-1), 3),
            ("BOTTOMPADDING", (0,0),(-1,-1), 3),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ]))
        header_cells.append(cell_t)

    hdr_table = Table([header_cells], colWidths=[card_w] * plan_count)
    hdr_styles = [
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), padding),
        ("BOTTOMPADDING", (0,0),(-1,-1), padding),
        ("LEFTPADDING",   (0,0),(-1,-1), padding),
        ("RIGHTPADDING",  (0,0),(-1,-1), padding),
    ]
    for i in range(plan_count):
        hdr_styles.append(("BACKGROUND", (i,0),(i,0), PLAN_COLORS[i % len(PLAN_COLORS)]))
    if rec_idx < plan_count:
        pass  # 테두리 강조는 아래 바디에서
    hdr_table.setStyle(TableStyle(hdr_styles))
    elems.append(hdr_table)

    # ── 항목 행 ──────────────────────────────────────────────────────────────
    skip_labels = {(price_row[0] if price_row else "").strip()}
    detail_rows = [r for r in rows if r[0].strip() not in skip_labels]
    for r_idx, row in enumerate(detail_rows):
        row_cells = []
        label_txt = row[0] if row else ""
        for i in range(plan_count):
            val = row[i + 1] if len(row) > i + 1 else ""
            # 추천 플랜 컬럼은 굵게
            st = styles["td_b"] if i == rec_idx else styles["td"]
            row_cells.append(Paragraph(_safe(val), st))
        body_row = Table(
            [[Paragraph(_safe(label_txt), styles["label"])] + row_cells],
            colWidths=[CONTENT_W * 0.18] + [card_w * (1 - 0.18 / plan_count)] * plan_count,
        )
        bg = PLAN_LIGHT[rec_idx % len(PLAN_LIGHT)] if r_idx % 2 == 0 else C["white"]
        body_row.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(0,-1), C["bg"]),
            ("BACKGROUND",    (1,0),(-1,-1), bg),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(-1,-1), 12),
            ("LINEBELOW",     (0,0),(-1,-1), 0.4, C["border2"]),
            ("LINEBEFORE",    (1 + rec_idx, 0),(1 + rec_idx, -1), 2, PLAN_COLORS[rec_idx]),
        ]))
        elems.append(body_row)

    elems.append(Spacer(1, 4*mm))
    return elems


def build_offer_section(text: str, styles: dict,
                         font="KR", bold="KR-B") -> list:
    elems = _section_header("투자 및 가격", "offer", styles)
    headers, rows = parse_md_table(text)

    if headers and rows and _is_plan_table(headers):
        # A/B/C 플랜 비교 카드
        elems.extend(_build_plan_cards(headers, rows, styles))
    elif headers and rows:
        # 단일 가격표
        n  = len(headers)
        cw = [CONTENT_W / n] * n
        tbl_data = [[Paragraph(_safe(h), styles["th"]) for h in headers]]
        for row in rows:
            padded = (row + [""]*n)[:n]
            tbl_data.append([Paragraph(_safe(c), styles["td"]) for c in padded])
        t = Table(tbl_data, colWidths=cw, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,0),  C["navy"]),
            ("BACKGROUND",    (0,-1),(-1,-1), C["gold_lt"]),
            ("FONTNAME",      (0,-1),(-1,-1), styles["td_b"].fontName),
            ("FONTSIZE",      (0,-1),(-1,-1), 11),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0), (-1,-1), 11),
            ("BOTTOMPADDING", (0,0), (-1,-1), 11),
            ("LEFTPADDING",   (0,0), (-1,-1), 13),
            ("LINEBELOW",     (0,0), (-1,-2), 0.5, C["border"]),
            ("BOX",           (0,0), (-1,-1), 0.7, C["border"]),
        ]))
        elems.append(t)
        elems.append(Spacer(1, 5*mm))
        d = _draw_budget_donut(rows, CONTENT_W, font, bold)
        if d:
            elems.append(Paragraph("예산 배분", styles["sec_sub"]))
            elems.append(_drawing_to_flowable(d))
            elems.append(Spacer(1, 2*mm))

    non_table = "\n".join(l for l in text.splitlines()
                          if not re.match(r"^\s*\|",l)).strip()
    if non_table:
        for f in _md_to_flowables(non_table, styles): elems.append(f)
    return elems


def build_case_section(text: str, styles: dict) -> list:
    elems = _section_header("적용 사례", "case", styles)
    cases, misc = [], []
    for line in text.splitlines():
        s = line.lstrip("-•* ").strip()
        if "|" in s: cases.append([p.strip() for p in s.split("|")])
        elif s and not re.match(r"^\s*\|", line): misc.append(s)
    for i, parts in enumerate(cases):
        if len(parts) >= 3:
            t = Table([
                [Paragraph("업종",styles["label"]),
                 Paragraph("채널",styles["label"]),
                 Paragraph("결과",styles["label"])],
                [Paragraph(_safe(parts[0]),styles["td_b"]),
                 Paragraph(_safe(parts[1]),styles["td"]),
                 Paragraph(_safe(parts[2]),styles["td"])],
            ], colWidths=[CONTENT_W*0.18, CONTENT_W*0.22, CONTENT_W*0.60])
            t.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,0), C["bg"]),
                ("BACKGROUND",    (0,1),(-1,1), C["gold_lt"]),
                ("TOPPADDING",    (0,0),(-1,-1),10),
                ("BOTTOMPADDING", (0,0),(-1,-1),10),
                ("LEFTPADDING",   (0,0),(-1,-1),13),
                ("LINERIGHT",     (0,0),(0,-1), 4, C["gold"]),
                ("BOX",           (0,0),(-1,-1),0.7, C["border"]),
            ]))
            elems.append(t)
        elif parts:
            elems.append(Paragraph(f"•  {_safe(parts[0])}", styles["bullet"]))
        elems.append(Spacer(1, 4*mm))
    for m in misc:
        elems.append(Paragraph(_safe(m), styles["body"]))
    return elems


def build_next_section(text: str, styles: dict) -> list:
    elems = _section_header("다음 단계", "next", styles)
    steps, cta_lines = [], []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\.\s+(.+)", line)
        if m: steps.append((m.group(1), m.group(2).strip()))
        elif re.match(r"^\s*[-•*]\s+", line):
            steps.append(("•", line.lstrip("-•* ").strip()))
        elif line.strip(): cta_lines.append(line.strip())
    for num, content in steps:
        bg = C["teal"] if num != "•" else C["navy2"]
        t = Table([[
            Paragraph(f"<b>{num}</b>", ParagraphStyle(
                "sn", fontName=styles["th"].fontName,
                fontSize=13, textColor=C["white"],
                leading=18, alignment=TA_CENTER)),
            Paragraph(_safe(content), styles["step_txt"]),
        ]], colWidths=[0.9*cm, CONTENT_W - 0.9*cm - 3*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(0,0),  bg),
            ("BACKGROUND",    (1,0),(1,0),  C["bg2"]),
            ("VALIGN",        (0,0),(-1,-1),"MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1),12),
            ("BOTTOMPADDING", (0,0),(-1,-1),12),
            ("LEFTPADDING",   (0,0),(0,0),  4),
            ("LEFTPADDING",   (1,0),(1,0),  14),
            ("BOX",           (0,0),(-1,-1),0.5, C["border"]),
        ]))
        elems.append(t); elems.append(Spacer(1, 3*mm))
    if cta_lines:
        cta = " ".join(cta_lines[:2])
        box = Table([[Paragraph(_safe(cta), ParagraphStyle(
            "cta_f", fontName=styles["th"].fontName,
            fontSize=12, textColor=C["white"], leading=19))]],
            colWidths=[CONTENT_W])
        box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1),C["navy"]),
            ("TOPPADDING",    (0,0),(-1,-1),14),
            ("BOTTOMPADDING", (0,0),(-1,-1),14),
            ("LEFTPADDING",   (0,0),(-1,-1),18),
        ]))
        elems.append(Spacer(1,2*mm)); elems.append(box)
    return elems


def build_generic_section(key: str, text: str, styles: dict) -> list:
    label = SECTION_LABEL.get(key, key.replace("other:",""))
    elems = _section_header(label, key, styles)

    bullets = [l.lstrip("-•* ").strip() for l in text.splitlines()
               if re.match(r"^\s*[-•*]\s+", l)]
    paras   = [l.strip() for l in text.splitlines()
               if l.strip() and not re.match(r"^\s*[-•*]", l)
               and not re.match(r"^\s*[#|]", l)]

    # 본문 단락 → 왼쪽 강조 라인 박스
    if paras:
        body_content = [
            [Paragraph(_safe(p), ParagraphStyle(
                "gp", fontName=styles["body"].fontName,
                fontSize=11, textColor=C["text"], leading=20, spaceAfter=4))]
            for p in paras
        ]
        para_box = Table(body_content, colWidths=[CONTENT_W])
        para_box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C["bg"]),
            ("TOPPADDING",    (0,0),(-1,-1), 9),
            ("BOTTOMPADDING", (0,0),(-1,-1), 9),
            ("LEFTPADDING",   (0,0),(-1,-1), 18),
            ("RIGHTPADDING",  (0,0),(-1,-1), 18),
            ("LINERIGHT",     (0,0),(0,-1),  4, C["teal"]),
            ("BOX",           (0,0),(-1,-1), 0.5, C["border"]),
        ]))
        elems.append(para_box); elems.append(Spacer(1, 4*mm))

    # 불릿 → 2열 아이콘 카드 그리드
    if bullets:
        cols  = 2
        cw    = [CONTENT_W / cols] * cols
        cards = []
        for b in bullets:
            lbl, sep, val = b.partition(":")
            content = val.strip() if sep else lbl
            sub     = lbl.strip() if sep else ""
            card_rows = [
                [Paragraph("▶", ParagraphStyle(
                    "gi", fontName=styles["sec_num"].fontName,
                    fontSize=9, textColor=C["teal"], leading=13))],
                [Paragraph(_safe(content[:80]), ParagraphStyle(
                    "gb", fontName=styles["body_b"].fontName,
                    fontSize=11, textColor=C["navy"], leading=17))],
            ]
            if sub:
                card_rows.append([Paragraph(_safe(sub[:50]), ParagraphStyle(
                    "gs", fontName=styles["muted"].fontName,
                    fontSize=9, textColor=C["muted"], leading=13))])
            card = Table(card_rows, colWidths=[CONTENT_W / cols - 28])
            card.setStyle(TableStyle([
                ("TOPPADDING",    (0,0),(-1,-1), 3),
                ("BOTTOMPADDING", (0,0),(-1,-1), 3),
                ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ]))
            cards.append(card)
        for row_start in range(0, len(cards), cols):
            row_cards = cards[row_start:row_start + cols]
            while len(row_cards) < cols:
                row_cards.append(Paragraph("", styles["muted"]))
            grid = Table([row_cards], colWidths=cw)
            grid.setStyle(TableStyle([
                ("BACKGROUND",    (0,0),(-1,-1), C["white"]),
                ("TOPPADDING",    (0,0),(-1,-1), 14),
                ("BOTTOMPADDING", (0,0),(-1,-1), 14),
                ("LEFTPADDING",   (0,0),(-1,-1), 18),
                ("RIGHTPADDING",  (0,0),(-1,-1), 18),
                ("LINEBEFORE",    (1,0),(-1,-1), 0.5, C["border"]),
                ("LINEBELOW",     (0,0),(-1,-1), 0.5, C["border2"]),
                ("BOX",           (0,0),(-1,-1), 0.7, C["border"]),
            ]))
            elems.append(grid); elems.append(Spacer(1, 2*mm))

    # 테이블이 있으면 그대로 렌더
    table_lines = [l for l in text.splitlines() if re.match(r"^\s*\|", l)]
    if table_lines:
        for f in _md_to_flowables("\n".join(table_lines), styles):
            elems.append(f)
    return elems


def build_landing_preview(landing_md: str, styles: dict) -> list:
    if not landing_md.strip(): return []
    elems: list = [PageBreak()]
    elems += _section_header("랜딩 페이지 미리보기", "landing", styles)
    frame_hdr = Table([[Paragraph("●  ●  ●   미리보기 화면", styles["muted"])]],
                      colWidths=[CONTENT_W])
    frame_hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1),colors.HexColor("#E2E8F0")),
        ("TOPPADDING",    (0,0),(-1,-1),7),
        ("BOTTOMPADDING", (0,0),(-1,-1),7),
        ("LEFTPADDING",   (0,0),(-1,-1),12),
        ("BOX",           (0,0),(-1,-1),0.5, C["border"]),
    ]))
    elems.append(frame_hdr)
    content = []
    for line in landing_md.splitlines():
        if re.match(r"^##\s+", line):
            content.append(Paragraph(_safe(re.sub(r"^##\s+","",line)), ParagraphStyle(
                "lh1", fontName=styles["th"].fontName,
                fontSize=15, textColor=C["navy"], leading=22, spaceAfter=5)))
        elif re.match(r"^###\s+", line):
            content.append(Paragraph(_safe(re.sub(r"^###\s+","",line)), ParagraphStyle(
                "lh2", fontName=styles["sec_sub"].fontName,
                fontSize=12, textColor=C["teal"], leading=18, spaceAfter=3)))
        elif re.match(r"^\s*[-•*]\s+", line):
            content.append(Paragraph(f"•  {_safe(line.lstrip('-•* ').strip())}",
                                     styles["bullet"]))
        elif line.strip():
            content.append(Paragraph(_safe(line.strip()), styles["body"]))
        else:
            content.append(Spacer(1, 2*mm))
    inner = Table([[r] for r in content], colWidths=[CONTENT_W - 2*cm])
    inner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1),C["white"]),
        ("TOPPADDING",    (0,0),(-1,-1),3),
        ("BOTTOMPADDING", (0,0),(-1,-1),3),
        ("LEFTPADDING",   (0,0),(-1,-1),20),
        ("BOX",           (0,0),(-1,-1),0.5, C["border"]),
    ]))
    elems.append(inner)
    return elems


def build_about_us(styles: dict) -> list:
    elems: list = [PageBreak()]
    elems += _section_header("Onecation 소개", "next", styles)

    # 홈페이지 링크 박스
    link_box = Table([[
        Paragraph(
            f'<link href="{BRAND["url"]}" color="#0B7285">'
            f'<u>🌐  {BRAND["website"]}</u></link>',
            styles["link"]),
    ]], colWidths=[CONTENT_W])
    link_box.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C["teal_lt"]),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(-1,-1), 16),
        ("BOX",           (0,0),(-1,-1), 0.7, C["border"]),
        ("LINERIGHT",     (0,0),(0,-1),  4, C["teal"]),
    ]))
    elems.append(link_box)
    elems.append(Spacer(1, 4*mm))

    rows = [
        ["회사명",      BRAND["name"]],
        ["서비스",      "데이터 기반 디지털 마케팅, 랜딩 페이지 구축, 광고 운영"],
        ["전문 채널",   "네이버 플레이스 · 메타 광고 · 구글 광고 · 인스타그램 · 당근 · 백링크 SEO"],
        ["연락처",      BRAND["phone"]],
        ["이메일",      BRAND["email"]],
        ["제안 유효기간", f"{TODAY} 기준 2주"],
    ]
    tbl_data = [[Paragraph(_safe(k), styles["label"]),
                 Paragraph(_safe(v), styles["value"])] for k, v in rows]
    t = Table(tbl_data, colWidths=[CONTENT_W*0.22, CONTENT_W*0.78])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,-1),  C["bg"]),
        ("BACKGROUND",    (1,0),(1,-1),  C["white"]),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0),(-1,-1), 12),
        ("BOTTOMPADDING", (0,0),(-1,-1), 12),
        ("LEFTPADDING",   (0,0),(-1,-1), 14),
        ("LINEBELOW",     (0,0),(-1,-2), 0.5, C["border2"]),
        ("BOX",           (0,0),(-1,-1), 0.7, C["border"]),
    ]))
    elems.append(t)
    return elems


# ═══════════════════════════════════════════════════════════════════════════════
# 메인 PDF 조립
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pdf(company_name: str, proposal_md: str, landing_md: str,
                 output_path: Path, font: str, bold: str, styles: dict) -> None:
    sections  = parse_sections(proposal_md)
    exec_text = sections.get("executive", "")
    exec_data, proof = parse_exec_bullets(exec_text)

    doc = SimpleDocTemplate(
        str(output_path), pagesize=(PAGE_W, PAGE_H),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 0.3*cm,
        bottomMargin=FOOTER_H + 1.0*cm,
        title=f"{company_name} 마케팅 성장 제안서",
        author=BRAND["name"],
    )

    cover_cb   = make_cover_cb(font, bold, company_name, exec_data)
    content_cb = make_page_cb(font, bold, company_name)

    story: list = [Spacer(1, PAGE_H * 0.57 - MARGIN - 0.3*cm), PageBreak()]
    story.extend(build_exec_summary(exec_data, proof, exec_text, styles))
    story.append(PageBreak())

    BUILDER_MAP = {
        "market":     lambda t: build_market_section(t, styles),
        "competitor": lambda t: build_competitor_section(t, styles, font, bold),
        "roadmap":    lambda t: build_roadmap_section(t, styles, font, bold),
        "kpi":        lambda t: build_kpi_section(t, styles, font, bold),
        "offer":      lambda t: build_offer_section(t, styles, font, bold),
        "case":       lambda t: build_case_section(t, styles),
        "next":       lambda t: build_next_section(t, styles),
    }
    for key in DETAIL_ORDER:
        content = sections.get(key, "").strip()
        if not content: continue
        story.extend(BUILDER_MAP.get(key, lambda t: build_generic_section(key,t,styles))(content))
        story.append(Spacer(1, 6*mm))

    skip = {"executive", *DETAIL_ORDER, "landing", "positioning"}
    for key, content in sections.items():
        if key in skip or not content.strip(): continue
        story.extend(build_generic_section(key, content, styles))
        story.append(Spacer(1, 6*mm))

    story.extend(build_landing_preview(landing_md, styles))
    story.extend(build_about_us(styles))

    doc.build(story,
              onFirstPage=lambda c,d: cover_cb(c,d),
              onLaterPages=lambda c,d: content_cb(c,d))
    print(f"  [OK] {output_path.name}  ({output_path.stat().st_size // 1024} KB)")


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Sales Factory → 제안서 PDF")
    parser.add_argument("--proposal", default=str(BASE_DIR / "proposal.md"))
    parser.add_argument("--landing",  default=str(BASE_DIR / "landing_pages.md"))
    parser.add_argument("--company",  default=None)
    parser.add_argument("--out",      default=str(OUTPUT_DIR))
    args = parser.parse_args()

    proposal_path = Path(args.proposal)
    if not proposal_path.exists():
        print(f"[오류] 파일 없음: {proposal_path}"); sys.exit(1)

    landing_path = Path(args.landing)
    out_dir      = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    font, bold = register_fonts()
    styles     = make_styles(font, bold)

    proposal_text = proposal_path.read_text(encoding="utf-8")
    landing_text  = landing_path.read_text(encoding="utf-8") if landing_path.exists() else ""
    companies     = parse_companies(proposal_text)

    m = re.search(r"대상\s*회사\s*수\s*:\s*(\d+)", proposal_text, re.IGNORECASE)
    if m and len(companies) != int(m.group(1)):
        print(f"[안내] proposal.md '대상 회사 수: {m.group(1)}'인데 # (H1) 블록은 {len(companies)}개입니다. PDF는 {len(companies)}개만 생성됩니다.\n")

    if args.company:
        companies = {k:v for k,v in companies.items()
                     if args.company in k or k in args.company}
        if not companies:
            print(f"[오류] '{args.company}' 없음"); sys.exit(1)

    print(f"\n[Sales Factory PDF Generator]")
    print(f"  폰트: {'Malgun Gothic' if font=='KR' else font}")
    print(f"  회사: {len(companies)}개  →  {out_dir}\n")

    for company_name, proposal_md in companies.items():
        display    = company_name if company_name != "default" else "제안서"
        landing_md = find_company_landing(landing_text, company_name)
        safe       = re.sub(r'[\\/*?:"<>|]', "_", display)
        out        = out_dir / f"{safe}_제안서_{TODAY_FILE}.pdf"
        try:
            generate_pdf(display, proposal_md, landing_md, out, font, bold, styles)
        except Exception as e:
            print(f"  [실패] {display}: {e}")
            import traceback; traceback.print_exc()

    print(f"\n완료 → {out_dir}")


if __name__ == "__main__":
    main()
