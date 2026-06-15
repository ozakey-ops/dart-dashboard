"""
상수 및 공통 설정 — ACC, COLORS, PLOTLY_LAYOUT, TTL, DART_KEY
"""
import os
from datetime import datetime
from typing import Any

import streamlit as st

# ── DART API 키 ──
try:
    DART_KEY: str = st.secrets.get("DART_KEY", os.environ.get("DART_KEY", ""))
except Exception:
    DART_KEY = os.environ.get("DART_KEY", "")

BASE          = "https://opendart.fss.or.kr/api"
_LATEST_YEAR  = datetime.now().year - 1
YEARS         = list(range(_LATEST_YEAR - 14, _LATEST_YEAR + 1))

# ── 캐시 TTL (초) ──
TTL_REALTIME = 300
TTL_SHORT    = 1800
TTL_MEDIUM   = 3600
TTL_LONG     = 86400
TTL_WEEKLY   = 604800

_CACHE_VER = 21

# ── 계정과목 키워드 매핑 ──
ACC: dict[str, list[str]] = {
    "assets":      ["자산총계"],
    "liabilities": ["부채총계"],
    "equity":      ["자본총계", "자본합계"],
    "revenue": [
        "매출액", "수익(매출액)", "영업수익", "매출", "총수익",
        "영업수익합계", "순영업수익", "이자수익", "순이자이익",
        "보험료수익", "보험영업수익", "수입보험료",
        "순수수료수익", "수수료수익",
    ],
    "opIncome":         ["영업이익", "영업이익(손실)", "영업손익"],
    "netIncome":        ["당기순이익", "당기순이익(손실)", "당기순손익"],
    "retainedEarnings": ["이익잉여금(결손금)", "이익잉여금", "결손금",
                         "미처분이익잉여금", "미처리결손금"],
    "opCF":             ["영업활동으로 인한 현금흐름", "영업활동현금흐름"],
    "invCF":            ["투자활동으로 인한 현금흐름", "투자활동현금흐름"],
    "finCF":            ["재무활동으로 인한 현금흐름", "재무활동현금흐름"],
    "endCash":          ["기말현금및현금성자산", "기말의현금및현금성자산",
                         "현금및현금성자산의기말잔액", "기말현금및현금성자산잔액"],
    "depreciationDA":   ["유형자산감가상각비", "감가상각비"],
    "amortizationIA":   ["무형자산상각비", "무형자산의상각", "무형자산상각액",
                         "사용권자산감가상각비", "사용권자산의감가상각비"],
}

COLORS: dict[str, str] = {
    "blue":   "#2563eb",
    "red":    "#dc2626",
    "green":  "#16a34a",
    "orange": "#ea580c",
    "purple": "#7c3aed",
}

PLOTLY_LAYOUT: dict[str, Any] = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(248,250,252,1)",
    font=dict(color="#64748b", size=11),
    xaxis=dict(gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
    yaxis=dict(gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#1e293b", size=11)),
    margin=dict(l=10, r=10, t=30, b=10),
    height=280,
)

# 공시 연도·보고서 코드 후보 (최근 5년 사업보고서 + 반기보고서)
_REPRT_CANDIDATES = (
    [(y, "11011") for y in range(datetime.now().year - 1, datetime.now().year - 6, -1)] +
    [(y, "11012") for y in range(datetime.now().year - 1, datetime.now().year - 4, -1)]
)
