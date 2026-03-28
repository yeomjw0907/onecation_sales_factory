#!/usr/bin/env python3
"""
generate_pdf_playwright.py — HTML/CSS → Playwright PDF
벤토 그리드 + 섹션별 시각화 + 표 페이지 브레이크 픽스
"""

import argparse
import re
import sys
from pathlib import Path

from generate_pdf import (
    BRAND,
    BASE_DIR,
    OUTPUT_DIR,
    TODAY,
    TODAY_FILE,
    SECTION_LABEL,
    DETAIL_ORDER,
    parse_companies,
    parse_sections,
    parse_exec_bullets,
)


# ─── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    s = str(s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def _inline_md(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s


def _parse_table_lines(table_lines: list[str]) -> tuple[list[str], list[list[str]]]:
    if len(table_lines) < 2:
        return [], []
    def row(l: str) -> list[str]:
        return [c.strip() for c in l.strip().strip("|").split("|")]
    headers = row(table_lines[0])
    rows = []
    for l in table_lines[2:]:
        if re.match(r"^\s*\|[-| :]+\|\s*$", l):
            continue
        rows.append(row(l))
    return headers, rows


def _md_to_html(md: str) -> str:
    """마크다운 → HTML (테이블, 헤더, 불릿, 굵게)."""
    if not md or not md.strip():
        return ""
    lines = md.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if re.match(r"^\s*\|", line):
            table_lines = []
            while i < len(lines) and re.match(r"^\s*\|", lines[i]):
                table_lines.append(lines[i])
                i += 1
            headers, rows = _parse_table_lines(table_lines)
            if headers:
                out.append("<table class='proposal-table'>")
                out.append("<thead><tr>")
                for h in headers:
                    out.append(f"<th>{_esc(h)}</th>")
                out.append("</tr></thead><tbody>")
                for row in rows:
                    out.append("<tr>")
                    for c in (row + [""] * len(headers))[:len(headers)]:
                        out.append(f"<td>{_inline_md(_esc(c))}</td>")
                    out.append("</tr>")
                out.append("</tbody></table>")
            continue
        if re.match(r"^##\s+", line):
            t = re.sub(r"^##\s+", "", stripped)
            out.append(f"<h2>{_esc(t)}</h2>")
            i += 1; continue
        if re.match(r"^###\s+", line):
            t = re.sub(r"^###\s+", "", stripped)
            out.append(f"<h3>{_esc(t)}</h3>")
            i += 1; continue
        if re.match(r"^\s*[-*•]\s+", line):
            out.append("<ul>")
            while i < len(lines) and re.match(r"^\s*[-*•]\s+", lines[i]):
                part = re.sub(r"^\s*[-*•]\s+", "", lines[i].strip())
                out.append(f"<li>{_inline_md(_esc(part))}</li>")
                i += 1
            out.append("</ul>")
            continue
        if stripped:
            out.append(f"<p>{_inline_md(_esc(stripped))}</p>")
        i += 1
    return "\n".join(out)


# ─── 키-값 파서 (** key:** value 형식) ───────────────────────────────────────

def _parse_kv_bullets(content: str) -> tuple[dict[str, str], list[str]]:
    """**키:** 값 형식의 불릿을 dict로, 나머지는 list로 반환."""
    metrics: dict[str, str] = {}
    extra: list[str] = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
        if m:
            key = re.sub(r"\s*\(.*?\)", "", m.group(1)).strip()
            val = m.group(2).strip().rstrip(".")
            metrics[key] = val
        else:
            cleaned = re.sub(r"^[-*•]\s*", "", s)
            if cleaned and not re.match(r"^-+$|^\|", cleaned):
                extra.append(cleaned)
    return metrics, extra


# ─── 섹션별 렌더러 ────────────────────────────────────────────────────────────

def _render_market_bento(content: str) -> str:
    """시장 현황 → 벤토 그리드 카드 + 키워드 칩 + 하이라이트 박스."""
    metrics, extra = _parse_kv_bullets(content)

    cards: list[str] = []

    # 시장 규모 — large (span 2)
    size_key = next((k for k in metrics if "규모" in k), None)
    if size_key:
        val = metrics[size_key]
        num_m = re.search(r"[\d,조억만원\s]+", val)
        num = num_m.group(0).strip() if num_m else val[:20]
        sub = val[len(num_m.group(0)):].strip(" /|") if num_m else ""
        sub = sub[:70]
        cards.append(f"""
        <div class="bcard blue bento-span-2">
          <div class="bcard-label">📊 {_esc(size_key)}</div>
          <div class="bcard-value xl">{_esc(num)}</div>
          {f'<div class="bcard-sub">{_esc(sub)}</div>' if sub else ''}
        </div>""")

    # 성장 트렌드
    trend_key = next((k for k in metrics if "트렌드" in k or "성장" in k or "추이" in k), None)
    if trend_key:
        val = metrics[trend_key]
        up = any(w in val for w in ["성장", "증가", "상승", "확대", "급성장", "빠르게"])
        color = "green" if up else "amber"
        arrow = "↑" if up else "→"
        cards.append(f"""
        <div class="bcard {color}">
          <div class="bcard-label">📈 {_esc(trend_key)}</div>
          <div class="bcard-value">{arrow} {_esc(val[:60])}</div>
        </div>""")

    # 핵심 키워드 → 칩
    kw_key = next((k for k in metrics if "키워드" in k), None)
    if kw_key:
        kws = [kw.strip() for kw in re.split(r"[,、]", metrics[kw_key]) if kw.strip()]
        chips = "".join(f'<span class="chip blue">{_esc(kw)}</span>' for kw in kws[:6])
        cards.append(f"""
        <div class="bcard">
          <div class="bcard-label">🔍 {_esc(kw_key)}</div>
          <div class="chips" style="margin-top:var(--s2);">{chips}</div>
        </div>""")

    # 기타 metrics → 작은 카드들
    skip_keys = {size_key, trend_key, kw_key}
    why_key = next((k for k in metrics if "지금" in k or "기회" in k), None)
    skip_keys.add(why_key)
    for k, v in metrics.items():
        if k in skip_keys or not k or not v:
            continue
        cards.append(f"""
        <div class="bcard">
          <div class="bcard-label">{_esc(k)}</div>
          <div class="bcard-value" style="font-size:13px;">{_esc(v[:80])}</div>
        </div>""")

    html: list[str] = []
    if cards:
        html.append('<div class="bento bento-3">')
        html.extend(cards[:5])
        html.append("</div>")

    # 왜 지금인가 → 하이라이트 박스
    if why_key and why_key in metrics:
        html.append(f"""
        <div class="hl-box amber" style="margin-top:var(--s3);">
          <div class="hl-label">⚡ WHY NOW — {_esc(why_key)}</div>
          <div class="hl-text">{_esc(metrics[why_key])}</div>
        </div>""")

    if extra:
        html.append(f'<div style="margin-top:var(--s3);">{_md_to_html(chr(10).join("- " + l for l in extra))}</div>')

    return "\n".join(html) if html else _md_to_html(content)


def _render_competitor_visual(content: str) -> str:
    """경쟁사 분석 → 컴팩트 테이블 + 강점/약점 배지."""
    table_lines = [l for l in content.splitlines() if re.match(r"^\s*\|", l)]
    other_lines = [l for l in content.splitlines() if not re.match(r"^\s*\|", l)]

    if not table_lines:
        return _md_to_html(content)

    headers, rows = _parse_table_lines(table_lines)
    if not headers:
        return _md_to_html(content)

    # 강점/약점 컬럼 인덱스 탐지
    strength_idx = next((i for i, h in enumerate(headers) if "강점" in h or "장점" in h), -1)
    weakness_idx = next((i for i, h in enumerate(headers) if "약점" in h or "단점" in h), -1)

    html: list[str] = ['<div style="overflow:visible;"><table class="comp-table">']
    html.append("<thead><tr>")
    for h in headers:
        html.append(f"<th>{_esc(h)}</th>")
    html.append("</tr></thead><tbody>")

    for row in rows[:5]:
        html.append("<tr>")
        padded = (row + [""] * len(headers))[:len(headers)]
        for i, cell in enumerate(padded):
            cell_short = cell[:80]
            if i == strength_idx and cell:
                html.append(f'<td><span class="cbadge up">✓ {_esc(cell_short)}</span></td>')
            elif i == weakness_idx and cell:
                html.append(f'<td><span class="cbadge down">△ {_esc(cell_short)}</span></td>')
            else:
                html.append(f"<td>{_esc(cell_short)}</td>")
        html.append("</tr>")

    html.append("</tbody></table></div>")

    remaining = "\n".join(l for l in other_lines if l.strip()).strip()
    if remaining:
        html.append(f'<div style="margin-top:var(--s3);">{_md_to_html(remaining)}</div>')

    return "\n".join(html)


def _render_current_diagnosis(content: str) -> str:
    """현황 진단 → 빨간 진단 카드 목록."""
    metrics, extra = _parse_kv_bullets(content)

    # 불릿 형태로 된 문제점들 수집
    issues: list[tuple[str, str]] = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        # **제목:** 설명 형태
        m = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
        if m:
            issues.append((m.group(1).strip(), m.group(2).strip()))
        elif re.match(r"^\s*[-*•]\s+", s) and not re.match(r"^\s*\|", s):
            cleaned = re.sub(r"^\s*[-*•]\s+", "", s)
            # 일반 불릿은 짧은 제목 없이 추가
            issues.append(("", cleaned))

    if not issues:
        return _md_to_html(content)

    icons = ["⚠️", "🔍", "📉", "❌", "💡"]
    html: list[str] = ['<div class="diagnosis-grid">']
    for idx, (title, body) in enumerate(issues[:4]):
        icon = icons[idx % len(icons)]
        html.append(f"""
        <div class="diag-card">
          <div class="diag-icon">{icon}</div>
          <div>
            {f'<div class="diag-title">{_esc(title)}</div>' if title else ''}
            <div class="diag-text">{_esc(body[:120])}</div>
          </div>
        </div>""")
    html.append("</div>")
    return "\n".join(html)


def _render_opportunity(content: str) -> str:
    """기회 → 파란 기회 카드 그리드."""
    issues: list[tuple[str, str]] = []
    for line in content.splitlines():
        s = line.strip()
        if not s or re.match(r"^\s*\|", s):
            continue
        m = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
        if m:
            issues.append((m.group(1).strip(), m.group(2).strip()))
        elif re.match(r"^\s*[-*•]\s+", s):
            cleaned = re.sub(r"^\s*[-*•]\s+", "", s)
            issues.append(("", cleaned))

    if not issues:
        return _md_to_html(content)

    icons = ["🎯", "📈", "🚀", "💡", "🌟"]
    html: list[str] = ['<div class="opportunity-grid">']
    for idx, (title, body) in enumerate(issues[:4]):
        icon = icons[idx % len(icons)]
        html.append(f"""
        <div class="opp-card">
          <div class="opp-icon">{icon}</div>
          {f'<div class="opp-title">{_esc(title)}</div>' if title else ''}
          <div class="opp-text">{_esc(body[:160])}</div>
        </div>""")
    html.append("</div>")

    # 나머지 텍스트
    extra = "\n".join(
        l for l in content.splitlines()
        if l.strip() and not re.match(r"^\s*[-*•]\s+", l.strip()) and "**" not in l
    ).strip()
    if extra:
        html.append(f'<div class="hl-box blue" style="margin-top:var(--s3);"><div class="hl-text">{_md_to_html(extra)}</div></div>')

    return "\n".join(html)


def _render_solution(content: str) -> str:
    """제안 솔루션 → 그린 하이라이트 + 벤토 카드."""
    metrics, extra = _parse_kv_bullets(content)

    # 핵심 포인트 불릿 추출
    bullets: list[str] = []
    brief_text: list[str] = []
    in_brief = False
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if "랜딩" in s and "브리프" in s:
            in_brief = True
            continue
        if in_brief:
            if re.match(r"^\s*[-*•]\s+", s):
                m2 = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
                if m2:
                    brief_text.append(f"<strong>{_esc(m2.group(1))}</strong>: {_esc(m2.group(2)[:80])}")
                else:
                    cleaned = re.sub(r"^\s*[-*•]\s+", "", s)
                    brief_text.append(_esc(cleaned[:100]))
        elif re.match(r"^\s*[-*•]\s+", s):
            m3 = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
            if m3:
                bullets.append(f"<strong>{_esc(m3.group(1))}</strong>: {_esc(m3.group(2)[:80])}")
            else:
                cleaned = re.sub(r"^\s*[-*•]\s+", "", s)
                bullets.append(_esc(cleaned[:100]))

    html: list[str] = []

    # 메인 설명 (첫 단락)
    first_para = next(
        (l.strip() for l in content.splitlines()
         if l.strip() and not re.match(r"^\s*[-*•#]", l.strip()) and "**" not in l),
        ""
    )
    if first_para:
        html.append(f'<div class="hl-box green"><div class="hl-text">{_esc(first_para)}</div></div>')

    if bullets:
        html.append('<div class="bento bento-2" style="margin-top:var(--s3);">')
        for b in bullets[:4]:
            html.append(f'<div class="bcard"><div class="bcard-value" style="font-size:13px;">{b}</div></div>')
        html.append("</div>")

    if brief_text:
        html.append('<div class="bcard" style="margin-top:var(--s3);">')
        html.append('<div class="bcard-label">📄 랜딩페이지 브리프</div>')
        for bt in brief_text[:4]:
            html.append(f'<div style="font-size:12px;color:var(--gray7);margin-top:6px;">{bt}</div>')
        html.append("</div>")

    return "\n".join(html) if html else _md_to_html(content)


def _render_channel_cards(content: str) -> str:
    """채널 전략 → 채널 카드 그리드."""
    channels: list[tuple[str, str]] = []
    current_ch: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        m = re.match(r"^###\s+(.+)$", line.strip())
        if m:
            if current_ch is not None:
                channels.append((current_ch, "\n".join(current_lines)))
            current_ch = m.group(1).strip()
            current_lines = []
        else:
            if current_ch is not None:
                current_lines.append(line)
    if current_ch is not None:
        channels.append((current_ch, "\n".join(current_lines)))

    if not channels:
        return _md_to_html(content)

    html: list[str] = ['<div class="channel-grid">']
    for ch_name, ch_content in channels[:4]:
        budget = why = target = kpi = ""
        for line in ch_content.splitlines():
            s = line.strip()
            kv = re.search(r":\s*(.+)$", s)
            if not kv:
                continue
            val = kv.group(1).strip()
            sl = s.lower()
            if "예산" in sl:
                budget = val[:30]
            elif "왜 이 채널" in sl or "이유" in sl:
                why = val[:100]
            elif "타깃" in sl or "타겟" in sl:
                target = val[:80]
            elif "kpi" in sl:
                kpi = val[:60]

        html.append('<div class="channel-card">')
        html.append(f'<div class="ch-name">{_esc(ch_name)}</div>')
        html.append('<div class="ch-meta">')
        if budget:
            html.append(f'<span class="chip blue">💰 {_esc(budget)}</span>')
        if target:
            html.append(f'<span class="chip gray">🎯 {_esc(target[:20])}...</span>' if len(target) > 20 else f'<span class="chip gray">🎯 {_esc(target)}</span>')
        html.append("</div>")
        if why:
            html.append(f'<div class="ch-body">{_esc(why)}</div>')
        if kpi:
            html.append(f'<div class="ch-kpi">📊 {_esc(kpi)}</div>')
        html.append("</div>")
    html.append("</div>")
    return "\n".join(html)


def _render_roadmap_timeline(content: str) -> str:
    """로드맵 → 3단계 타임라인 카드."""
    phases: list[tuple[str, list[str]]] = []
    current_phase: str | None = None
    current_items: list[str] = []

    for line in content.splitlines():
        s = line.strip()
        if re.match(r"^#{2,3}\s+", s):
            if current_phase is not None:
                phases.append((current_phase, current_items[:]))
            current_phase = re.sub(r"^#{2,3}\s+", "", s).strip()
            current_items = []
        elif re.match(r"^\*\*(.+)\*\*\s*$", s) and not current_phase:
            if current_phase is not None:
                phases.append((current_phase, current_items[:]))
            current_phase = re.sub(r"\*\*", "", s).strip()
            current_items = []
        elif s and re.match(r"^\s*[-*•]\s+", s) and current_phase:
            item = re.sub(r"^\s*[-*•]\s+", "", s)
            item = re.sub(r"\*\*", "", item)
            current_items.append(item[:80])
        elif s and not re.match(r"^\s*[-*•]\s+", s) and current_phase and "**" in s:
            pass  # skip bold-only lines within a phase

    if current_phase is not None:
        phases.append((current_phase, current_items))

    if not phases:
        return _md_to_html(content)

    m_classes = ["", "m2", "m3"]
    html: list[str] = ['<div class="timeline-grid">']
    for i, (phase_name, items) in enumerate(phases[:3]):
        mc = m_classes[i] if i < len(m_classes) else ""
        html.append(f'<div class="tl-phase {mc}">')
        html.append(f'<div class="tl-label {mc}">{_esc(phase_name)}</div>')
        if items:
            html.append("<ul>")
            for item in items[:6]:
                html.append(f"<li>{_esc(item)}</li>")
            html.append("</ul>")
        html.append("</div>")
    html.append("</div>")
    return "\n".join(html)


def _render_kpi_cards(content: str) -> str:
    """KPI → 메트릭 카드 그리드."""
    table_lines = [l for l in content.splitlines() if re.match(r"^\s*\|", l)]
    metrics: list[dict[str, str]] = []

    if table_lines:
        headers, rows = _parse_table_lines(table_lines)
        for row in rows[:6]:
            padded = (row + [""] * 4)[:4]
            metrics.append({"label": padded[0], "value": padded[1], "change": padded[2]})
    else:
        for line in content.splitlines():
            s = line.strip()
            m = re.match(r"^\*?\s*[-*]?\s*\*\*(.+?)\*\*\s*[:\s]+\s*(.+)$", s)
            if m:
                metrics.append({"label": m.group(1).strip(), "value": m.group(2).strip()[:20], "change": ""})

    if not metrics:
        return _md_to_html(content)

    html: list[str] = ['<div class="kpi-grid">']
    for metric in metrics[:4]:
        val = metric["value"][:15]
        lbl = metric["label"][:30]
        chg = metric.get("change", "")[:20]
        html.append(f"""
        <div class="kpi-card">
          <div class="kv">{_esc(val)}</div>
          <div class="kl">{_esc(lbl)}</div>
          {f'<div class="kp">{_esc(chg)}</div>' if chg else ''}
        </div>""")
    html.append("</div>")

    # 테이블 외 텍스트
    extra = "\n".join(
        l for l in content.splitlines()
        if l.strip() and not re.match(r"^\s*\|", l) and not re.match(r"^\s*\*?\s*[-*]?\s*\*\*", l.strip())
    ).strip()
    if extra:
        html.append(f'<div style="margin-top:var(--s3);">{_md_to_html(extra)}</div>')

    return "\n".join(html)


def _render_offer(content: str) -> str:
    """투자 및 가격 → 프라이싱 카드."""
    metrics, extra = _parse_kv_bullets(content)

    html: list[str] = []
    if metrics:
        html.append('<div class="bento bento-3">')
        colors = ["navy", "teal", "blue", "amber", "green"]
        for idx, (k, v) in enumerate(list(metrics.items())[:4]):
            c = colors[idx % len(colors)]
            html.append(f"""
            <div class="bcard {c}">
              <div class="bcard-label">{_esc(k)}</div>
              <div class="bcard-value lg">{_esc(v[:40])}</div>
            </div>""")
        html.append("</div>")

    if extra:
        html.append(f'<div style="margin-top:var(--s3);">{_md_to_html(chr(10).join("- " + l for l in extra))}</div>')

    return "\n".join(html) if html else _md_to_html(content)


def _render_case_study(content: str) -> str:
    """적용 사례 → 그린 하이라이트 카드 + 수치 뱃지."""
    lines = content.splitlines()
    cases: list[str] = []
    current: list[str] = []
    for line in lines:
        s = line.strip()
        if re.match(r"^###\s+|^##\s+", s):
            if current:
                cases.append("\n".join(current))
            current = [re.sub(r"^#{2,3}\s+", "", s)]
        elif s:
            current.append(s)
    if current:
        cases.append("\n".join(current))

    if not cases:
        cases = [content.strip()]

    # 숫자 추출 (성과 지표)
    html: list[str] = []
    icons = ["📌", "📊", "🏆", "💡"]

    for idx, case_text in enumerate(cases[:2]):
        lines2 = case_text.splitlines()
        title = lines2[0] if lines2 else ""
        body = " ".join(lines2[1:]).strip()

        nums = re.findall(r"(\d+[%배만억건회원]+)", body or case_text)
        badges = "".join(
            f'<span class="chip green">{_esc(n)}</span>' for n in nums[:4]
        )

        icon = icons[idx % len(icons)]
        html.append(f"""
        <div class="proof-card" style="margin-bottom:var(--s3);">
          <div class="pc-tag">{icon} 적용 사례</div>
          {f'<div style="font-size:15px;font-weight:700;color:var(--black);margin-bottom:var(--s2);">{_esc(title)}</div>' if title else ''}
          {f'<div class="chips" style="margin-bottom:var(--s2);">{badges}</div>' if badges else ''}
          <div class="pc-text">{_esc((body or case_text)[:300])}</div>
        </div>""")

    if not html:
        return _md_to_html(content)

    return "\n".join(html)


def _render_next_steps(content: str) -> str:
    """다음 단계 → 넘버드 스텝 카드."""
    steps: list[str] = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        cleaned = re.sub(r"^\s*[-*•\d.]+\s*", "", re.sub(r"\*\*", "", s))
        if cleaned:
            steps.append(cleaned)

    if not steps:
        return _md_to_html(content)

    step_colors = ["blue", "green", "amber", "purple"]
    html: list[str] = ['<div class="bento bento-2">']
    for i, step in enumerate(steps[:4]):
        c = step_colors[i % len(step_colors)]
        html.append(f"""
        <div class="bcard {c}">
          <div class="bcard-label">STEP {i+1:02d}</div>
          <div class="bcard-value" style="font-size:13px;">{_esc(step[:120])}</div>
        </div>""")
    html.append("</div>")
    return "\n".join(html)


# ─── CSS ──────────────────────────────────────────────────────────────────────

SECTION_ICONS = {
    "executive": "summary",
    "market": "bar_chart",
    "competitor": "groups",
    "current": "analytics",
    "opportunity": "trending_up",
    "solution": "lightbulb",
    "channel": "campaign",
    "roadmap": "map",
    "kpi": "show_chart",
    "offer": "payments",
    "case": "verified_user",
    "next": "contact_page",
    "landing": "web",
    "about": "info",
}


def _get_css() -> str:
    return """
    :root {
      --s1:8px;--s2:16px;--s3:24px;--s4:32px;--s5:40px;--s6:48px;
      --primary:#3182F6;--primary-dark:#1B64DA;--primary-soft:#E8F3FF;
      --black:#191F28;--gray9:#333D4B;--gray7:#4E5968;--gray5:#8B95A1;
      --gray3:#B0B8C1;--gray2:#E5E8EB;--gray1:#F2F4F6;--white:#FFFFFF;
      --success:#00C48C;
      --radius-sm:8px;--radius-md:12px;--radius-lg:16px;
      --shadow-sm:0 2px 8px rgba(0,0,0,0.04);
      --shadow-md:0 4px 20px rgba(0,0,0,0.06);
      --shadow-card:0 2px 12px rgba(0,0,0,0.04),0 0 1px rgba(0,0,0,0.04);
    }
    *{box-sizing:border-box;margin:0;padding:0;}
    body{
      font-family:'Noto Sans KR',-apple-system,BlinkMacSystemFont,sans-serif;
      font-size:14px;font-weight:400;line-height:1.6;letter-spacing:-0.01em;
      color:var(--black);background:var(--white);
      -webkit-print-color-adjust:exact;print-color-adjust:exact;
    }

    /* ── 페이지 섹션 (슬라이드) ───────────────────── */
    .page-section{
      page-break-after:always;break-after:page;
      min-height:100vh;
      padding:48px 56px 80px;
      display:flex;flex-direction:column;
      position:relative;overflow:hidden;
    }
    .page-section:last-of-type{page-break-after:auto;break-after:auto;}
    .page-section .section-content{flex:1;overflow:hidden;}
    .bcard,.bento,.exec-grid,.exec-wrap,.comp-table,.proposal-table,
    .timeline-grid,.kpi-grid,.channel-grid,.diagnosis-grid,.opportunity-grid,
    .hl-box,.proof-card,.proof-box,.about-box,.diag-card,.opp-card,
    .channel-card,.kpi-card,.tl-phase{page-break-inside:avoid;break-inside:avoid;}

    /* ── 페이지 푸터 ─────────────────────────────── */
    .page-footer{
      position:absolute;bottom:0;left:0;right:0;height:48px;
      padding:0 56px;display:flex;align-items:center;justify-content:space-between;
      font-size:11px;color:var(--gray5);border-top:1px solid var(--gray2);
      background:rgba(255,255,255,0.97);
    }
    .page-footer .pf-brand{font-weight:600;color:var(--gray7);}
    .page-footer .pf-num{font-weight:700;color:var(--black);font-size:12px;letter-spacing:0.05em;}
    .page-footer .pf-num .pf-total{font-weight:400;color:var(--gray5);}

    /* ── 커버 ────────────────────────────────────── */
    .cover{
      background:linear-gradient(135deg,#0D1B2A 0%,#1B3358 40%,#0B7285 100%);
      color:var(--white);justify-content:space-between;
      padding:var(--s6) var(--s6) 0;position:relative;overflow:hidden;
    }
    .cover::before{
      content:'';position:absolute;inset:0;
      background:
        radial-gradient(ellipse 80% 50% at 70% 20%,rgba(200,146,10,.15) 0%,transparent 50%),
        radial-gradient(ellipse 60% 40% at 20% 80%,rgba(11,114,133,.20) 0%,transparent 50%);
      pointer-events:none;
    }
    .cover .cover-inner{position:relative;z-index:1;}
    .cover .cover-inner .brand{position:absolute;top:0;right:0;}
    .cover .company{font-size:40px;font-weight:700;letter-spacing:-0.03em;line-height:1.2;margin-bottom:var(--s2);}
    .cover .subtitle{font-size:16px;font-weight:500;color:rgba(255,255,255,.85);}
    .cover .meta{font-size:13px;color:rgba(255,255,255,.6);margin-top:var(--s5);}
    .cover .stat-row{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s3);margin-top:var(--s5);}
    .cover .stat-card{background:rgba(255,255,255,.08);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.12);border-radius:var(--radius-md);padding:var(--s4);}
    .cover .stat-card .label{font-size:11px;font-weight:600;color:#C8920A;letter-spacing:.04em;text-transform:uppercase;margin-bottom:var(--s1);}
    .cover .stat-card .value{font-size:16px;font-weight:700;color:var(--white);}
    .cover .footer-bar{
      background:rgba(0,0,0,.25);margin:0 calc(-1*var(--s6)) 0;padding:var(--s3) var(--s6);
      display:flex;justify-content:space-between;align-items:center;
      font-size:12px;color:rgba(255,255,255,.9);position:relative;z-index:1;
    }
    .cover .footer-bar a{color:#C8920A;text-decoration:none;font-weight:600;}

    /* ── 섹션 헤더 ───────────────────────────────── */
    .section-badge{display:inline-flex;align-items:center;gap:var(--s1);margin-bottom:var(--s2);}
    .section-badge .material-symbols-outlined,.material-symbols-outlined{
      font-family:'Material Symbols Outlined';font-weight:normal;font-style:normal;
      font-size:28px;display:inline-block;line-height:1;text-transform:none;
      letter-spacing:normal;word-wrap:normal;white-space:nowrap;direction:ltr;
      color:var(--primary);
      font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 24;
    }
    .section-badge .section-num{font-size:13px;font-weight:700;color:var(--primary);}
    .section-num{
      display:inline-flex;align-items:center;justify-content:center;
      width:36px;height:36px;border-radius:var(--radius-sm);
      background:#0D1B2A;color:var(--white);
      font-size:14px;font-weight:700;letter-spacing:0.02em;
    }
    .section-heading{
      font-size:26px;font-weight:700;color:#0D1B2A;
      letter-spacing:-0.02em;margin-bottom:var(--s4);
      padding-bottom:var(--s2);border-bottom:3px solid #C8920A;
    }

    /* ── 실행 요약 ───────────────────────────────── */
    .exec-wrap{margin-top:var(--s2);}
    .exec-grid{
      display:grid;grid-template-columns:160px 1fr;gap:0;
      border-radius:var(--radius-md);overflow:hidden;
      border:1px solid var(--gray2);margin-bottom:1px;
    }
    .exec-grid .label{background:#0D1B2A;padding:var(--s3) var(--s4);font-size:12px;font-weight:600;color:rgba(255,255,255,.9);letter-spacing:.02em;}
    .exec-grid .value{padding:var(--s3) var(--s4);font-size:14px;color:var(--black);}
    .exec-grid .value.cta{color:var(--primary);font-weight:700;}

    /* ── proof 박스 ──────────────────────────────── */
    .proof-box{
      background:linear-gradient(135deg,#F0FDF4 0%,#ECFDF5 100%);
      border-radius:var(--radius-md);border-left:4px solid var(--success);
      padding:var(--s4);margin-top:var(--s4);
    }
    .proof-box .tag{font-size:11px;font-weight:700;color:var(--success);margin-bottom:var(--s1);letter-spacing:.02em;}
    .proof-card{
      background:linear-gradient(135deg,#F0FDF4 0%,#ECFDF5 100%);
      border-radius:var(--radius-lg);border:1px solid #86EFAC;
      padding:var(--s5);margin-bottom:var(--s3);
    }
    .proof-card .pc-tag{font-size:11px;font-weight:700;color:var(--success);letter-spacing:.05em;margin-bottom:var(--s2);text-transform:uppercase;}
    .proof-card .pc-text{font-size:14px;color:var(--gray9);line-height:1.8;}

    /* ── 벤토 그리드 ─────────────────────────────── */
    .bento{display:grid;gap:var(--s3);margin:var(--s3) 0;}
    .bento-2{grid-template-columns:1fr 1fr;}
    .bento-3{grid-template-columns:repeat(3,1fr);}
    .bento-4{grid-template-columns:repeat(4,1fr);}
    .bento-2-1{grid-template-columns:2fr 1fr;}
    .bento-1-2{grid-template-columns:1fr 2fr;}
    .bento-span-2{grid-column:span 2;}
    .bento-span-3{grid-column:span 3;}

    /* ── 벤토 카드 ───────────────────────────────── */
    .bcard{
      background:var(--gray1);border-radius:var(--radius-md);
      padding:var(--s4);border:1px solid var(--gray2);
      box-shadow:var(--shadow-card);
    }
    .bcard.blue{background:#EFF6FF;border-color:#93C5FD;}
    .bcard.green{background:#F0FDF4;border-color:#86EFAC;}
    .bcard.amber{background:#FFFBEB;border-color:#FCD34D;}
    .bcard.purple{background:#F5F3FF;border-color:#C4B5FD;}
    .bcard.primary{background:var(--primary);color:white;border-color:var(--primary);}
    .bcard.dark{background:var(--black);color:white;border-color:var(--black);}
    .bcard .bcard-icon{font-size:24px;margin-bottom:var(--s2);}
    .bcard .bcard-label{
      font-size:11px;font-weight:600;color:var(--gray5);
      text-transform:uppercase;letter-spacing:.04em;margin-bottom:var(--s1);
    }
    .bcard.primary .bcard-label,.bcard.dark .bcard-label{color:rgba(255,255,255,.6);}
    .bcard .bcard-value{font-size:14px;font-weight:700;color:var(--black);line-height:1.4;}
    .bcard.primary .bcard-value,.bcard.dark .bcard-value{color:white;}
    .bcard .bcard-value.xl{font-size:24px;letter-spacing:-0.03em;}
    .bcard .bcard-value.lg{font-size:18px;}
    .bcard .bcard-sub{font-size:11px;color:var(--gray5);margin-top:4px;line-height:1.4;}
    .bcard ul{padding-left:16px;margin-top:var(--s2);}
    .bcard li{font-size:12px;color:var(--gray7);margin:4px 0;line-height:1.5;}

    /* ── 칩 ──────────────────────────────────────── */
    .chips{display:flex;flex-wrap:wrap;gap:6px;}
    .chip{display:inline-flex;align-items:center;padding:3px 10px;border-radius:100px;font-size:11px;font-weight:600;}
    .chip.blue{background:#DBEAFE;color:#1D4ED8;}
    .chip.green{background:#DCFCE7;color:#15803D;}
    .chip.amber{background:#FEF3C7;color:#B45309;}
    .chip.gray{background:var(--gray2);color:var(--gray7);}
    .chip.red{background:#FEE2E2;color:#DC2626;}
    .chip.purple{background:#EDE9FE;color:#6D28D9;}

    /* ── 하이라이트 박스 ─────────────────────────── */
    .hl-box{border-radius:var(--radius-md);padding:var(--s4);}
    .hl-box.amber{background:linear-gradient(135deg,#FFFBEB,#FEF3C7);border-left:4px solid #F59E0B;}
    .hl-box.blue{background:linear-gradient(135deg,#EFF6FF,#DBEAFE);border-left:4px solid #3B82F6;}
    .hl-box.green{background:linear-gradient(135deg,#F0FDF4,#DCFCE7);border-left:4px solid #22C55E;}
    .hl-box.red{background:linear-gradient(135deg,#FFF1F2,#FFE4E6);border-left:4px solid #F43F5E;}
    .hl-box .hl-label{font-size:11px;font-weight:700;letter-spacing:.05em;margin-bottom:var(--s2);}
    .hl-box.amber .hl-label{color:#B45309;}
    .hl-box.blue .hl-label{color:#1D4ED8;}
    .hl-box.green .hl-label{color:#15803D;}
    .hl-box.red .hl-label{color:#BE123C;}
    .hl-box .hl-text{font-size:13px;color:var(--gray9);line-height:1.7;}

    /* ── 경쟁사 테이블 ───────────────────────────── */
    table.comp-table{
      width:100%;border-collapse:collapse;font-size:12px;margin:var(--s3) 0;
      page-break-inside:avoid;break-inside:avoid;
    }
    table.comp-table thead{display:table-header-group;}
    table.comp-table th{
      background:var(--black);color:white;
      padding:var(--s2) var(--s3);text-align:left;
      font-size:11px;font-weight:600;white-space:nowrap;
    }
    table.comp-table td{
      padding:var(--s2) var(--s3);border-bottom:1px solid var(--gray2);
      vertical-align:top;font-size:12px;color:var(--gray9);
    }
    table.comp-table tbody tr:nth-child(odd) td{background:#FAFBFC;}
    .cbadge{display:inline-block;padding:2px 8px;border-radius:6px;font-size:11px;font-weight:500;}
    .cbadge.up{background:#DCFCE7;color:#15803D;}
    .cbadge.down{background:#FEE2E2;color:#DC2626;}

    /* ── 일반 proposal 테이블 ────────────────────── */
    table.proposal-table{
      width:100%;border-collapse:collapse;font-size:13px;margin:var(--s3) 0;
      border-radius:var(--radius-md);overflow:hidden;box-shadow:var(--shadow-sm);
      page-break-inside:avoid;break-inside:avoid;
    }
    table.proposal-table thead{display:table-header-group;}
    table.proposal-table th{background:#0D1B2A;color:var(--white);padding:var(--s3) var(--s4);text-align:left;font-weight:600;font-size:12px;}
    table.proposal-table td{padding:var(--s3) var(--s4);border-bottom:1px solid var(--gray2);color:var(--gray9);}
    table.proposal-table tbody tr:last-child td{border-bottom:none;}
    table.proposal-table tbody tr:nth-child(even) td{background:#FAFBFC;}

    /* ── 타임라인 ────────────────────────────────── */
    .timeline-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s3);margin-top:var(--s4);}
    .tl-phase{background:var(--white);border-radius:var(--radius-md);padding:var(--s4);border-top:4px solid #0B7285;box-shadow:var(--shadow-card);}
    .tl-phase.m2{border-top-color:#0D1B2A;}
    .tl-phase.m3{border-top-color:#C8920A;}
    .tl-label{font-size:11px;font-weight:700;color:#0B7285;margin-bottom:var(--s2);text-transform:uppercase;letter-spacing:.05em;}
    .tl-label.m2{color:#0D1B2A;}
    .tl-label.m3{color:#C8920A;}
    .tl-phase ul{padding-left:16px;}
    .tl-phase li{font-size:12px;color:var(--gray7);margin:4px 0;line-height:1.5;}

    /* ── KPI 카드 ────────────────────────────────── */
    .kpi-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--s3);margin-top:var(--s3);}
    .kpi-card{
      background:white;border:1px solid var(--gray2);
      border-radius:var(--radius-md);padding:var(--s4);
      text-align:center;box-shadow:var(--shadow-sm);border-top:3px solid #0B7285;
    }
    .kpi-card .kv{font-size:28px;font-weight:800;color:#0D1B2A;letter-spacing:-0.03em;line-height:1.1;}
    .kpi-card .kl{font-size:11px;color:var(--gray5);margin-top:6px;}
    .kpi-card .kp{font-size:12px;color:var(--success);font-weight:600;margin-top:4px;}

    /* ── 채널 카드 ───────────────────────────────── */
    .channel-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3);margin-top:var(--s3);}
    .channel-card{background:white;border:1px solid var(--gray2);border-radius:var(--radius-md);padding:var(--s4);box-shadow:var(--shadow-sm);border-left:4px solid #0B7285;}
    .channel-card .ch-name{font-size:15px;font-weight:700;color:#0D1B2A;margin-bottom:var(--s2);padding-bottom:var(--s2);border-bottom:1px solid var(--gray2);}
    .channel-card .ch-meta{display:flex;flex-wrap:wrap;gap:6px;margin:var(--s2) 0;}
    .channel-card .ch-body{font-size:12px;color:var(--gray7);line-height:1.6;}
    .channel-card .ch-kpi{font-size:11px;color:var(--primary);font-weight:600;margin-top:var(--s2);}

    /* ── 현황 진단 ───────────────────────────────── */
    .diagnosis-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--s2);margin-top:var(--s3);}
    .diag-card{
      background:#FFF1F2;border-radius:var(--radius-md);
      padding:var(--s3) var(--s4);border-left:4px solid #F43F5E;
      display:flex;align-items:flex-start;gap:var(--s3);
    }
    .diag-card .diag-icon{font-size:20px;flex-shrink:0;}
    .diag-card .diag-title{font-size:13px;font-weight:700;color:var(--black);margin-bottom:4px;}
    .diag-card .diag-text{font-size:12px;color:var(--gray7);line-height:1.5;}

    /* ── 기회 카드 ───────────────────────────────── */
    .opportunity-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--s3);margin-top:var(--s3);}
    .opp-card{border-radius:var(--radius-md);padding:var(--s4);background:linear-gradient(135deg,#EAF6F8,#E8F3FF);border:1px solid #93C5FD;border-left:4px solid #0B7285;}
    .opp-card .opp-icon{font-size:24px;margin-bottom:var(--s2);}
    .opp-card .opp-title{font-size:13px;font-weight:700;color:#0D1B2A;margin-bottom:var(--s2);}
    .opp-card .opp-text{font-size:12px;color:var(--gray7);line-height:1.5;}

    /* ── 타이포 ──────────────────────────────────── */
    .page-section h2{font-size:18px;font-weight:700;color:#0D1B2A;margin:var(--s4) 0 var(--s2);}
    .page-section h3{font-size:15px;font-weight:600;color:#0B7285;margin:var(--s3) 0 var(--s2);}
    .page-section ul{margin:var(--s2) 0;padding-left:var(--s4);}
    .page-section li{margin:var(--s1) 0;color:var(--gray9);}
    .page-section p{margin:var(--s2) 0;color:var(--gray9);font-size:14px;}

    /* ── 소개 박스 ───────────────────────────────── */
    .about-box{
      background:linear-gradient(135deg,#0D1B2A 0%,#1B3358 100%);
      border-radius:var(--radius-lg);
      padding:var(--s5);margin-top:var(--s4);box-shadow:var(--shadow-md);color:var(--white);
    }
    .about-box a{color:#C8920A;font-weight:600;text-decoration:none;}
    .about-box p{margin:var(--s2) 0;color:rgba(255,255,255,.85);}
    .about-box strong{color:#C8920A;}
    """


# ─── 섹션 렌더러 맵 ──────────────────────────────────────────────────────────

SECTION_RENDERERS = {
    "market": _render_market_bento,
    "competitor": _render_competitor_visual,
    "current": _render_current_diagnosis,
    "opportunity": _render_opportunity,
    "solution": _render_solution,
    "channel": _render_channel_cards,
    "roadmap": _render_roadmap_timeline,
    "kpi": _render_kpi_cards,
    "offer": _render_offer,
    "case": _render_case_study,
    "next": _render_next_steps,
}


# ─── HTML 빌더 ────────────────────────────────────────────────────────────────

def build_html(company_name: str, proposal_md: str) -> str:
    sections = parse_sections(proposal_md)
    exec_text = sections.get("executive", "")
    exec_data, proof = parse_exec_bullets(exec_text)

    chunks: list[str] = []

    # ── 총 페이지 수 산출 (넘버링용) ──────────────────────────────────────────
    page_keys = ["cover", "executive"]
    for key in DETAIL_ORDER:
        if sections.get(key, "").strip():
            page_keys.append(key)
    skip_set = {"executive", *DETAIL_ORDER, "landing", "positioning"}
    for key in sections:
        if key not in skip_set and sections[key].strip():
            page_keys.append(key)
    page_keys.append("about")
    total_pages = len(page_keys)

    def _footer(page_num: int) -> str:
        return (
            f'<div class="page-footer">'
            f'<span class="pf-brand">{_esc(BRAND["name"])}  ·  {_esc(BRAND["phone"])}  ·  {_esc(BRAND["email"])}</span>'
            f'<span class="pf-num">{page_num:02d} <span class="pf-total">/ {total_pages:02d}</span></span>'
            f'</div>'
        )

    # ── 커버 ─────────────────────────────────────────────────────────────────
    stats: list[tuple[str, str]] = []
    if exec_data:
        e = exec_data[0]
        if e.get("budget_4w"):
            stats.append(("4주 테스트 예산", e["budget_4w"]))
        if e.get("channels"):
            stats.append(("추천 채널", e["channels"]))
        if e.get("monthly_cost"):
            stats.append(("월 유지비", e["monthly_cost"]))
    stat_cards = "".join(f"""
        <div class="stat-card">
          <div class="label">{_esc(lbl)}</div>
          <div class="value">{_esc(str(val)[:30])}</div>
        </div>""" for lbl, val in stats[:3])

    chunks.append(f"""
    <section class="page-section cover">
      <div class="cover-inner">
        <div class="brand">{_esc(BRAND["name"])}</div>
        <div class="company">{_esc(company_name)}</div>
        <div class="subtitle">마케팅 성장 제안서</div>
        <div class="meta">{_esc(TODAY)}  ·  Prepared by {_esc(BRAND["name"])}</div>
        <div class="stat-row">{stat_cards}</div>
      </div>
      <div class="footer-bar">
        <span>{_esc(BRAND["name"])}  ·  {_esc(BRAND["phone"])}  ·  {_esc(BRAND["email"])}</span>
        <a href="{_esc(BRAND['url'])}">{_esc(BRAND["website"])}</a>
      </div>
    </section>""")

    page_num = 2

    # ── 실행 요약 ─────────────────────────────────────────────────────────────
    chunks.append('<section class="page-section">')
    chunks.append('<div class="section-badge"><span class="section-num">01</span></div>')
    chunks.append('<h1 class="section-heading">실행 요약</h1>')
    chunks.append('<div class="section-content">')
    chunks.append('<div class="exec-wrap">')
    if exec_data:
        for entry in exec_data:
            fields = [
                ("현황", entry.get("current_state")),
                ("제안 내용", entry.get("proposal")),
                ("추천 채널", entry.get("channels")),
                ("4주 예산", entry.get("budget_4w")),
                ("월 유지비", entry.get("monthly_cost")),
                ("다음 단계", entry.get("cta")),
            ]
            for lbl, val in fields:
                if not val:
                    continue
                css_val = "value cta" if lbl == "다음 단계" else "value"
                chunks.append(f'<div class="exec-grid"><div class="label">{_esc(lbl)}</div><div class="{css_val}">{_esc(str(val))}</div></div>')
    else:
        chunks.append(_md_to_html(exec_text[:2000]))
    chunks.append("</div>")

    if proof.strip():
        chunks.append(f'<div class="proof-box"><div class="tag">✅ 적용 사례 / 근거</div><div style="font-size:13px;color:var(--gray9);margin-top:4px;">{_esc(proof)}</div></div>')
    chunks.append("</div>")  # section-content
    chunks.append(_footer(page_num))
    chunks.append("</section>")
    page_num += 1

    # ── 상세 섹션 ─────────────────────────────────────────────────────────────
    sec_nums = {
        "market": "02", "competitor": "03", "current": "04", "opportunity": "05",
        "solution": "06", "channel": "07", "roadmap": "08", "kpi": "09",
        "offer": "10", "case": "11", "next": "12",
    }

    for key in DETAIL_ORDER:
        content = sections.get(key, "").strip()
        if not content:
            continue
        label = SECTION_LABEL.get(key, key.replace("other:", ""))
        num = sec_nums.get(key, "—")

        renderer = SECTION_RENDERERS.get(key, _md_to_html)
        rendered = renderer(content)

        chunks.append('<section class="page-section">')
        chunks.append(f'<div class="section-badge"><span class="section-num">{num}</span></div>')
        chunks.append(f'<h1 class="section-heading">{_esc(label)}</h1>')
        chunks.append(f'<div class="section-content">{rendered}</div>')
        chunks.append(_footer(page_num))
        chunks.append("</section>")
        page_num += 1

    # 기타 섹션 (other:xxx)
    for key, content in sections.items():
        if key in skip_set or not content.strip():
            continue
        label = key.replace("other:", "")
        chunks.append('<section class="page-section">')
        chunks.append(f'<h1 class="section-heading">{_esc(label)}</h1>')
        chunks.append(f'<div class="section-content">{_md_to_html(content)}</div>')
        chunks.append(_footer(page_num))
        chunks.append("</section>")
        page_num += 1

    # ── 소개 ──────────────────────────────────────────────────────────────────
    chunks.append(f"""
    <section class="page-section">
      <div class="section-badge"><span class="section-num">★</span></div>
      <h1 class="section-heading">Onecation 소개</h1>
      <div class="section-content">
        <div class="about-box">
          <p><a href="{_esc(BRAND['url'])}">🌐 {_esc(BRAND['website'])}</a></p>
          <p><strong>회사명</strong>  {_esc(BRAND['name'])}</p>
          <p><strong>연락처</strong>  {_esc(BRAND['phone'])}  |  <strong>이메일</strong>  {_esc(BRAND['email'])}</p>
          <p><strong>제안 유효기간</strong>  {_esc(TODAY)} 기준 2주</p>
        </div>
      </div>
      {_footer(page_num)}
    </section>""")

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(company_name)} 마케팅 성장 제안서</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{_get_css()}</style>
</head>
<body>
{chr(10).join(chunks)}
</body>
</html>"""
    return html


# ─── Playwright PDF 변환 ──────────────────────────────────────────────────────

def html_to_pdf(html: str, output_path: Path) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[오류] playwright가 필요합니다. 실행: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(output_path),
            width="13.33in",
            height="7.5in",
            margin={"top": "0.5in", "right": "0.5in", "bottom": "0.5in", "left": "0.5in"},
            print_background=True,
        )
        browser.close()
    size_kb = output_path.stat().st_size // 1024
    print(f"  [OK] {output_path.name}  ({size_kb} KB)")


# ─── 진입점 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Sales Factory → 제안서 PDF (Playwright)")
    parser.add_argument("--proposal", default=str(BASE_DIR / "proposal.md"))
    parser.add_argument("--company", default=None)
    parser.add_argument("--out", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    proposal_path = Path(args.proposal)
    if not proposal_path.exists():
        print(f"[오류] 파일 없음: {proposal_path}")
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    proposal_text = proposal_path.read_text(encoding="utf-8")
    companies = parse_companies(proposal_text)

    expected_n = None
    m = re.search(r"대상\s*회사\s*수\s*:\s*(\d+)", proposal_text, re.IGNORECASE)
    if m:
        expected_n = int(m.group(1))
    if expected_n is not None and len(companies) != expected_n:
        print(f"[안내] proposal.md에는 '대상 회사 수: {expected_n}'인데, # 회사명 (H1) 블록은 {len(companies)}개입니다.\n")

    if args.company:
        companies = {k: v for k, v in companies.items() if args.company in k or k in args.company}
        if not companies:
            print(f"[오류] '{args.company}' 없음")
            sys.exit(1)

    print("\n[Sales Factory PDF Generator — Playwright]")
    print(f"  회사: {len(companies)}개  →  {out_dir}\n")

    for company_name, proposal_md in companies.items():
        display = company_name if company_name != "default" else "제안서"
        safe = re.sub(r'[\\/*?:"<>|]', "_", display)
        base_name = f"{safe}_제안서_{TODAY_FILE}_playwright"
        out = out_dir / f"{base_name}.pdf"
        try:
            html = build_html(display, proposal_md)
            try:
                html_to_pdf(html, out)
            except PermissionError:
                for n in range(1, 10):
                    alt = out_dir / f"{base_name}_{n}.pdf"
                    try:
                        html_to_pdf(html, alt)
                        break
                    except PermissionError:
                        continue
                else:
                    print(f"  [실패] {display}: PDF 파일을 닫은 뒤 다시 실행하세요.")
        except Exception as e:
            print(f"  [실패] {display}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n완료 → {out_dir}")


if __name__ == "__main__":
    main()
