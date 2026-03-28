from __future__ import annotations

from copy import deepcopy
from typing import Any


COUNTRY_PATTERN_LIBRARY: dict[str, list[dict[str, Any]]] = {
    "KR": [
        {
            "pattern_name": "웹 신뢰가 약한 수출형 제조/패키지 업체",
            "target_industries": ["제조", "패키지", "인쇄", "산업자재"],
            "company_traits": "오프라인 실적은 있으나 웹 표현이 약하고 문의 동선이 낡은 owner-led 중소기업",
            "digital_pain_signals": "오래된 회사 소개, 신뢰 페이지 부재, 제품/포트폴리오 표현 약함",
            "why_we_can_win": "신뢰형 홈페이지 리뉴얼, 제안서형 영업 자료, 유지보수 리테이너까지 연결하기 쉽다.",
            "offer_fit": "relaunch_offer + managed_website_ops",
            "suggested_query": "서울 및 경기의 제조, 패키지, 인쇄 업체 중 웹사이트가 오래됐거나 신뢰 표현이 약한 회사",
            "priority_score": 92,
            "strategic_bias": "general_digital_recovery",
        },
        {
            "pattern_name": "설명형 전문 서비스업",
            "target_industries": ["법무", "회계", "교육", "클리닉", "컨설팅"],
            "company_traits": "설명과 신뢰가 중요한데 웹에서 차별점이 잘 안 보이는 전문 서비스 사업자",
            "digital_pain_signals": "서비스 소개 구조 약함, CTA 약함, 검색은 되지만 전환 흐름이 약함",
            "why_we_can_win": "콘텐츠 구조, 신뢰 요소, 문의 흐름을 다시 설계해 바로 체감되는 개선을 만들 수 있다.",
            "offer_fit": "relaunch_offer + growth_execution_plan",
            "suggested_query": "서울의 법무, 회계, 교육, 클리닉 중 웹사이트가 낡았거나 설명 구조가 약한 업체",
            "priority_score": 87,
            "strategic_bias": "trust_gap_services",
        },
        {
            "pattern_name": "자사 사이트 없이 외부 채널에만 의존하는 업체",
            "target_industries": ["로컬 서비스", "유통", "브랜드"],
            "company_traits": "네이버, 지도, SNS, 디렉토리에는 흔적이 있으나 자사 소유 사이트가 없거나 약한 업체",
            "digital_pain_signals": "owned media 부재, 브랜드 신뢰 자산 약함, 검색 후 이탈 가능성 높음",
            "why_we_can_win": "신규 사이트 + 로컬 검색 + 운영 대행 오퍼가 명확하게 맞는다.",
            "offer_fit": "new_presence_offer + growth_execution_plan",
            "suggested_query": "서울 업체 중 외부 플랫폼 정보는 있으나 자사 홈페이지가 없거나 매우 약한 회사",
            "priority_score": 79,
            "strategic_bias": "new_presence_build",
        },
    ],
    "US": [
        {
            "pattern_name": "오래된 웹사이트를 가진 owner-led B2B 산업 업체",
            "target_industries": ["printing", "packaging", "industrial services", "suppliers"],
            "company_traits": "5-50인 규모, 오너 주도, 오프라인 실적은 있으나 웹 신뢰가 약한 B2B 회사",
            "digital_pain_signals": "stale design, weak inquiry flow, low trust presentation, outdated copy",
            "why_we_can_win": "리뉴얼 가치가 선명하고, 사이트 개선 이후 유지보수/콘텐츠/영업 보조까지 자연스럽게 연결된다.",
            "offer_fit": "relaunch_offer + managed_website_ops",
            "suggested_query": "California owner-led printing, packaging, or industrial companies with outdated websites",
            "priority_score": 94,
            "strategic_bias": "general_digital_recovery",
        },
        {
            "pattern_name": "신뢰 표현이 약한 전문 서비스업",
            "target_industries": ["law", "accounting", "education", "medical", "consulting"],
            "company_traits": "고객은 신뢰를 보고 결정하는데 웹에서 전문성과 차별점이 충분히 드러나지 않는 회사",
            "digital_pain_signals": "weak positioning, unclear proof, generic copy, poor CTA structure",
            "why_we_can_win": "시니어 세일즈형 제안서와 설명 구조 개선이 바로 먹히는 업종이다.",
            "offer_fit": "relaunch_offer + growth_execution_plan",
            "suggested_query": "California professional service firms with stale websites or weak trust presentation",
            "priority_score": 89,
            "strategic_bias": "trust_gap_services",
        },
        {
            "pattern_name": "한국 진출 가능성이 보이는 해외 기업",
            "target_industries": ["consumer brands", "ecommerce", "education", "services"],
            "company_traits": "아시아 확장 흔적이 있고 한국 맞춤 사이트/마케팅이 약한 회사",
            "digital_pain_signals": "no Korea page, weak localization, generic Asia messaging, no local execution plan",
            "why_we_can_win": "Onecation의 차별점이 가장 선명하게 드러나는 세그먼트다.",
            "offer_fit": "korea_entry_offer + growth_execution_plan",
            "suggested_query": "US companies expanding into Asia or Korea with weak localization websites",
            "priority_score": 83,
            "strategic_bias": "korea_entry_specialist",
        },
    ],
    "JP": [
        {
            "pattern_name": "신뢰형 웹사이트가 중요한 제조/패키지/산업 서비스",
            "target_industries": ["printing", "packaging", "manufacturing", "industrial services"],
            "company_traits": "정중하고 안정적인 신뢰 표현이 필요한 중소기업, 웹 관리 공백이 있는 회사",
            "digital_pain_signals": "stale corporate site, weak proof structure, missing updates, inconsistent information",
            "why_we_can_win": "정돈된 구조와 유지관리 제안이 강하게 먹히는 시장이다.",
            "offer_fit": "maintenance_recovery_offer + managed_website_ops",
            "suggested_query": "Tokyo printing, packaging, and manufacturing companies with stale or inconsistent websites",
            "priority_score": 92,
            "strategic_bias": "maintenance_recovery",
        },
        {
            "pattern_name": "설명력과 품질관리가 필요한 전문 서비스업",
            "target_industries": ["education", "consulting", "clinics", "professional services"],
            "company_traits": "직접적인 과장보다 신뢰, 품질, 운영 안정성을 중시하는 서비스업",
            "digital_pain_signals": "unclear service explanation, old information, weak credibility blocks",
            "why_we_can_win": "공손한 톤과 구조화된 제안서, 장기 운영형 오퍼가 맞는다.",
            "offer_fit": "relaunch_offer + growth_execution_plan",
            "suggested_query": "Tokyo professional service firms with outdated websites and weak trust structure",
            "priority_score": 84,
            "strategic_bias": "trust_gap_services",
        },
        {
            "pattern_name": "해외 확장 맥락이 있는 일본 기업",
            "target_industries": ["brands", "education", "B2B services"],
            "company_traits": "영문/다국어 대응은 하지만 웹 현지화와 확장 메시지가 약한 기업",
            "digital_pain_signals": "generic English site, weak market-entry messaging, low conversion structure",
            "why_we_can_win": "다국어 웹과 실행안 제안이 결합되면 설득 포인트가 커진다.",
            "offer_fit": "cross_border_growth_offer",
            "suggested_query": "Japanese companies with English sites but weak international growth messaging",
            "priority_score": 77,
            "strategic_bias": "cross_border_growth",
        },
    ],
    "TW": [
        {
            "pattern_name": "수출형 패키지/브랜드 기업",
            "target_industries": ["packaging", "consumer brands", "manufacturing", "ecommerce"],
            "company_traits": "제품 경쟁력은 있으나 다국어 신뢰 페이지와 시장별 메시지가 약한 회사",
            "digital_pain_signals": "weak international copy, old site design, unclear inquiry path",
            "why_we_can_win": "브랜드/제품 강점을 웹 구조로 재번역하는 제안이 잘 맞는다.",
            "offer_fit": "relaunch_offer + cross_border_growth_offer",
            "suggested_query": "Taipei packaging, manufacturing, or brand companies with weak multilingual websites",
            "priority_score": 88,
            "strategic_bias": "cross_border_growth",
        },
        {
            "pattern_name": "한국/일본 시장 진출 가능 기업",
            "target_industries": ["consumer brands", "ecommerce", "services"],
            "company_traits": "북아시아 확장 여지가 있으나 현지화 사이트/메시지 부재",
            "digital_pain_signals": "generic export messaging, no Korea/Japan localization, weak trust content",
            "why_we_can_win": "Onecation의 국가 적응형 실행안이 차별점으로 작동한다.",
            "offer_fit": "korea_entry_offer + growth_execution_plan",
            "suggested_query": "Taiwan companies likely to expand into Korea or Japan with weak localization websites",
            "priority_score": 82,
            "strategic_bias": "korea_entry_specialist",
        },
    ],
    "SG": [
        {
            "pattern_name": "B2B 서비스/트레이딩 회사의 신뢰 갭",
            "target_industries": ["B2B services", "trading", "consulting", "industrial supply"],
            "company_traits": "영문 사이트는 있으나 전환 구조와 신뢰 메시지가 약한 중소기업",
            "digital_pain_signals": "generic messaging, weak proof, poor CTA, old case study structure",
            "why_we_can_win": "간결한 영문 제안서와 신뢰형 사이트 구조 개선이 잘 맞는다.",
            "offer_fit": "relaunch_offer + growth_execution_plan",
            "suggested_query": "Singapore B2B service or trading companies with weak trust presentation on their websites",
            "priority_score": 86,
            "strategic_bias": "trust_gap_services",
        },
        {
            "pattern_name": "다국적 진출 준비형 중소기업",
            "target_industries": ["services", "education", "brands", "technology-enabled SMBs"],
            "company_traits": "작은 팀이지만 여러 시장을 보고 있어 웹과 메시지 정리가 필요한 기업",
            "digital_pain_signals": "inconsistent market messaging, weak localization, shallow lead capture",
            "why_we_can_win": "웹 리뉴얼과 실행 계획을 함께 제안하면 차별화되기 쉽다.",
            "offer_fit": "cross_border_growth_offer",
            "suggested_query": "Singapore companies with weak international growth messaging and stale websites",
            "priority_score": 79,
            "strategic_bias": "cross_border_growth",
        },
    ],
    "CN": [
        {
            "pattern_name": "대외 신뢰용 영문 사이트가 약한 수출형 기업",
            "target_industries": ["manufacturing", "trading", "packaging", "industrial supply"],
            "company_traits": "국제 바이어 상대용 웹이 필요하지만 영문 사이트의 신뢰 구조가 약한 기업",
            "digital_pain_signals": "dated English site, weak proof, poor product explanation, stale updates",
            "why_we_can_win": "B2B 신뢰형 웹과 유지관리 오퍼가 명확하게 맞는다.",
            "offer_fit": "relaunch_offer + managed_website_ops",
            "suggested_query": "Shanghai manufacturing and trading companies with weak English websites",
            "priority_score": 85,
            "strategic_bias": "cross_border_growth",
        },
        {
            "pattern_name": "한국 시장 진출 잠재 기업",
            "target_industries": ["consumer brands", "cross-border ecommerce", "education", "services"],
            "company_traits": "한국 시장에 관심이 있을 수 있으나 현지화 준비가 약한 기업",
            "digital_pain_signals": "no Korea-specific messaging, weak localized trust, shallow owned media",
            "why_we_can_win": "한국 시장 적응형 제안이 강점으로 작동할 수 있다.",
            "offer_fit": "korea_entry_offer + growth_execution_plan",
            "suggested_query": "Chinese companies entering Korea with weak localization websites",
            "priority_score": 78,
            "strategic_bias": "korea_entry_specialist",
        },
    ],
    "AE": [
        {
            "pattern_name": "신뢰형 기업 사이트가 약한 서비스/산업 중소기업",
            "target_industries": ["industrial services", "professional services", "B2B suppliers", "trading"],
            "company_traits": "영문 사이트는 있으나 high-trust corporate feel과 inquiry flow가 약한 회사",
            "digital_pain_signals": "thin copy, weak proof, old site, poor corporate credibility blocks",
            "why_we_can_win": "기업 신뢰 구조, 다국어 대비, 실행안 제안이 잘 맞는다.",
            "offer_fit": "relaunch_offer + managed_website_ops",
            "suggested_query": "Dubai B2B service, industrial, or trading companies with weak corporate websites",
            "priority_score": 84,
            "strategic_bias": "general_digital_recovery",
        },
        {
            "pattern_name": "다국적 고객 대응이 필요한 성장 기업",
            "target_industries": ["services", "education", "trading", "specialized SMBs"],
            "company_traits": "국제 고객을 상대하지만 웹 메시지와 운영 구조가 약한 기업",
            "digital_pain_signals": "generic positioning, weak multilingual structure, unclear inquiry path",
            "why_we_can_win": "다국어 웹/제안서/실행 계획을 동시에 제안할 수 있다.",
            "offer_fit": "cross_border_growth_offer",
            "suggested_query": "Dubai companies serving international clients with stale websites and weak multilingual messaging",
            "priority_score": 77,
            "strategic_bias": "cross_border_growth",
        },
    ],
}


def _copy_patterns(target_country: str) -> list[dict[str, Any]]:
    return deepcopy(COUNTRY_PATTERN_LIBRARY.get(target_country, []))


def build_strategy_snapshot(
    *,
    target_country: str,
    lead_mode: str,
    lead_query: str,
) -> dict[str, Any]:
    patterns = _copy_patterns(target_country)
    auto_mode = lead_mode == "region_or_industry" and not (lead_query or "").strip()
    selected_patterns = sorted(patterns, key=lambda item: item.get("priority_score", 0), reverse=True)[:2]
    resolved_query = (lead_query or "").strip()
    if auto_mode and selected_patterns:
        resolved_query = selected_patterns[0]["suggested_query"]

    strategy_bias = selected_patterns[0]["strategic_bias"] if selected_patterns else "general_digital_recovery"
    recommended_focus = [pattern["pattern_name"] for pattern in selected_patterns]
    avoided_patterns = [pattern["pattern_name"] for pattern in patterns[2:]]

    return {
        "auto_mode": auto_mode,
        "requested_query": (lead_query or "").strip(),
        "resolved_query": resolved_query,
        "patterns": patterns,
        "selected_patterns": selected_patterns,
        "strategy_bias": strategy_bias,
        "recommended_focus": recommended_focus,
        "avoided_patterns": avoided_patterns,
    }
