"""
기업 주식 시황 및 재무 대시보드 — Streamlit 모바일 웹앱
============================================
설치:  pip install streamlit plotly requests yfinance pandas
실행:  streamlit run streamlit_app.py
배포:  share.streamlit.io (무료)
"""
# ══════════════════════════════════════════
#  표준 라이브러리 imports
# ══════════════════════════════════════════
import io
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
# ══════════════════════════════════════════
#  서드파티 imports
# ══════════════════════════════════════════
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots
try:
    import yfinance as yf
    import pandas as pd
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False
# ══════════════════════════════════════════
#  설정 상수
# ══════════════════════════════════════════
def _dk() -> str:
    import base64
    _e = b"OTAxZGU3N2RhMDU5Yjg1ZTA5NWE5OWFiOWYyYmFmMzI2NGY3MjgxZg=="
    return base64.b64decode(_e).decode()
try:
    DART_KEY = st.secrets.get("DART_KEY", os.environ.get("DART_KEY", "")) or _dk()
except Exception:
    DART_KEY = os.environ.get("DART_KEY", "") or _dk()
BASE         = "https://opendart.fss.or.kr/api"
_LATEST_YEAR = datetime.now().year - 1
YEARS        = list(range(_LATEST_YEAR - 14, _LATEST_YEAR + 1))
# 캐시 TTL 상수 (초)
TTL_REALTIME  = 300      # 5분  — 시장 데이터
TTL_SHORT     = 1800     # 30분 — 공시·뉴스·대량보유
TTL_MEDIUM    = 3600     # 1시간 — 재무·주가
TTL_LONG      = 86400    # 1일  — 기업 개요
TTL_WEEKLY    = 604800   # 7일  — 기업 목록
# 캐시 버전 — 변경 시 이전 캐시 전체 무효화
_CACHE_VER = 25
# 계정과목 키워드 매핑
ACC: dict[str, list[str]] = {
    "assets":      ["자산총계"],
    "liabilities": ["부채총계"],
    "equity":      ["자본총계", "자본합계"],
    "revenue": [
        # 일반 기업
        "매출액", "수익(매출액)", "영업수익", "매출", "총수익",
        # 은행·금융지주 (이자수익은 구성항목이므로 합계 계정을 우선)
        "영업수익합계", "순영업수익", "이자수익", "순이자이익",
        # 보험업
        "보험료수익", "보험영업수익", "수입보험료",
        # 증권·캐피탈
        "순수수료수익", "수수료수익",
    ],
    "opIncome": ["영업이익", "영업이익(손실)", "영업손익"],
    "netIncome":        ["당기순이익", "당기순이익(손실)", "당기순손익"],
    "retainedEarnings": ["이익잉여금(결손금)", "이익잉여금", "결손금",
                         "미처분이익잉여금", "미처리결손금"],
    "opCF":             ["영업활동으로 인한 현금흐름", "영업활동현금흐름"],
    "invCF":            ["투자활동으로 인한 현금흐름", "투자활동현금흐름"],
    "finCF":            ["재무활동으로 인한 현금흐름", "재무활동현금흐름"],
    "endCash":          ["기말현금및현금성자산", "기말의현금및현금성자산",
                         "현금및현금성자산의기말잔액", "기말현금및현금성자산잔액"],
    # EV 산정용 — 이자발생부채
    "shortDebt":        ["단기차입금", "단기차입금및유동성장기부채",
                         "유동성장기부채", "단기사채", "유동금융부채"],
    "longDebt":         ["장기차입금", "사채", "장기사채", "비유동금융부채",
                         "장기금융부채", "신종자본증권"],
    "cashEquiv":        ["현금및현금성자산", "현금및단기금융상품",
                         "현금및현금등가물"],
    # EBITDA 구성 요소 — 현금흐름표 영업활동 조정항목에서 추출
    # EBITDA = 영업이익(IS) + 감가상각비(D) + 무형자산상각비(A)
    "depreciation":     [
        # ── "~에 대한 조정" 형식 (DART CF 간접법 조정항목 — 구체적 표기 우선) ──
        "감가상각비에 대한 조정",
        "유형자산감가상각비에 대한 조정",
        "사용권자산감가상각비에 대한 조정",
        "유형자산및사용권자산감가상각비에 대한 조정",
        "투자부동산감가상각비에 대한 조정",
        # ── 직접 계정명 ──
        "감가상각비", "유형자산감가상각비", "사용권자산감가상각비",
        "유형자산및사용권자산감가상각비", "유형자산및사용권자산의감가상각비",
        "사용권자산의감가상각비",   # ROU자산 감가 → 유형자산 범주
        "유형자산의감가상각비", "유형자산상각비", "유형자산의상각비",
        "감가상각비(유형자산)", "투자부동산감가상각비",
        # ── 유·무형 통합 표기 ──
        "감가상각및상각비", "감가상각비및상각비",
        "유·무형자산상각비", "유무형자산상각비",
        # ── D+A 합산형 조정항목 (회사별로 단일 행으로 표기할 경우 폴백) ──
        # 이 경우 amortization은 None 반환 → EBITDA = opIncome + (D+A합산) + 0 으로 정확
        "감가상각비 및 무형자산상각비에 대한 조정",
        "감가상각및무형자산상각비에 대한 조정",
        "감가상각비및무형자산상각비에 대한 조정",
        "유형자산및무형자산상각비에 대한 조정",
        "감가상각비 및 상각비에 대한 조정",
        "감가상각비와 무형자산상각비에 대한 조정",
        "감가상각비등에 대한 조정",
    ],
    "amortization":     [
        # ── "~에 대한 조정" 형식 ──
        "무형자산상각비에 대한 조정",
        "무형자산의상각에 대한 조정",
        "사용권자산상각비에 대한 조정",
        "무형자산및사용권자산상각비에 대한 조정",
        "무형자산및사용권자산의상각비에 대한 조정",
        # ── 직접 계정명 (무형자산 한정) ──
        "무형자산상각비", "무형자산의상각비", "무형자산의상각", "무형자산상각",
        "개발비상각액", "개발비상각비", "개발비의상각",
        "사용권자산상각비",
    ],
}
COLORS = {
    "blue":   "#2563eb",
    "red":    "#dc2626",
    "green":  "#16a34a",
    "orange": "#ea580c",
    "purple": "#7c3aed",
}
# Plotly 공통 레이아웃 — render_stock_chart 보다 먼저 선언
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
# ─── 페이지 설정 ───
st.set_page_config(
    page_title="기업 주식 시황 및 재무 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown("""
<style>
  [data-testid="stHeader"]           { display:none !important; }
  [data-testid="stToolbar"]          { display:none !important; }
  #MainMenu                          { display:none !important; }
  footer                             { display:none !important; }
  [data-testid="stAppViewContainer"] { background:#f8fafc; color:#1e293b; }
  [data-testid="stSidebar"]          { background:#f1f5f9; }
  body                               { background:#f8fafc; }
  .block-container                   { padding-top:0 !important; padding-bottom:1rem; max-width:1200px; }
  .appview-container                 { padding-top:0 !important; }
  h1,h2,h3                           { color:#1e293b !important; }
  .stTextInput input                 { background:#fff; color:#1e293b; border:1px solid #cbd5e1; border-radius:8px; }
  .stTextInput input:focus           { border-color:#2563eb; box-shadow:0 0 0 2px rgba(37,99,235,.15); }
  .stButton button                   { background:#2563eb; color:#fff; border:none; border-radius:8px; width:100%; font-weight:600; }
  .stButton button:hover             { background:#1d4ed8; }
  .metric-card                       { background:#fff; border:1px solid #e2e8f0; border-radius:12px; padding:14px 16px; margin-bottom:8px; box-shadow:0 1px 3px rgba(0,0,0,.06); }
  .metric-label                      { font-size:.72rem; color:#64748b; margin-bottom:4px; }
  .metric-value                      { font-size:1.15rem; font-weight:700; color:#1e293b; }
  .metric-delta                      { font-size:.72rem; margin-top:3px; }
  .up   { color:#16a34a; }
  .down { color:#dc2626; }
  .flat { color:#64748b; }
  div[data-testid="stSelectbox"] > div { background:#fff; border:1px solid #cbd5e1; border-radius:8px; }
  .stDataFrame                        { border:1px solid #e2e8f0; border-radius:8px; background:#fff; }
  [data-testid="stTab"]              { color:#64748b; }
  [data-testid="stTab"][aria-selected="true"] { color:#2563eb; border-bottom-color:#2563eb; }
  .stCaption                         { color:#64748b; }
  div[data-baseweb="tab-highlight"]  { background:#2563eb !important; }
  @media (max-width: 768px) {
    .block-container { padding-left:0.5rem !important; padding-right:0.5rem !important; }
    .dart-title { font-size:.95rem !important; }
    [data-testid="stNumberInput"] input { min-width: 0 !important; font-size:.88rem !important; }
    .stDataFrame { overflow-x: auto !important; }
    [data-testid="stTab"] { font-size:.82rem !important; padding: 6px 8px !important; }
    .metric-card { padding:10px 12px !important; }
    .metric-value { font-size:1rem !important; }
  }
  @media (max-width: 480px) {
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      min-width: 45% !important;
      flex: 1 1 45% !important;
    }
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)) > [data-testid="stColumn"] {
      min-width: 100% !important;
      flex: none !important;
    }
  }
</style>
""", unsafe_allow_html=True)
# ══════════════════════════════════════════
#  유틸리티
# ══════════════════════════════════════════
def clean(s: str) -> str:
    return (s or "").replace(" ", "")
def parse_amt(item: dict) -> int | None:
    """당기 금액 파싱 — thstrm_amount → thstrm_add_amount 순으로 시도."""
    for field in ("thstrm_amount", "thstrm_add_amount"):
        raw = (item.get(field) or "").replace(",", "").strip()
        if raw and raw not in ("-", ""):
            try:
                return round(int(raw) / 1e8)
            except (ValueError, TypeError):
                continue
    return None
def find_amount(items: list[dict], keys: list[str]) -> int | None:
    """계정과목 검색: 완전일치 → 키워드⊂계정명 포함 검색.
    nm in kc 방향(역방향)은 단어가 짧은 계정명이 긴 키워드에 잘못 매칭되는 오류 유발 → 제거."""
    for key in keys:
        kc = clean(key)
        for item in items:
            if clean(item.get("account_nm", "")) == kc:
                v = parse_amt(item)
                if v is not None:
                    return v
    for key in keys:
        kc = clean(key)
        for item in items:
            nm = clean(item.get("account_nm", ""))
            if kc in nm:          # 키워드가 계정명 안에 포함될 때만 매칭
                v = parse_amt(item)
                if v is not None:
                    return v
    return None
def find_retained_earnings(bs_items: list[dict]) -> int | None:
    r = find_amount(bs_items, ACC["retainedEarnings"])
    if r is not None:
        return r
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "이익잉여금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "결손금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    return None
def find_end_cash(cf_items: list[dict]) -> int | None:
    r = find_amount(cf_items, ACC["endCash"])
    if r is not None:
        return r
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "기말" in nm and "현금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    candidates = []
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "현금및현금성자산" in nm:
            v = parse_amt(item)
            if v is not None:
                candidates.append(v)
    return candidates[-1] if candidates else None
def fmt(n: int | float | None) -> str:
    if n is None:
        return "-"
    return f"{int(n):,}"
def pct(a: int | None, b: int | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)
def _html_table(headers: list[str], rows_html: str, align: list[str] | None = None) -> str:
    """공통 HTML 테이블 렌더러 — 반복되는 테이블 마크업을 하나로 통합."""
    if align is None:
        align = ["left"] * len(headers)
    th_cells = "".join(
        f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;'
        f'text-align:{a};font-weight:600;">{h}</th>'
        for h, a in zip(headers, align)
    )
    return (
        f'<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;">'
        f'<table style="width:100%;border-collapse:collapse;">'
        f'<thead><tr style="background:#f1f5f9;">{th_cells}</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table></div>'
    )
def _section_header(title: str, sub: str = "") -> None:
    sub_html = (
        f'<span style="font-size:.68rem;font-weight:400;color:#94a3b8;margin-left:6px;">{sub}</span>'
    ) if sub else ""
    st.markdown(
        f'<div style="font-size:.78rem;font-weight:700;color:#1e293b;'
        f'margin:14px 0 6px;border-left:3px solid #2563eb;padding-left:8px;">'
        f'{title}{sub_html}</div>',
        unsafe_allow_html=True,
    )
# ══════════════════════════════════════════
#  DART API — 기업 목록
# ══════════════════════════════════════════
def _dart_get(path: str, params: dict, timeout: tuple = (10, 60)) -> requests.Response:
    """DART API GET 래퍼 — SSL/연결 오류 시 verify=False 재시도."""
    url = f"{BASE}/{path}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        return requests.get(url, params=params, headers=headers, timeout=timeout, verify=True)
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError):
        # Streamlit Cloud 등 해외 서버에서 한국 정부 인증서 검증 실패 시 재시도
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, params=params, headers=headers, timeout=timeout, verify=False)

@st.cache_data(ttl=TTL_WEEKLY, show_spinner="기업 목록 로딩 중... (최초 1회, 약 10~20초)")
def load_corp_list() -> list[dict]:
    r = _dart_get("corpCode.xml", {"crtfc_key": DART_KEY})
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        with z.open("CORPCODE.xml") as f:
            xml_content = f.read().decode("utf-8")
    root = ET.fromstring(xml_content)
    corps = []
    for item in root.findall("list"):
        code  = (item.findtext("corp_code")  or "").strip()
        name  = (item.findtext("corp_name")  or "").strip()
        stock = (item.findtext("stock_code") or "").strip()
        if code and name:
            corps.append({"corp_code": code, "corp_name": name, "stock_code": stock})
    return corps
def search_corps(query: str, all_corps: list[dict]) -> list[dict]:
    q  = query.strip()
    ql = q.lower()
    if q.isdigit() or (len(q) >= 2 and q[0].upper() == "A" and q[1:].isdigit()):
        stock_q = q.lstrip("Aa")
        matches = [c for c in all_corps if c["stock_code"] in (stock_q, q)]
    else:
        exact   = [c for c in all_corps if c["corp_name"].lower() == ql]
        partial = [c for c in all_corps if ql in c["corp_name"].lower()]
        matches = exact if exact else partial
    if not matches:
        return []
    matches.sort(key=lambda c: (
        c["corp_name"].lower() != ql,                                     # 정확히 일치 먼저
        not bool(c["stock_code"]),                                        # 상장 기업 먼저
        -(int(c["corp_code"]) if c["corp_code"].isdigit() else 0),        # 최신 등록 법인 먼저
        c["corp_name"],
    ))
    return matches[:20]
# ══════════════════════════════════════════
#  DART API — 재무 데이터
# ══════════════════════════════════════════
@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_year(corp_code: str, year: int, fs_div: str) -> dict | None:
    try:
        r = requests.get(
            f"{BASE}/fnlttSinglAcntAll.json",
            params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                    "bsns_year": year, "reprt_code": "11011", "fs_div": fs_div},
            timeout=15,
        )
        d = r.json()
        if d.get("status") != "000" or not d.get("list"):
            return None
        lst = d["list"]
        bs  = [x for x in lst if x.get("sj_div") == "BS"]
        isl = [x for x in lst if x.get("sj_div") == "IS"] or \
              [x for x in lst if x.get("sj_div") == "CIS"]
        cf  = [x for x in lst if x.get("sj_div") == "CF"]
        short_d = find_amount(bs, ACC["shortDebt"])
        long_d  = find_amount(bs, ACC["longDebt"])
        cash_bs = find_amount(bs, ACC["cashEquiv"])
        total_debt = (short_d or 0) + (long_d or 0) if (short_d is not None or long_d is not None) else None
        net_debt   = (total_debt - (cash_bs or 0)) if total_debt is not None else None
        result = {
            "bs": {
                "assets":           find_amount(bs, ACC["assets"]),
                "liabilities":      find_amount(bs, ACC["liabilities"]),
                "equity":           find_amount(bs, ACC["equity"]),
                "retainedEarnings": find_retained_earnings(bs),
                "shortDebt":        short_d,
                "longDebt":         long_d,
                "cashEquiv":        cash_bs,
                "totalDebt":        total_debt,
                "netDebt":          net_debt,
            },
            "is": {
                "revenue":   find_amount(isl, ACC["revenue"]),
                "opIncome":  find_amount(isl, ACC["opIncome"]),
                "netIncome": find_amount(isl, ACC["netIncome"]),
            },
            "cf": {
                "opCF":    find_amount(cf, ACC["opCF"]),
                "invCF":   find_amount(cf, ACC["invCF"]),
                "finCF":   find_amount(cf, ACC["finCF"]),
                "endCash": find_end_cash(cf),
                # EBITDA 구성: 영업활동CF 조정항목에서 D&A 추출
                # ① 키워드 매칭 → ② DART ZIP 주석 HTML 파싱 순으로 시도
                "depre":   find_amount(cf, ACC["depreciation"]),
                "amort":   find_amount(cf, ACC["amortization"]),
                # 디버그용: CF 전체 계정명 + 금액 필드 (D&A 매칭 실패 시 확인용)
                "_cf_accounts": [
                    {
                        "계정명":           item.get("account_nm", ""),
                        "thstrm_amount":   item.get("thstrm_amount",     ""),
                        "thstrm_add_amt":  item.get("thstrm_add_amount", ""),
                    }
                    for item in cf
                    if item.get("account_nm")
                ],
            },
        }
        # "_"로 시작하는 메타 필드(디버그용)는 제외하고 실제 재무 필드만 체크
        has_data = any(
            v is not None
            for sec in result.values()
            for k, v in sec.items()
            if not k.startswith("_")
        )
        return result if has_data else None
    except Exception:
        return None
@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_all_years(corp_code: str, fs_div: str, _ver: int = _CACHE_VER) -> dict:
    """연도별 재무데이터를 ThreadPoolExecutor로 병렬 조회 (순차 대비 최대 5× 빠름)."""
    all_data: dict[str, dict] = {}
    def _fetch(year: int) -> tuple[int, dict | None]:
        return year, fetch_year(corp_code, year, fs_div)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch, year): year for year in YEARS}
        for future in as_completed(futures):
            year, data = future.result()
            if data:
                all_data[str(year)] = data
    return all_data


# ──────────────────────────────────────────────────────────────────────────────
#  DART 공시 ZIP HTML 파싱 — 재무제표 주석에서 D&A 추출 (fnlttSinglAcntAll 누락 폴백)
# ──────────────────────────────────────────────────────────────────────────────
_DA_ZIP_SIZE_LIMIT = 200 * 1024 * 1024  # 200 MB — 초과 시 파싱 건너뜀


@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def _fetch_rcept_no(corp_code: str, year: int) -> str | None:
    """해당 연도 사업보고서(reprt_code=11011) rcept_no 조회."""
    try:
        r = _dart_get("list.json", {
            "crtfc_key":        DART_KEY,
            "corp_code":        corp_code,
            "bgn_de":           f"{year}0101",
            "end_de":           f"{year + 1}0630",
            "pblntf_detail_ty": "A001",   # 사업보고서
            "sort":             "date",
            "sort_mthd":        "desc",
            "page_count":       "10",
        })
        d = r.json()
        if d.get("status") != "000":
            return None
        items = [
            x for x in d.get("list", [])
            if str(x.get("bsns_year", "")) == str(year)
        ]
        return items[0]["rcept_no"] if items else None
    except Exception:
        return None


@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def _fetch_da_from_dart_zip(corp_code: str, year: int) -> tuple[int | None, int | None]:
    """
    DART 사업보고서 ZIP → HTML 재무제표 주석 파싱 → 감가상각비·무형자산상각비 (억원).

    대상: fnlttSinglAcntAll 에서 D&A 항목이 누락된 기업 (삼성 등 조정합계만 태깅).
    주석 27(현금흐름표 조정내역) HTML 테이블에서 "감가상각비"·"무형자산상각비" 행을 찾아 파싱.

    반환: (depre_억원, amort_억원) — 40 MB 초과 or 파싱 실패 시 (None, None).
    """
    import zipfile, io, re
    from bs4 import BeautifulSoup

    rcept_no = _fetch_rcept_no(corp_code, year)
    if not rcept_no:
        return None, None

    # ── ZIP 다운로드 (크기 제한) ──────────────────────────────────────────────
    try:
        r = _dart_get(
            "document.xml",
            {"crtfc_key": DART_KEY, "rcept_no": rcept_no},
            timeout=(10, 180),
        )
        raw = r.content
    except Exception:
        return None, None

    if not raw or len(raw) < 1_000:
        return None, None
    if len(raw) > _DA_ZIP_SIZE_LIMIT:
        return None, None   # ZIP 너무 큼 → 건너뜀

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        return None, None

    # ── 단위 감지 헬퍼 ────────────────────────────────────────────────────────
    def _detect_unit(text: str) -> float:
        """금액 단위 감지 → 억원 변환 제수."""
        snippet = text[:4000].replace(" ", "").replace("\n", "")
        if re.search(r"단위.*백만원|백만원.*단위|백만원\)", snippet, re.I):
            return 100.0        # 백만원 → 억원 (÷100)
        if re.search(r"단위.*억원|억원.*단위|억원\)", snippet, re.I):
            return 1.0          # 이미 억원
        if re.search(r"단위.*천원|천원.*단위|천원\)", snippet, re.I):
            return 100_000.0    # 천원 → 억원 (÷100,000)
        if re.search(r"단위.*원|원.*단위", snippet, re.I):
            return 1e8          # 원 → 억원 (÷1억)
        return 100.0            # 기본값: 백만원

    # ── 숫자 파싱 헬퍼 ───────────────────────────────────────────────────────
    def _parse_cell(s: str) -> int | None:
        s = s.strip().replace(",", "").replace(" ", "").replace("\xa0", "").replace("−", "-")
        neg = s.startswith("(") and s.endswith(")")
        s   = s.strip("()")
        if not s or not s.lstrip("-").isdigit():
            return None
        v = int(s)
        return -v if neg else v

    depre: int | None = None
    amort: int | None = None

    try:
        # ── HTML 파일 검색 (파일명 정렬 → 주석 파일 우선 도달 경향) ───────────
        for name in sorted(zf.namelist()):
            if not name.lower().endswith((".html", ".htm")):
                continue
            try:
                html = zf.read(name).decode("utf-8", errors="replace")
            except Exception:
                continue
            if "감가상각비" not in html:
                continue

            unit_div = _detect_unit(html)
            soup     = BeautifulSoup(html, "html.parser")

            for row in soup.find_all("tr"):
                cells      = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                label = re.sub(r"\s+", "", cells[0].get_text())

                # 감가상각비 (유형자산 / 사용권자산 포함)
                if depre is None and re.fullmatch(r"감가상각비|유형자산감가상각비|사용권자산감가상각비", label):
                    for cell in cells[1:]:
                        v = _parse_cell(cell.get_text())
                        if v is not None and v > 0:
                            depre = round(v / unit_div)
                            break

                # 무형자산상각비
                if amort is None and re.fullmatch(r"무형자산상각비|무형자산의?상각비|무형자산의?상각", label):
                    for cell in cells[1:]:
                        v = _parse_cell(cell.get_text())
                        if v is not None and v > 0:
                            amort = round(v / unit_div)
                            break

            if depre is not None:
                break   # 첫 번째로 "감가상각비" 포함 HTML에서 탐색 완료

    finally:
        zf.close()

    return depre, amort
# ══════════════════════════════════════════
#  DART API — 기업 개요
# ══════════════════════════════════════════
@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def fetch_company_overview(corp_code: str, stock_code: str) -> dict:
    result = {}
    try:
        r = requests.get(f"{BASE}/company.json",
                         params={"crtfc_key": DART_KEY, "corp_code": corp_code},
                         timeout=10)
        d = r.json()
        if d.get("status") == "000":
            cls_map = {"Y": "유가증권(KOSPI)", "K": "코스닥(KOSDAQ)", "N": "코넥스", "E": "기타"}
            est = d.get("est_dt", "")
            raw_url = (d.get("hm_url") or "").strip().rstrip("/")
            result = {
                "ceo_nm":       d.get("ceo_nm", ""),
                "corp_cls":     cls_map.get(d.get("corp_cls", ""), ""),
                "corp_cls_raw": d.get("corp_cls", "Y"),
                "est_dt":       f"{est[:4]}.{est[4:6]}" if len(est) >= 6 else "",
                "acc_mt":       f"{d.get('acc_mt', '')}월" if d.get("acc_mt") else "",
                "phn_no":       d.get("phn_no", ""),
                "adres":        d.get("adres", ""),
                "hm_url":       ("https://" + raw_url) if raw_url and not raw_url.startswith(("http://", "https://")) else raw_url,
            }
    except Exception:
        pass
    return result
# ══════════════════════════════════════════
#  시장 데이터 (환율 + 미국채)
# ══════════════════════════════════════════
@st.cache_data(ttl=TTL_REALTIME, show_spinner=False)
def fetch_market_data() -> dict:
    if not _YF_AVAILABLE:
        return {}
    try:
        cfg = {
            "USDKRW=X": (1,   1),
            "JPYKRW=X":  (100, 1),
            "USDJPY=X":  (1,   2),
            "^TNX":      (1,   3),
        }
        raw: dict[str, dict] = {}
        for sym, (mul, nd) in cfg.items():
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=True)
            if hist.empty:
                continue
            hist  = hist.dropna(subset=["Close"])
            dates = sorted(hist.index)
            cur   = round(float(hist.loc[dates[-1],  "Close"]) * mul, nd)
            prev  = round(float(hist.loc[dates[-2], "Close"]) * mul, nd) if len(dates) >= 2 else None
            chg   = round(cur - prev, nd) if prev is not None else None
            raw[sym] = {"value": cur, "chg": chg, "date": str(dates[-1])[:10]}
        ref_date = raw.get("USDKRW=X", {}).get("date", "")
        return {
            "usd_krw":        raw.get("USDKRW=X", {}).get("value"),
            "jpy100_krw":     raw.get("JPYKRW=X",  {}).get("value"),
            "usd_jpy":        raw.get("USDJPY=X",  {}).get("value"),
            "bond10y":        raw.get("^TNX",      {}).get("value"),
            "usd_krw_chg":    raw.get("USDKRW=X", {}).get("chg"),
            "jpy100_krw_chg": raw.get("JPYKRW=X",  {}).get("chg"),
            "usd_jpy_chg":    raw.get("USDJPY=X",  {}).get("chg"),
            "bond10y_chg":    raw.get("^TNX",      {}).get("chg"),
            "date":           ref_date,
        }
    except Exception:
        return {}
# ══════════════════════════════════════════
#  DART API — 공시
# ══════════════════════════════════════════
def _parse_disc_list(items: list[dict], count: int) -> list[dict]:
    result = []
    for item in items[:count]:
        rcept_dt = item.get("rcept_dt", "")
        if len(rcept_dt) == 8:
            rcept_dt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"
        rcept_no = item.get("rcept_no", "")
        link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
        corp_cls_map = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}
        result.append({
            "report_nm": item.get("report_nm", "").strip(),
            "flr_nm":    item.get("flr_nm", "").strip(),
            "rcept_dt":  rcept_dt,
            "corp_cls":  corp_cls_map.get(item.get("corp_cls", ""), ""),
            "link":      link,
        })
    return result
@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_disclosures(corp_code: str, count: int = 15) -> tuple[list[dict], str]:
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")
    base_params = {
        "crtfc_key":  DART_KEY,
        "corp_code":  corp_code,
        "bgn_de":     bgn_de,
        "end_de":     end_de,
        "page_count": count,
        "page_no":    1,
    }
    attempts = [("I", "거래소공시"), ("B", "주요사항보고"), ("A", "정기공시"), ("", "전체공시")]
    last_err = ""
    for pblntf_ty, label in attempts:
        try:
            params = dict(base_params)
            if pblntf_ty:
                params["pblntf_ty"] = pblntf_ty
            r = requests.get(f"{BASE}/list.json", params=params, timeout=10)
            d = r.json()
            if d.get("status") == "000" and d.get("list"):
                return _parse_disc_list(d["list"], count), label
            last_err = f"{label}: {d.get('status','?')} {d.get('message','')}"
        except Exception as e:
            last_err = str(e)
    return [], last_err or "공시 조회 실패"
# ══════════════════════════════════════════
#  뉴스
# ══════════════════════════════════════════
@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_news(company_name: str, count: int = 15) -> list[dict]:
    try:
        query = urllib.parse.quote(company_name)
        url   = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        r     = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        root  = ET.fromstring(r.content)
        news  = []
        for item in root.findall(".//item")[:count]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "").strip()
            src   = item.findtext("source", "").strip()
            if " - " in title:
                title, src = title.rsplit(" - ", 1)
            try:
                pub_fmt = parsedate_to_datetime(pub).strftime("%m/%d %H:%M")
            except Exception:
                pub_fmt = pub[:16] if pub else ""
            news.append({"title": title.strip(), "link": link,
                         "source": src.strip(), "date": pub_fmt})
        return news
    except Exception:
        return []
# ══════════════════════════════════════════
#  DART API — 주주·임원 현황
# ══════════════════════════════════════════
_REPRT_CANDIDATES = (
    [(y, "11011") for y in range(datetime.now().year - 1, datetime.now().year - 6, -1)] +
    [(y, "11012") for y in range(datetime.now().year - 1, datetime.now().year - 4, -1)]
)
@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_major_shareholders(corp_code: str, _ver: int = _CACHE_VER) -> list[dict]:
    if not corp_code:
        return []
    for bsns_year, reprt_code in _REPRT_CANDIDATES:
        try:
            r = requests.get(
                f"{BASE}/hyslrSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(bsns_year), "reprt_code": reprt_code},
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue
            rows = []
            for item in (data.get("list") or []):
                name = (item.get("nm") or "").strip()
                if name in ("계", "합계", ""):
                    continue
                try:
                    shares = int((item.get("trmend_posesn_stock_co") or "").replace(",", "").strip())
                except ValueError:
                    shares = 0
                try:
                    ratio_pct = float((item.get("trmend_posesn_stock_qota_rt") or "").replace(",", "").strip())
                except ValueError:
                    ratio_pct = None
                rows.append({
                    "name":      name,
                    "relation":  (item.get("relate") or "").strip(),
                    "shares":    shares,
                    "ratio":     ratio_pct,
                    "stock_knd": (item.get("stock_knd") or "").strip(),
                    "rm":        (item.get("rm") or "").strip(),
                    "stlm_dt":   (item.get("stlm_dt") or "").strip(),
                    "year":      bsns_year,
                    "rcode":     reprt_code,
                })
            if rows:
                return rows
        except Exception:
            continue
    return []
@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_major_shareholder_history(corp_code: str, _ver: int = _CACHE_VER) -> list[dict]:
    if not corp_code:
        return []
    for bsns_year, reprt_code in _REPRT_CANDIDATES:
        try:
            r = requests.get(
                f"{BASE}/hyslrChgSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(bsns_year), "reprt_code": reprt_code},
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue
            rows = []
            for item in (data.get("list") or []):
                nm = (item.get("mxmm_shrholdr_nm") or "").strip()
                if nm in ("-", ""):
                    continue
                shares_s = (item.get("posesn_stock_co") or "").replace(",", "").strip()
                ratio_s  = (item.get("qota_rt") or "").strip()
                try:
                    shares = int(shares_s) if shares_s not in ("", "-") else None
                except ValueError:
                    shares = None
                try:
                    ratio = float(ratio_s) if ratio_s not in ("", "-") else None
                except ValueError:
                    ratio = None
                rows.append({
                    "nm":      nm,
                    "chg_on":  (item.get("change_on") or "").strip(),
                    "shares":  shares,
                    "ratio":   ratio,
                    "cause":   (item.get("change_cause") or "").strip(),
                    "rm":      (item.get("rm") or "").strip(),
                    "stlm_dt": (item.get("stlm_dt") or "").strip(),
                    "year":    bsns_year,
                    "rcode":   reprt_code,
                })
            if rows:
                return rows
        except Exception:
            continue
    return []
def _is_year_key(k: str) -> bool:
    """4자리 연도 키 여부 판별 (PER/PBR 차트용)."""
    return len(k) == 4 and k.isdigit()
def _sal_fmt(v: int | None) -> str:
    """연봉 단위 변환 (원 → 만원 문자열)."""
    return f'{round((v or 0) / 10_000):,}만원' if v else "-"
def _to_man(v: int | None) -> int:
    """원 → 만원 변환."""
    return round((v or 0) / 10_000)
def _stock_info_cell(lbl: str, val: str, color: str = "#475569") -> str:
    """주가 정보 바 셀 HTML."""
    return (
        f'<span style="margin-right:12px;white-space:nowrap;">'
        f'<span style="font-size:.65rem;color:#94a3b8;">{lbl} </span>'
        f'<span style="font-size:.82rem;font-weight:600;color:{color};">{val}</span>'
        f'</span>'
    )
def _fx_card_item(label: str, value: float | None,
                  chg: float | None, unit: str = "", num_fmt: str = ".1f") -> str:
    """환율·금리 카드 셀 HTML."""
    if value is None:
        return ""
    if chg is not None and chg != 0:
        sym_c    = "▲" if chg > 0 else "▼"
        color    = "#dc2626" if chg > 0 else "#2563eb"
        chg_html = (f'<span style="font-size:.62rem;color:{color};margin-left:3px;">'
                    f'{sym_c}{abs(chg):{num_fmt}}</span>')
    else:
        chg_html = ""
    val_str = f"{value:,{num_fmt}}"   # num_fmt = ".1f" → ":,.1f"
    unit_html = (f'<span style="font-size:.65rem;font-weight:400;color:#94a3b8;margin-left:2px;">{unit}</span>'
                 if unit else "")
    return (
        f'<div style="flex:1;min-width:45%;text-align:center;padding:8px 6px;">'
        f'<div style="font-size:.65rem;color:#64748b;margin-bottom:2px;white-space:nowrap;">{label}</div>'
        f'<div style="font-size:.95rem;font-weight:700;color:#1e293b;white-space:nowrap;">'
        f'{val_str}{chg_html}{unit_html}</div>'
        f'</div>'
    )
def _get_yf_val(df_T, idx, keys: list[str]) -> float | None:
    """yfinance DataFrame에서 첫 번째 유효 키 값 반환."""
    for k in keys:
        if k in df_T.columns:
            v = df_T.loc[idx, k]
            if pd.notna(v):
                return float(v)
    return None
def _safe_int(v: str) -> int | None:
    s = (v or "").replace(",", "").strip()
    try:
        return int(s) if s else None
    except ValueError:
        return None
def _safe_float(v: str) -> float | None:
    try:
        return float(v or 0) or None
    except (ValueError, TypeError):
        return None
@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_large_holding_reports(corp_code: str, count: int = 20, _ver: int = _CACHE_VER) -> list[dict]:
    if not DART_KEY or not corp_code:
        return []
    try:
        r = requests.get(
            f"{BASE}/majorstock.json",
            params={"crtfc_key": DART_KEY, "corp_code": corp_code},
            timeout=10,
        )
        data = r.json()
        if data.get("status") != "000":
            return []
        rows = []
        for item in sorted(data.get("list") or [], key=lambda x: x.get("rcept_dt", ""), reverse=True)[:count]:
            rows.append({
                "rcept_dt":    item.get("rcept_dt", ""),
                "rcept_no":    item.get("rcept_no", ""),
                "report_tp":   item.get("report_tp", ""),
                "repror":      item.get("repror", ""),
                "stkqy":       _safe_int(item.get("stkqy", "")),
                "stkqy_irds":  _safe_int(item.get("stkqy_irds", "")),
                "stkrt":       _safe_float(item.get("stkrt")),
                "stkrt_irds":  _safe_float(item.get("stkrt_irds")),
                "report_resn": (item.get("report_resn") or "").replace("\n", " / ").strip(),
            })
        return rows
    except Exception:
        return []
@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_executive_stock_reports(corp_code: str, count: int = 30, _ver: int = _CACHE_VER) -> list[dict]:
    if not DART_KEY or not corp_code:
        return []
    try:
        r = requests.get(
            f"{BASE}/elestock.json",
            params={"crtfc_key": DART_KEY, "corp_code": corp_code},
            timeout=10,
        )
        data = r.json()
        if data.get("status") != "000":
            return []
        rows = []
        for item in (data.get("list") or []):
            irds_raw = (item.get("sp_stock_lmp_irds_cnt") or "0").replace(",", "")
            try:
                irds = int(irds_raw)
            except ValueError:
                irds = 0
            rows.append({
                "rcept_no": item.get("rcept_no", ""),
                "rcept_dt": item.get("rcept_dt", ""),
                "repror":   (item.get("repror") or "").strip(),
                "rgist_at": (item.get("isu_exctv_rgist_at") or "").strip(),
                "ofcps":    (item.get("isu_exctv_ofcps") or "").strip(),
                "shares":   (item.get("sp_stock_lmp_cnt") or "0").replace(",", "").strip(),
                "irds":     irds,
                "irds_raw": item.get("sp_stock_lmp_irds_cnt", "0"),
            })
        rows.sort(key=lambda x: x["rcept_dt"], reverse=True)
        return rows[:count]
    except Exception:
        return []
# ══════════════════════════════════════════
#  DART API — 직원 현황
# ══════════════════════════════════════════
def _emp_parse_int(v: str) -> int:
    s = (v or "").strip()
    if not s or s == "-":
        return 0
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0
def _emp_parse_float(v: str) -> float:
    s = (v or "").strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0
def _emp_parse_salary(v: str) -> int | None:
    s = (v or "").strip().replace(",", "")
    if not s or s == "-" or not s.isdigit():
        return None
    val = int(s)
    return val if val > 0 else None
def _emp_pick_agg(items: list[dict], sex: str) -> dict | None:
    """성별(남/여) 기준 대표 행 선택 — 합계 행 우선, 없으면 sm 최대 행."""
    rows = [x for x in items if (x.get("sexdstn") or "").strip() == sex]
    if not rows:
        return None
    agg = [x for x in rows if "합계" in (x.get("fo_bbm") or "")]
    return agg[0] if agg else max(rows, key=lambda x: _emp_parse_int(x.get("sm")))
@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_employee_status(corp_code: str, _ver: int = _CACHE_VER) -> dict:
    if not DART_KEY:
        return {}

    def _fetch_emp_year(year: int) -> tuple[int, dict | None]:
        try:
            r = requests.get(
                f"{BASE}/empSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": "11011"},
                timeout=10,
            )
            raw = r.json()
            if raw.get("status") != "000":
                return year, None
            all_items = raw.get("list") or []
            if not all_items:
                return year, None
            rec: dict[str, Any] = {}
            for sex, prefix in [("남", "male"), ("여", "female")]:
                item = _emp_pick_agg(all_items, sex)
                if not item:
                    continue
                rec[prefix]                    = _emp_parse_int(item.get("rgllbr_co"))
                rec[f"{prefix}_contract"]      = _emp_parse_int(item.get("cnttk_co"))
                rec[f"{prefix}_total"]         = _emp_parse_int(item.get("sm"))
                rec[f"avg_tenure_{prefix[0]}"] = _emp_parse_float(item.get("avrg_cnwk_sdytrn"))
                rec[f"salary_{prefix[0]}"]     = _emp_parse_salary(item.get("jan_salary_am"))
            if rec:
                rec["total"] = rec.get("male_total", 0) + rec.get("female_total", 0)
                return year, rec
            return year, None
        except Exception:
            return year, None

    result: dict[str, dict] = {}
    fetch_years = list(range(2015, datetime.now().year))
    with ThreadPoolExecutor(max_workers=5) as executor:
        for year, rec in executor.map(_fetch_emp_year, fetch_years):
            if rec:
                result[str(year)] = rec
    return result
# ══════════════════════════════════════════
#  주가 데이터 (yfinance)
# ══════════════════════════════════════════
def _resolve_ticker(stock_code: str, corp_cls: str) -> tuple[str, str] | None:
    """corp_cls 에 맞는 거래소 접미사를 시도하고, 데이터가 없으면 반대 거래소도 시도.
    DART가 corp_cls='E'(기타)로 잘못 분류한 KOSPI/KOSDAQ 종목에 대응.
    반환: (ticker, suffix) or None
    """
    primary   = ".KQ" if corp_cls == "K" else ".KS"
    secondary = ".KS" if primary == ".KQ" else ".KQ"
    for suffix in (primary, secondary):
        ticker = f"{stock_code}{suffix}"
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
            if not hist.empty:
                return ticker, suffix
        except Exception:
            continue
    return None
@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_stock_chart(stock_code: str, corp_cls: str = "Y",
                      timeframe: str = "6mo", _ver: int = _CACHE_VER) -> list[dict]:
    if not _YF_AVAILABLE or not stock_code:
        return []
    try:
        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            return []
        ticker, _ = resolved
        _today = datetime.now()
        cfg = {
            "6mo":   dict(period="6mo",  interval="1d"),
            "24mo":  dict(period="2y",   interval="1d"),
            # period="3y"는 yfinance에서 빈 데이터를 반환하는 경우가 있어 start/end 명시
            "36mo":  dict(start=(_today - timedelta(days=1097)).strftime("%Y-%m-%d"),
                         end=_today.strftime("%Y-%m-%d"), interval="1d"),
            "month": dict(period="10y",  interval="1mo"),
            "year":  dict(period="max",  interval="3mo"),
        }
        df = yf.Ticker(ticker).history(**cfg.get(timeframe, cfg["6mo"]), auto_adjust=True)
        if df.empty:
            return []
        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        df = df[df["Volume"] > 0]
        if timeframe in ("6mo", "24mo", "36mo"):
            df = df[df.index.dayofweek < 5]
            df = df[df["High"] > df["Low"]]
        data = [
            {
                "date":   str(dt)[:10],
                "year":   str(dt)[:4],
                "open":   round(float(row["Open"]),  0),
                "high":   round(float(row["High"]),  0),
                "low":    round(float(row["Low"]),   0),
                "close":  round(float(row["Close"]), 0),
                "volume": float(row["Volume"]),
            }
            for dt, row in df.iterrows()
        ]
        if timeframe == "year" and data:
            yearly: dict[str, dict] = {}
            for d in data:
                yr = d["year"]
                if yr not in yearly:
                    yearly[yr] = {**d, "date": yr}
                else:
                    yearly[yr]["high"]    = max(yearly[yr]["high"], d["high"])
                    yearly[yr]["low"]     = min(yearly[yr]["low"],  d["low"])
                    yearly[yr]["close"]   = d["close"]
                    yearly[yr]["volume"] += d["volume"]
            data = sorted(yearly.values(), key=lambda x: x["date"])
        return data
    except Exception:
        return []
@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def fetch_yf_annual_data(stock_code: str, corp_cls: str = "Y",
                         corp_code: str = "", _ver: int = _CACHE_VER) -> dict:
    if not _YF_AVAILABLE or not stock_code:
        return {"__error__": "yfinance 없음"}
    try:
        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            return {"__error__": "주가 데이터 없음 (KS/KQ 모두 시도)"}
        actual_ticker, _ = resolved
        t = yf.Ticker(actual_ticker)
        shares: int | None = None
        try:
            shares = t.fast_info.shares
        except Exception:
            pass
        if not shares:
            shares = (t.info or {}).get("sharesOutstanding")
        today_mktcap_eok: int | None = None
        try:
            mc = t.fast_info.market_cap
            if mc:
                today_mktcap_eok = round(float(mc) / 1e8)
        except Exception:
            pass
        today_price: float | None = None
        try:
            today_price = float(t.fast_info.last_price)
        except Exception:
            pass
        hist = None
        for _attempt in range(3):
            try:
                hist = t.history(period="12y", interval="1mo", auto_adjust=True)
                break
            except Exception as _e:
                _emsg = str(_e)
                if _attempt < 2 and any(
                    k in _emsg for k in ("Too Many", "Rate", "429", "limit")
                ):
                    time.sleep(3 * (_attempt + 1))
                else:
                    return {"__error__": _emsg}
        if hist is None or hist.empty:
            return {"__error__": "주가 데이터 없음"}
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        cur_year = datetime.now().year
        year_closes: dict[int, float] = {}
        for yr in range(cur_year - 9, cur_year + 1):
            yr_data = hist[hist.index.year == yr]
            if not yr_data.empty:
                year_closes[yr] = float(yr_data["Close"].iloc[-1])
        # 시가총액
        mktcap: dict[str, int] = {}
        if shares:
            for yr, close in year_closes.items():
                if yr != cur_year:
                    mktcap[str(yr)] = round(close * shares / 1e8)
        if today_mktcap_eok:
            mktcap[str(cur_year)] = today_mktcap_eok
        elif today_price and shares:
            mktcap[str(cur_year)] = round(today_price * shares / 1e8)
        elif shares and cur_year in year_closes:
            mktcap[str(cur_year)] = round(year_closes[cur_year] * shares / 1e8)
        # PER / PBR — DART 재무 기반 (병렬 조회)
        per_pbr: dict[str, dict] = {}
        if corp_code and shares and shares > 0:
            target_years = [yr for yr in range(cur_year - 9, cur_year) if yr in year_closes]
            def _fetch_per_pbr(yr: int) -> tuple[int, dict | None]:
                d = fetch_year(corp_code, yr, "CFS") or fetch_year(corp_code, yr, "OFS")
                if not d:
                    return yr, None
                close = year_closes[yr]
                ni = d["is"].get("netIncome")
                eq = d["bs"].get("equity")
                per = round(close / (ni * 1e8 / shares), 1) if (ni and ni > 0) else None
                pbr = round(close / (eq * 1e8 / shares), 2) if (eq and eq > 0) else None
                return yr, {"PER": per, "PBR": pbr} if (per is not None or pbr is not None) else None
            with ThreadPoolExecutor(max_workers=5) as executor:
                for yr, pp in executor.map(_fetch_per_pbr, target_years):
                    if pp:
                        per_pbr[str(yr)] = pp
        # yfinance fallback (DART 데이터 없을 때)
        if not per_pbr:
            try:
                fin  = t.financials
                bs_f = t.balance_sheet
                if fin is not None and not fin.empty:
                    fin_T = fin.T.copy()
                    fin_T.index = pd.to_datetime(fin_T.index).tz_localize(None)
                    bs_T = pd.DataFrame()
                    if bs_f is not None and not bs_f.empty:
                        bs_T = bs_f.T.copy()
                        bs_T.index = pd.to_datetime(bs_T.index).tz_localize(None)
                    NI_KEYS = ["Net Income", "Net Income Common Stockholders"]
                    EQ_KEYS = ["Stockholders Equity", "Common Stock Equity",
                               "Total Equity Gross Minority Interest"]
                    for idx_date in fin_T.index:
                        yr    = idx_date.year
                        close = year_closes.get(yr)
                        if close is None or not shares or shares <= 0:
                            continue
                        ni = _get_yf_val(fin_T, idx_date, NI_KEYS)
                        eq = None
                        if not bs_T.empty:
                            closest = min(bs_T.index, key=lambda d: abs((d - idx_date).days))
                            eq = _get_yf_val(bs_T, closest, EQ_KEYS)
                        per = round(close / (ni / shares), 1) if (ni and ni > 0) else None
                        pbr = round(close / (eq / shares), 2) if (eq and eq > 0) else None
                        if per is not None or pbr is not None:
                            per_pbr[str(yr)] = {"PER": per, "PBR": pbr}
            except Exception:
                pass
        # 오늘 포인트
        if today_price and shares and shares > 0:
            today_label = datetime.now().strftime("%Y-%m-%d")
            latest_yr   = cur_year - 1
            if corp_code:
                d = fetch_year(corp_code, latest_yr, "CFS") or fetch_year(corp_code, latest_yr, "OFS")
                if d:
                    ni_t = d["is"].get("netIncome")
                    eq_t = d["bs"].get("equity")
                    today_pp: dict[str, float] = {}
                    if ni_t and ni_t > 0:
                        today_pp["PER"] = round(today_price / (ni_t * 1e8 / shares), 1)
                    if eq_t and eq_t > 0:
                        today_pp["PBR"] = round(today_price / (eq_t * 1e8 / shares), 2)
                    if today_pp:
                        per_pbr[today_label] = today_pp
        return {"mktcap": mktcap, "per_pbr": per_pbr}
    except Exception as e:
        return {"__error__": str(e)}
# ══════════════════════════════════════════
#  차트 헬퍼
# ══════════════════════════════════════════
def make_bar(years: list, series: dict, title: str) -> go.Figure:
    colors_list = [COLORS["blue"], COLORS["red"], COLORS["green"],
                   COLORS["orange"], COLORS["purple"]]
    fig = go.Figure()
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Bar(name=name, x=years, y=vals,
                             marker_color=colors_list[i % len(colors_list)],
                             marker_line_width=0))
    fig.update_layout(title_text=title, title_font_color="#1e293b",
                      title_font_size=12, barmode="group", **PLOTLY_LAYOUT)
    return fig
def make_line(years: list, series: dict, title: str, is_pct: bool = False) -> go.Figure:
    colors_list = [COLORS["orange"], COLORS["purple"], COLORS["green"],
                   COLORS["blue"], COLORS["red"]]
    fig = go.Figure()
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Scatter(name=name, x=years, y=vals, mode="lines+markers",
                                 line=dict(color=colors_list[i % len(colors_list)], width=2),
                                 marker=dict(size=5)))
    suffix = "%" if is_pct else ""
    fig.update_layout(
        title_text=title, title_font_color="#1e293b", title_font_size=12,
        yaxis=dict(ticksuffix=suffix, gridcolor="#e2e8f0", tickfont=dict(color="#64748b")),
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k != "yaxis"},
    )
    return fig
# ══════════════════════════════════════════
#  KPI 카드
# ══════════════════════════════════════════
def kpi_card(label: str, cur, prev, is_pct: bool = False, invert: bool = False) -> None:
    if cur is None:
        val_str    = "-"
        delta_html = ""
    else:
        val_str = f"{cur:.1f}%" if is_pct else fmt(cur)
        if prev is not None:
            diff  = cur - prev
            d_str = f"{abs(diff):.1f}%p" if is_pct else (
                f"{abs(int(diff)):,} ({abs(diff/prev*100):.1f}%)" if prev != 0 else f"{abs(int(diff)):,}"
            )
            is_up = diff > 0
            good  = (not invert and is_up) or (invert and not is_up)
            cls   = "up" if good else ("down" if diff != 0 else "flat")
            sym   = "▲" if diff > 0 else ("▼" if diff < 0 else "—")
            delta_html = f'<div class="metric-delta {cls}">{sym} {d_str}</div>'
        else:
            delta_html = '<div class="metric-delta flat">전년 데이터 없음</div>'
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-label">{label}</div>'
        f'<div class="metric-value">{val_str}</div>'
        f'{delta_html}</div>',
        unsafe_allow_html=True,
    )
# ══════════════════════════════════════════
#  주식 탭 — 서브 렌더러
# ══════════════════════════════════════════
def _render_mktcap_chart(stock_code: str, corp_cls: str, corp_code: str) -> dict:
    _section_header("연도별 시가총액", "과거: 연말 종가 기준 · 현재 연도: 당일 현재가 기준 (억 원)")
    yf_data = fetch_yf_annual_data(stock_code, corp_cls, corp_code, _ver=_CACHE_VER)
    if "__error__" in yf_data:
        st.caption(f"시가총액 데이터를 가져올 수 없습니다: {yf_data['__error__']}")
        return yf_data
    mktcap = yf_data.get("mktcap", {})
    if not mktcap:
        st.caption("시가총액을 계산하기 위한 데이터가 부족합니다 (발행주식수 미확인).")
        return yf_data
    cur_yr_str = str(datetime.now().year)
    years_mc   = sorted(mktcap.keys())
    vals_mc    = [mktcap[y] for y in years_mc]

    # ── KPI 요약 카드 ──────────────────────────────────────────────────────────
    def _fmt_mc(v):
        if v is None: return "-"
        return f"{v/10_000:.1f}조" if v >= 10_000 else f"{int(v):,}억"

    latest_mc = vals_mc[-1] if vals_mc else None
    prev_mc   = vals_mc[-2] if len(vals_mc) >= 2 else None
    max_idx   = max(range(len(vals_mc)), key=lambda i: vals_mc[i])
    min_idx   = min(range(len(vals_mc)), key=lambda i: vals_mc[i])

    mc_sub = ""
    if latest_mc and prev_mc and prev_mc > 0:
        chg = (latest_mc - prev_mc) / prev_mc * 100
        sym = "▲" if chg >= 0 else "▼"
        clr = "#dc2626" if chg >= 0 else "#2563eb"
        mc_sub = f'<span style="color:{clr};">{sym}{abs(chg):.1f}%</span> vs {years_mc[-2]}'

    def _kc(label, value, sub="", hi=False):
        bg  = "#eff6ff" if hi else "#f8fafc"
        bdr = "2px solid #2563eb" if hi else "1px solid #e2e8f0"
        lc  = "#2563eb" if hi else "#64748b"
        return (
            f'<div style="flex:1;min-width:120px;text-align:center;padding:10px 8px;'
            f'border:{bdr};border-radius:8px;background:{bg};margin:3px;">'
            f'<div style="font-size:.65rem;color:{lc};font-weight:500;">{label}</div>'
            f'<div style="font-size:.98rem;font-weight:700;color:#1e293b;margin-top:4px;">{value}</div>'
            f'<div style="font-size:.61rem;color:#94a3b8;margin-top:2px;">{sub}</div>'
            f'</div>'
        )

    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;margin:0 0 8px;">'
        + _kc(f"시가총액 ({years_mc[-1]})", _fmt_mc(latest_mc), mc_sub, hi=True)
        + _kc(f"최고 ({years_mc[max_idx]})", _fmt_mc(vals_mc[max_idx]), "기간 내 최고")
        + _kc(f"최저 ({years_mc[min_idx]})", _fmt_mc(vals_mc[min_idx]), "기간 내 최저")
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── 차트 (레이블 제거 → hover만) ─────────────────────────────────────────
    bar_colors = [COLORS["orange"] if y == cur_yr_str else COLORS["blue"] for y in years_mc]
    fig = go.Figure(go.Bar(
        x=years_mc, y=vals_mc, marker_color=bar_colors,
        hovertemplate="%{x}<br>시가총액: %{y:,.0f}억원<extra></extra>",
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "xaxis")},
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
        yaxis=dict(title="억 원", tickformat=",", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b")),
        margin=dict(l=10, r=10, t=30, b=10),
        height=280,
    )
    st.plotly_chart(fig, use_container_width=True)
    return yf_data
def _render_per_pbr_chart(yf_data: dict) -> None:
    _section_header("PER / PBR 밸류에이션 추이", "연말 종가 기준 · 오늘: trailing 기준")
    raw_per_pbr = yf_data.get("per_pbr", {})
    if not raw_per_pbr:
        st.caption("PER/PBR 계산에 필요한 재무데이터(순이익, 자본총계)를 가져올 수 없습니다.")
        return
    today_key = datetime.now().strftime("%Y-%m-%d")
    per_pbr: dict[str, dict] = {}
    for k, v in raw_per_pbr.items():
        per_pbr[today_key if (not _is_year_key(k) and k != today_key) else k] = v
    hist_keys  = sorted([k for k in per_pbr if _is_year_key(k)], key=int)
    date_keys  = sorted([k for k in per_pbr if not _is_year_key(k)])
    years_pp   = hist_keys + date_keys
    per_vals   = [per_pbr[y].get("PER") for y in years_pp]
    pbr_vals   = [per_pbr[y].get("PBR") for y in years_pp]

    # ── KPI 요약 카드 ──────────────────────────────────────────────────────────
    cur_per = per_pbr.get(today_key, {}).get("PER")
    cur_pbr = per_pbr.get(today_key, {}).get("PBR")
    hist_per_vals = [per_pbr.get(y, {}).get("PER") for y in hist_keys[-5:]]
    hist_pbr_vals = [per_pbr.get(y, {}).get("PBR") for y in hist_keys[-5:]]
    hist_per_vals = [v for v in hist_per_vals if v]
    hist_pbr_vals = [v for v in hist_pbr_vals if v]
    avg_per = round(sum(hist_per_vals) / len(hist_per_vals), 1) if hist_per_vals else None
    avg_pbr = round(sum(hist_pbr_vals) / len(hist_pbr_vals), 2) if hist_pbr_vals else None

    def _kc(label, value, sub="", hi=False):
        bg  = "#eff6ff" if hi else "#f8fafc"
        bdr = "2px solid #2563eb" if hi else "1px solid #e2e8f0"
        lc  = "#2563eb" if hi else "#64748b"
        return (
            f'<div style="flex:1;min-width:120px;text-align:center;padding:10px 8px;'
            f'border:{bdr};border-radius:8px;background:{bg};margin:3px;">'
            f'<div style="font-size:.65rem;color:{lc};font-weight:500;">{label}</div>'
            f'<div style="font-size:.98rem;font-weight:700;color:#1e293b;margin-top:4px;">{value}</div>'
            f'<div style="font-size:.61rem;color:#94a3b8;margin-top:2px;">{sub}</div>'
            f'</div>'
        )

    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;margin:0 0 8px;">'
        + _kc("PER (현재)",
              f"{cur_per:.1f}x" if cur_per else "-",
              f"5년 평균 {avg_per:.1f}x" if avg_per else "",
              hi=True)
        + _kc("PBR (현재)",
              f"{cur_pbr:.2f}x" if cur_pbr else "-",
              f"5년 평균 {avg_pbr:.2f}x" if avg_pbr else "",
              hi=True)
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── 차트 ─────────────────────────────────────────────────────────────────
    def _marker(base_color: str) -> dict:
        return dict(
            size=[9 if not _is_year_key(y) else 5 for y in years_pp],
            color=[COLORS["red"] if not _is_year_key(y) else base_color for y in years_pp],
        )
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=years_pp, y=per_vals, name="PER", mode="lines+markers",
        line=dict(color=COLORS["blue"], width=2), marker=_marker(COLORS["blue"]),
        connectgaps=True,
        hovertemplate="%{x}<br>PER: %{y:.1f}x<extra></extra>",
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=years_pp, y=pbr_vals, name="PBR", mode="lines+markers",
        line=dict(color=COLORS["orange"], width=2, dash="dot"), marker=_marker(COLORS["orange"]),
        connectgaps=True,
        hovertemplate="%{x}<br>PBR: %{y:.2f}x<extra></extra>",
    ), secondary_y=True)
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "legend", "xaxis")},
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
        margin=dict(l=10, r=10, t=30, b=10),
        height=280,
    )
    fig.update_yaxes(title_text="PER (배)", ticksuffix="x",
                     gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), secondary_y=False)
    fig.update_yaxes(title_text="PBR (배)", ticksuffix="x",
                     gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)
def _render_shareholder_section(corp_code: str) -> None:
    """최대주주 현황 + 변동현황 테이블 렌더링."""
    rcode_label = {"11011": "사업보고서", "11012": "반기보고서",
                   "11013": "1분기보고서", "11014": "3분기보고서"}
    # ① 현황 테이블
    with st.spinner("최대주주 데이터 조회 중..."):
        shareholders = fetch_major_shareholders(corp_code)
    if shareholders:
        ref       = shareholders[0]
        ref_label = f"{ref['year']}년 {rcode_label.get(ref['rcode'], ref['rcode'])}"
        if ref.get("stlm_dt"):
            ref_label += f"  ·  결산일 {ref['stlm_dt']}"
        _section_header("최대주주·임원 소유현황", ref_label)
        rows_html = ""
        for i, sh in enumerate(shareholders):
            bg         = "#f8fafc" if i % 2 == 0 else "#ffffff"
            ratio_str  = f"{sh['ratio']:.2f}%" if sh["ratio"] is not None else "-"
            shares_str = f"{sh['shares']:,}" if sh["shares"] else "-"
            knd_badge  = (
                f'<span style="font-size:.62rem;background:#e0f2fe;color:#0369a1;'
                f'border-radius:4px;padding:1px 5px;margin-left:4px;">{sh["stock_knd"]}</span>'
            ) if sh.get("stock_knd") else ""
            rows_html += (
                f'<tr style="background:{bg};">'
                f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;">'
                f'{sh["name"]}{knd_badge}</td>'
                f'<td style="padding:5px 8px;font-size:.75rem;color:#64748b;text-align:center;">{sh["relation"]}</td>'
                f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;white-space:nowrap;">{shares_str}</td>'
                f'<td style="padding:5px 8px;font-size:.78rem;font-weight:600;color:#2563eb;text-align:right;white-space:nowrap;">{ratio_str}</td>'
                f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">{sh.get("rm","")}</td>'
                f'</tr>'
            )
        st.markdown(
            _html_table(["주주명", "관계", "보유주식수", "지분율", "비고"], rows_html,
                        align=["left", "center", "right", "right", "left"]),
            unsafe_allow_html=True,
        )
    else:
        _section_header("최대주주·임원 소유현황")
        st.caption("소유현황 데이터를 찾을 수 없습니다.")
    # ② 변동현황 테이블
    with st.spinner("최대주주 변동현황 조회 중..."):
        sh_history = fetch_major_shareholder_history(corp_code)
    if sh_history:
        ref_h     = sh_history[0]
        h_label   = f"{ref_h['year']}년 {rcode_label.get(ref_h['rcode'], ref_h['rcode'])}"
        if ref_h.get("stlm_dt"):
            h_label += f"  ·  결산일 {ref_h['stlm_dt']}"
        _section_header("최대주주 변동현황", h_label)
        rows_h = ""
        for i, sh in enumerate(sh_history):
            bg         = "#f8fafc" if i % 2 == 0 else "#ffffff"
            shares_str = f"{sh['shares']:,}" if sh["shares"] is not None else "-"
            ratio_str  = f"{sh['ratio']:.2f}%" if sh["ratio"] is not None else "-"
            rows_h += (
                f'<tr style="background:{bg};">'
                f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;">{sh["nm"]}</td>'
                f'<td style="padding:5px 8px;font-size:.72rem;color:#64748b;text-align:center;white-space:nowrap;">{sh.get("chg_on") or "-"}</td>'
                f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;">{shares_str}</td>'
                f'<td style="padding:5px 8px;font-size:.78rem;font-weight:600;color:#2563eb;text-align:right;">{ratio_str}</td>'
                f'<td style="padding:5px 8px;font-size:.72rem;color:#64748b;">{sh.get("cause") or "-"}</td>'
                f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;">{sh.get("rm") or ""}</td>'
                f'</tr>'
            )
        st.markdown(
            _html_table(["최대주주명", "변동일", "보유주식수", "지분율", "변동원인", "비고"], rows_h,
                        align=["left", "center", "right", "right", "left", "left"]),
            unsafe_allow_html=True,
        )
    else:
        _section_header("최대주주 변동현황")
        st.caption("변동현황 데이터를 찾을 수 없습니다.")
def _render_large_holdings(corp_code: str) -> None:
    """대량보유상황보고 테이블 렌더링."""
    with st.spinner("대량보유상황보고 조회 중..."):
        large_holdings = fetch_large_holding_reports(corp_code, count=15, _ver=_CACHE_VER)
    _section_header("대량보유상황보고")
    if not large_holdings:
        st.caption("대량보유상황보고 데이터를 찾을 수 없습니다.")
        return
    def _irds_cell(qty: int | None, rt: float | None) -> tuple[str, str]:
        if qty is not None and qty != 0:
            c   = "#dc2626" if qty > 0 else "#2563eb"
            sym = "▲" if qty > 0 else "▼"
            q_html = f'<span style="color:{c};font-size:.72rem;">{sym}{abs(qty):,}</span>'
            r_html = (f'<span style="color:{c};font-size:.72rem;">{sym}{abs(rt or 0):.2f}%</span>'
                      if rt is not None else q_html)
        else:
            q_html = r_html = '<span style="color:#94a3b8;font-size:.72rem;">-</span>'
        return q_html, r_html
    rows_lh = ""
    for i, lh in enumerate(large_holdings):
        bg         = "#f8fafc" if i % 2 == 0 else "#ffffff"
        stkqy_str  = f"{lh['stkqy']:,}" if lh["stkqy"] is not None else "-"
        stkrt_str  = f"{lh['stkrt']:.2f}%" if lh["stkrt"] is not None else "-"
        irds_q, irds_r = _irds_cell(lh["stkqy_irds"], lh["stkrt_irds"])
        dart_url   = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={lh['rcept_no']}"
        tp_badge   = (f'<span style="font-size:.62rem;background:#f0fdf4;color:#166534;'
                      f'border-radius:4px;padding:1px 5px;">{lh["report_tp"]}</span>'
                      if lh.get("report_tp") else "")
        resn       = lh.get("report_resn", "")
        resn_short = resn[:40] + "…" if len(resn) > 40 else resn
        rows_lh += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">'
            f'<a href="{dart_url}" target="_blank" style="color:#94a3b8;text-decoration:none;">{lh["rcept_dt"]}</a></td>'
            f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;white-space:nowrap;">'
            f'{lh["repror"]}&nbsp;{tp_badge}</td>'
            f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;">{stkqy_str}</td>'
            f'<td style="padding:5px 8px;text-align:right;">{irds_q}</td>'
            f'<td style="padding:5px 8px;font-size:.75rem;font-weight:600;color:#1e293b;text-align:right;">{stkrt_str}</td>'
            f'<td style="padding:5px 8px;text-align:right;">{irds_r}</td>'
            f'<td style="padding:5px 8px;font-size:.70rem;color:#64748b;" title="{resn}">{resn_short}</td>'
            f'</tr>'
        )
    st.markdown(
        _html_table(["접수일", "보고자", "보유주식수", "증감", "지분율", "증감율", "보고사유"], rows_lh,
                    align=["left", "left", "right", "right", "right", "right", "left"]),
        unsafe_allow_html=True,
    )
def _render_executive_reports(corp_code: str) -> None:
    """임원·주요주주 소유보고 테이블 렌더링."""
    with st.spinner("임원·주요주주 소유보고 조회 중..."):
        exec_reports = fetch_executive_stock_reports(corp_code, count=15, _ver=_CACHE_VER)
    _section_header("임원·주요주주 소유보고")
    if not exec_reports:
        st.caption("임원·주요주주 소유보고 데이터를 찾을 수 없습니다.")
        return
    rows_er = ""
    for i, er in enumerate(exec_reports):
        bg    = "#f8fafc" if i % 2 == 0 else "#ffffff"
        dt    = er["rcept_dt"]
        dt_fmt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}" if len(dt) == 8 else dt
        dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={er['rcept_no']}"
        irds  = er["irds"]
        if irds > 0:
            irds_cell = f'<span style="color:#dc2626;font-size:.72rem;">▲{er["irds_raw"]}</span>'
        elif irds < 0:
            irds_cell = f'<span style="color:#2563eb;font-size:.72rem;">▼{er["irds_raw"].lstrip("-")}</span>'
        else:
            irds_cell = '<span style="color:#94a3b8;font-size:.72rem;">-</span>'
        rgist = er["rgist_at"].replace("비등기임원", "비등기").replace("등기임원", "등기")
        rgist_badge = (
            f'<span style="font-size:.62rem;background:#f0fdf4;color:#166534;'
            f'border-radius:4px;padding:1px 5px;">{rgist}</span>'
        ) if rgist else ""
        try:
            shares_fmt = f'{int(er["shares"]):,}'
        except Exception:
            shares_fmt = er["shares"]
        rows_er += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">'
            f'<a href="{dart_url}" target="_blank" style="color:#94a3b8;text-decoration:none;">{dt_fmt}</a></td>'
            f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;white-space:nowrap;">'
            f'{er["repror"]}&nbsp;{rgist_badge}</td>'
            f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;white-space:nowrap;">{er["ofcps"] or "-"}</td>'
            f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;white-space:nowrap;">{shares_fmt}</td>'
            f'<td style="padding:5px 8px;text-align:right;white-space:nowrap;">{irds_cell}</td>'
            f'</tr>'
        )
    st.markdown(
        _html_table(["접수일", "보고자", "직위", "보유주식수", "증감"], rows_er,
                    align=["left", "left", "left", "right", "right"]),
        unsafe_allow_html=True,
    )
# ══════════════════════════════════════════
#  EV/EBITDA 차트
# ══════════════════════════════════════════
def _render_ev_ebitda_chart(yf_data: dict, corp_code: str) -> None:
    """EV/EBITDA 추이 카드 + 차트.
    EV = 시가총액 + 순부채(차입금합계 - 현금)
    EBITDA = 영업이익 + 감가상각비 + 무형자산상각비
    """
    mktcap = yf_data.get("mktcap", {})
    if not mktcap or not corp_code:
        return

    fin: dict[str, dict] = fetch_all_years(corp_code, "CFS", _ver=_CACHE_VER)
    if not fin:
        fin = fetch_all_years(corp_code, "OFS", _ver=_CACHE_VER)
    if not fin:
        return

    years_sorted = sorted(
        set(mktcap.keys()) & set(fin.keys()),
        key=lambda y: int(y),
    )
    if not years_sorted:
        return

    ev_vals:     list[float | None] = []
    ebitda_vals: list[float | None] = []
    ratio_vals:  list[float | None] = []

    for y in years_sorted:
        mc  = mktcap.get(y)
        d   = fin.get(y, {})
        bs  = d.get("bs", {})
        cf  = d.get("cf", {})
        isd = d.get("is", {})

        net_debt  = bs.get("netDebt")
        op_income = isd.get("opIncome")
        depre     = cf.get("depre")
        amort     = cf.get("amort")

        if op_income is not None or depre is not None or amort is not None:
            ebitda = (op_income or 0) + (depre or 0) + (amort or 0)
        else:
            ebitda = None

        ev    = (mc + (net_debt or 0)) if mc is not None else None
        ratio = round(ev / ebitda, 1) if (ev is not None and ebitda and ebitda > 0) else None

        ev_vals.append(ev)
        ebitda_vals.append(ebitda)
        ratio_vals.append(ratio)

    if not any(r is not None for r in ratio_vals):
        return

    _section_header(
        "EV / EBITDA 추이",
        "EV = 시가총액 + 순부채(차입금 − 현금) · EBITDA = 영업이익 + 감가상각비 + 무형자산상각비 (억 원 / 배)",
    )

    # ── 정의 카드 (차트 밖 HTML) ──────────────────────────────────────────────
    st.markdown(
        '<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;'
        'padding:10px 16px;margin-bottom:6px;font-size:.79rem;color:#1e293b;">'
        '<b>EV/EBITDA</b> — 기업가치(EV)가 EBITDA의 몇 배인지 나타내는 밸류에이션 지표. '
        '낮을수록 상대적 저평가.<br>'
        '<span style="color:#475569;">'
        '&nbsp;• <b>EV</b> (Enterprise Value) = 시가총액 + 순부채 (차입금 합계 − 현금및현금성자산)<br>'
        '&nbsp;• <b>EBITDA</b> = 영업이익 + 감가상각비 (D, Depreciation) + 무형자산상각비 (A, Amortization)<br>'
        '&nbsp;• 자본구조·세율·감가상각 정책 차이를 제거해 기업 간 수익성을 동일 기준으로 비교할 때 활용'
        '</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── KPI 요약 카드 ──────────────────────────────────────────────────────────
    latest_idx = len(years_sorted) - 1
    prev_idx   = latest_idx - 1 if latest_idx > 0 else None
    ly         = years_sorted[latest_idx]
    ev_now     = ev_vals[latest_idx]
    eb_now     = ebitda_vals[latest_idx]
    rt_now     = ratio_vals[latest_idx]
    rt_prev    = ratio_vals[prev_idx] if prev_idx is not None else None
    ev_prev    = ev_vals[prev_idx] if prev_idx is not None else None
    eb_prev    = ebitda_vals[prev_idx] if prev_idx is not None else None

    def _fmt_억(v):
        if v is None: return "-"
        return f"{v/10_000:.1f}조" if v >= 10_000 else f"{int(v):,}억"

    def _yoy(now, prev):
        if not (now and prev and prev > 0): return ""
        chg = (now - prev) / prev * 100
        sym = "▲" if chg >= 0 else "▼"
        clr = "#dc2626" if chg >= 0 else "#2563eb"
        return f'<span style="color:{clr};">{sym}{abs(chg):.1f}%</span> YoY'

    def _kc(label, value, sub="", hi=False):
        bg  = "#eff6ff" if hi else "#f8fafc"
        bdr = "2px solid #2563eb" if hi else "1px solid #e2e8f0"
        lc  = "#2563eb" if hi else "#64748b"
        return (
            f'<div style="flex:1;min-width:120px;text-align:center;padding:10px 8px;'
            f'border:{bdr};border-radius:8px;background:{bg};margin:3px;">'
            f'<div style="font-size:.65rem;color:{lc};font-weight:500;">{label}</div>'
            f'<div style="font-size:.98rem;font-weight:700;color:#1e293b;margin-top:4px;">{value}</div>'
            f'<div style="font-size:.61rem;color:#94a3b8;margin-top:2px;">{sub}</div>'
            f'</div>'
        )

    st.markdown(
        '<div style="display:flex;flex-wrap:wrap;margin:0 0 4px;">'
        + _kc(f"EV ({ly})",      _fmt_억(ev_now), _yoy(ev_now, ev_prev))
        + _kc(f"EBITDA ({ly})",  _fmt_억(eb_now), _yoy(eb_now, eb_prev))
        + _kc(f"EV/EBITDA ({ly})",
              f"{rt_now:.1f}x" if rt_now is not None else "-",
              f"전년 {rt_prev:.1f}x" if rt_prev is not None else "",
              hi=True)
        + '</div>',
        unsafe_allow_html=True,
    )

    # ── Plotly 차트 (annotation 없음, 막대 레이블 제거 → hover만) ─────────────
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=years_sorted,
        y=[v if v is not None else 0 for v in ev_vals],
        name="EV (억원)",
        marker_color=COLORS["blue"],
        opacity=0.7,
        yaxis="y",
        hovertemplate="%{x}<br>EV: %{y:,.0f}억원<extra></extra>",
    ))

    fig.add_trace(go.Bar(
        x=years_sorted,
        y=[v if v is not None else 0 for v in ebitda_vals],
        name="EBITDA (억원)",
        marker_color=COLORS["green"],
        opacity=0.7,
        yaxis="y",
        hovertemplate="%{x}<br>EBITDA: %{y:,.0f}억원<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=years_sorted,
        y=ratio_vals,
        name="EV/EBITDA (배)",
        mode="lines+markers+text",
        line=dict(color=COLORS["orange"], width=2.5),
        marker=dict(size=7, color=COLORS["orange"]),
        text=[f"{v:.1f}x" if v is not None else "" for v in ratio_vals],
        textposition="top center",
        textfont=dict(size=9, color=COLORS["orange"]),
        yaxis="y2",
        hovertemplate="%{x}<br>EV/EBITDA: %{y:.1f}x<extra></extra>",
    ))

    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items()
           if k not in ("yaxis", "xaxis", "margin", "height", "legend")},
        barmode="group",
        margin=dict(l=10, r=10, t=40, b=10),
        height=320,
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
        yaxis=dict(title="억 원", tickformat=",", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), side="left"),
        yaxis2=dict(title="EV/EBITDA (배)", overlaying="y", side="right",
                    tickfont=dict(color=COLORS["orange"]),
                    showgrid=False),
        legend=dict(orientation="h", y=1.05, x=1.0, xanchor="right",
                    bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)
# ══════════════════════════════════════════
#  주주 현황 탭 통합 렌더러
# ══════════════════════════════════════════
def _render_shareholder_tab(corp_code: str) -> None:
    """주주 현황 탭: 4가지 주주 섹션 통합 렌더링."""
    if not corp_code:
        st.caption("종목코드가 없는 비상장 기업은 주주 현황 데이터를 제공하지 않습니다.")
        return
    _render_shareholder_section(corp_code)
    _render_large_holdings(corp_code)
    _render_executive_reports(corp_code)

# ══════════════════════════════════════════
#  주가 차트 메인
# ══════════════════════════════════════════
def render_stock_chart(stock_code: str, corp_name: str,
                       corp_cls: str = "Y", corp_code: str = "") -> None:
    if not stock_code:
        return
    period_labels = ["6달", "2년", "3년", "월봉", "연봉"]
    sel = st.radio("기간", period_labels, index=2, horizontal=True,
                   key=f"sp_{stock_code}", label_visibility="collapsed")
    col_ma1, col_ma2 = st.columns(2)
    with col_ma1:
        ma_period1 = int(st.number_input("이평선1", min_value=0, max_value=300,
                                         value=25, key=f"ma1b_{stock_code}"))
    with col_ma2:
        ma_period2 = int(st.number_input("이평선2", min_value=0, max_value=300,
                                         value=200, key=f"ma2b_{stock_code}"))
    tf_map    = {"6달": "6mo", "2년": "24mo", "3년": "36mo", "월봉": "month", "연봉": "year"}
    title_map = {
        "6달":  f"{corp_name}  일봉 (최근 6개월)",
        "2년":  f"{corp_name}  일봉 (최근 2년)",
        "3년":  f"{corp_name}  일봉 (최근 3년)",
        "월봉": f"{corp_name}  월봉 (최근 10년)",
        "연봉": f"{corp_name}  연봉 (최근 20년)",
    }
    is_daily = sel in ("6달", "2년", "3년")
    with st.spinner("주가 데이터 조회 중..."):
        chart_data = fetch_stock_chart(stock_code, corp_cls, tf_map[sel], _ver=_CACHE_VER)
    if not chart_data:
        st.caption("주가 데이터를 불러올 수 없습니다.")
        return
    # 시세 정보 바 (일봉만)
    if is_daily:
        last       = chart_data[-1]
        prev_close = chart_data[-2]["close"] if len(chart_data) >= 2 else None
        chg_val    = round(last["close"] - prev_close, 0) if prev_close else 0
        chg_pct    = round(chg_val / prev_close * 100, 2) if prev_close else 0
        turnover   = round(last["close"] * last["volume"] / 1e8, 1)
        clr        = "#dc2626" if chg_val >= 0 else "#2563eb"
        sym        = "▲" if chg_val > 0 else ("▼" if chg_val < 0 else "━")
        info_cells = (
              _stock_info_cell("시가",   f"{last['open']:,.0f}")
            + _stock_info_cell("고가",   f"{last['high']:,.0f}", "#dc2626")
            + _stock_info_cell("저가",   f"{last['low']:,.0f}",  "#2563eb")
            + _stock_info_cell("종가",   f"{last['close']:,.0f}")
            + _stock_info_cell("대비",   f"{sym}{abs(int(chg_val)):,}", clr)
            + _stock_info_cell("등락률", f"{sym}{abs(chg_pct):.2f}%", clr)
            + _stock_info_cell("거래량", f"{last['volume']:,.0f}")
            + _stock_info_cell("거래대금", f"{turnover:,.0f}억")
        )
        st.markdown(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
            f'padding:6px 12px;margin-bottom:6px;display:flex;align-items:center;'
            f'justify-content:space-between;overflow-x:auto;">'
            f'<div style="white-space:nowrap;">{info_cells}</div>'
            f'<div style="font-size:.65rem;color:#94a3b8;white-space:nowrap;margin-left:12px;">{last["date"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    dates   = [d["date"]   for d in chart_data]
    opens_  = [d["open"]   for d in chart_data]
    highs   = [d["high"]   for d in chart_data]
    lows    = [d["low"]    for d in chart_data]
    closes  = [d["close"]  for d in chart_data]
    volumes = [d["volume"] for d in chart_data]
    vol_colors = ["#dc2626" if c >= o else "#2563eb" for c, o in zip(closes, opens_)]
    ma_cfg  = [(ma_period1, "#f59e0b"), (ma_period2, "#8b5cf6")]
    show_ma = is_daily and any(p > 0 and len(closes) >= p for p, _ in ma_cfg)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, row_heights=[0.72, 0.28])
    fig.add_trace(go.Candlestick(
        x=dates, open=opens_, high=highs, low=lows, close=closes, name="주가",
        increasing_line_color="#dc2626", increasing_fillcolor="#dc2626",
        decreasing_line_color="#2563eb", decreasing_fillcolor="#2563eb",
        line_width=1,
    ), row=1, col=1)
    if is_daily:
        for ma_p, ma_color in ma_cfg:
            if ma_p > 0 and len(closes) >= ma_p:
                ma_vals = [None] * (ma_p - 1) + [
                    round(sum(closes[j - ma_p:j]) / ma_p, 0)
                    for j in range(ma_p, len(closes) + 1)
                ]
                fig.add_trace(go.Scatter(
                    x=dates, y=ma_vals, mode="lines", name=f"이평선{ma_p}",
                    line=dict(color=ma_color, width=1.4),
                ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=dates, y=volumes, name="거래량",
        marker_color=vol_colors, opacity=0.75,
    ), row=2, col=1)
    fig.update_layout(
        title=dict(text=title_map[sel], font=dict(size=12, color="#1e293b"),
                   x=0, y=0.98, yanchor="top"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        font=dict(color="#64748b", size=11),
        xaxis_rangeslider_visible=False,
        margin=dict(l=8, r=8, t=80, b=8),
        height=420,
        showlegend=show_ma,
        legend=dict(orientation="h", yanchor="top", y=1.0, xanchor="right", x=1,
                    font=dict(size=10), bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
    )
    for row in [1, 2]:
        fig.update_xaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0", row=row, col=1)
        fig.update_yaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0", tickformat=",", row=row, col=1)
    if is_daily:
        fig.update_xaxes(type="category", nticks=min(len(dates), 12), tickangle=-45)
    fig.update_yaxes(title_text="거래량", tickformat=".3s", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)
    # 서브섹션 렌더링
    if corp_code:
        yf_data = _render_mktcap_chart(stock_code, corp_cls, corp_code)
        if yf_data and "__error__" not in yf_data:
            _render_per_pbr_chart(yf_data)
            _render_ev_ebitda_chart(yf_data, corp_code)
# ══════════════════════════════════════════
#  재무제표 탭
# ══════════════════════════════════════════
def _render_fs_tab(corp: dict) -> None:
    cache_key = f"{corp['corp_code']}_data"
    need_fetch = (
        cache_key not in st.session_state
        or st.session_state.get(cache_key + "_corp")  != corp["corp_code"]
        or st.session_state.get(cache_key + "_ver")   != _CACHE_VER
        or st.session_state.get(cache_key + "_years") != (YEARS[0], YEARS[-1])
    )
    if need_fetch:
        with st.spinner(f"{corp['corp_name']} 재무데이터 수집 중 (K-IFRS 기준 최대 15년)..."):
            cfs = fetch_all_years(corp["corp_code"], "CFS")
            ofs = fetch_all_years(corp["corp_code"], "OFS")
            if cfs and ofs:
                # CFS 우선, CFS에 없는 연도는 OFS로 보완 (금융지주·은행 등 CFS 이력이 짧은 경우 대응)
                data   = {**ofs, **cfs}
                fs_div = "CFS+OFS"
            elif cfs:
                data   = cfs
                fs_div = "CFS"
            elif ofs:
                data   = ofs
                fs_div = "OFS"
            else:
                data   = {}
                fs_div = "-"
        st.session_state[cache_key]            = data
        st.session_state[cache_key + "_fs"]    = fs_div
        st.session_state[cache_key + "_corp"]  = corp["corp_code"]
        st.session_state[cache_key + "_ver"]   = _CACHE_VER
        st.session_state[cache_key + "_years"] = (YEARS[0], YEARS[-1])
    else:
        data   = st.session_state[cache_key]
        fs_div = st.session_state.get(cache_key + "_fs", "CFS")
    if not data:
        st.error("재무데이터를 불러올 수 없습니다.")
        return

    # ── D&A ZIP 폴백: fnlttSinglAcntAll 에서 D&A 항목이 누락된 연도에 대해
    #    DART 사업보고서 ZIP의 재무제표 주석 HTML(현금흐름표 조정내역)을 파싱해 보완.
    #    결과는 session_state 내 data dict를 직접 갱신 (현 세션 내 중복 다운로드 방지).
    _missing_da_years = [
        y for y in sorted(data.keys())
        if data[y].get("cf", {}).get("depre") is None
    ]
    if _missing_da_years:
        with st.spinner(
            f"감가상각비 데이터 보완 중 — DART 재무제표 주석 분석 "
            f"({corp['corp_name']}, {', '.join(_missing_da_years)})..."
        ):
            for _y in _missing_da_years:
                _dep, _amt = _fetch_da_from_dart_zip(corp["corp_code"], int(_y))
                if _dep is not None:
                    data[_y]["cf"]["depre"] = _dep
                    data[_y]["cf"]["amort"] = _amt

    years    = sorted(data.keys())
    fs_label_map = {"CFS": "연결재무제표", "OFS": "별도재무제표",
                    "CFS+OFS": "연결(최근)+별도(과거) 혼합", "-": ""}
    fs_label = fs_label_map.get(fs_div, fs_div)
    st.caption(f"{fs_label} 기준 · {years[0]}~{years[-1]} · 단위: 억원")
    ly      = years[-1]
    py      = years[-2] if len(years) >= 2 else None
    ld      = data[ly]
    pd_data = data[py] if py else {}
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("매출액 (최근)",   ld["is"].get("revenue"),  pd_data.get("is", {}).get("revenue"))
        kpi_card("자산총계 (최근)", ld["bs"].get("assets"),   pd_data.get("bs", {}).get("assets"))
    with c2:
        kpi_card("영업이익 (최근)", ld["is"].get("opIncome"), pd_data.get("is", {}).get("opIncome"))
        kpi_card("부채비율",
                 pct(ld["bs"].get("liabilities"), ld["bs"].get("equity")),
                 pct(pd_data.get("bs", {}).get("liabilities"), pd_data.get("bs", {}).get("equity")),
                 is_pct=True, invert=True)
    with c3:
        kpi_card("순이익 (최근)",  ld["is"].get("netIncome"), pd_data.get("is", {}).get("netIncome"))
        kpi_card("영업이익률",
                 pct(ld["is"].get("opIncome"), ld["is"].get("revenue")),
                 pct(pd_data.get("is", {}).get("opIncome"), pd_data.get("is", {}).get("revenue")),
                 is_pct=True)
    st.divider()
    sub_bs, sub_is, sub_cf = st.tabs(["📋 재무상태표", "💰 손익계산서", "💧 현금흐름표"])
    with sub_bs:
        st.plotly_chart(make_bar(years, {
            "자산총계": [data[y]["bs"].get("assets")     for y in years],
            "부채총계": [data[y]["bs"].get("liabilities") for y in years],
            "자본총계": [data[y]["bs"].get("equity")      for y in years],
        }, "자산 · 부채 · 자본 (억원)"), use_container_width=True)
        st.plotly_chart(make_line(years, {
            "부채비율(%)":     [pct(data[y]["bs"].get("liabilities"), data[y]["bs"].get("equity")) for y in years],
            "자기자본비율(%)": [pct(data[y]["bs"].get("equity"),      data[y]["bs"].get("assets"))  for y in years],
        }, "부채비율 & 자기자본비율", is_pct=True), use_container_width=True)
        st.plotly_chart(make_line(years, {
            "이익잉여금": [data[y]["bs"].get("retainedEarnings") for y in years],
        }, "이익잉여금 추이 (억원)"), use_container_width=True)
        rows = []
        for y in reversed(years):
            b = data[y]["bs"]
            rows.append({
                "연도": y, "자산총계": fmt(b.get("assets")),
                "부채총계": fmt(b.get("liabilities")), "자본총계": fmt(b.get("equity")),
                "이익잉여금": fmt(b.get("retainedEarnings")),
                "부채비율":   f"{pct(b.get('liabilities'),b.get('equity')):.1f}%" if pct(b.get("liabilities"), b.get("equity")) else "-",
                "자기자본비율": f"{pct(b.get('equity'),b.get('assets')):.1f}%" if pct(b.get("equity"), b.get("assets")) else "-",
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
    with sub_is:
        st.plotly_chart(make_bar(years, {
            "매출액":   [data[y]["is"].get("revenue")   for y in years],
            "영업이익": [data[y]["is"].get("opIncome")  for y in years],
            "순이익":   [data[y]["is"].get("netIncome") for y in years],
        }, "매출 · 영업이익 · 순이익 (억원)"), use_container_width=True)
        st.plotly_chart(make_line(years, {
            "영업이익률(%)": [pct(data[y]["is"].get("opIncome"),  data[y]["is"].get("revenue")) for y in years],
            "순이익률(%)":   [pct(data[y]["is"].get("netIncome"), data[y]["is"].get("revenue")) for y in years],
        }, "이익률 추이", is_pct=True), use_container_width=True)
        rows = []
        for y in reversed(years):
            s = data[y]["is"]
            rows.append({
                "연도": y, "매출액": fmt(s.get("revenue")),
                "영업이익": fmt(s.get("opIncome")), "순이익": fmt(s.get("netIncome")),
                "영업이익률": f"{pct(s.get('opIncome'),s.get('revenue')):.1f}%" if pct(s.get("opIncome"), s.get("revenue")) else "-",
                "순이익률":   f"{pct(s.get('netIncome'),s.get('revenue')):.1f}%" if pct(s.get("netIncome"), s.get("revenue")) else "-",
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)
    with sub_cf:
        st.plotly_chart(make_bar(years, {
            "영업CF": [data[y]["cf"].get("opCF")  for y in years],
            "투자CF": [data[y]["cf"].get("invCF") for y in years],
            "재무CF": [data[y]["cf"].get("finCF") for y in years],
        }, "현금흐름 (억원)"), use_container_width=True)
        st.plotly_chart(make_line(years, {
            "기말현금": [data[y]["cf"].get("endCash") for y in years],
        }, "기말현금 추이 (억원)"), use_container_width=True)

        # ── EBITDA 구성 차트 ──────────────────────────────────────
        # EBITDA = 영업이익(IS) + 감가상각비(D, CF조정항목) + 무형자산상각비(A, CF조정항목)
        has_da = any(
            data[y]["cf"].get("depre") is not None
            or data[y]["cf"].get("amort") is not None
            for y in years
        )
        if has_da:
            _section_header(
                "EBITDA 구성",
                "감가상각비(D) + 무형자산상각비(A) — 현금흐름표 영업활동 조정항목 기준 (억원)",
            )
            st.plotly_chart(make_bar(years, {
                "감가상각비(D)":     [data[y]["cf"].get("depre") for y in years],
                "무형자산상각비(A)": [data[y]["cf"].get("amort") for y in years],
            }, "감가상각비 · 무형자산상각비 (억원)"), use_container_width=True)

            def _ebitda(y: str) -> int | None:
                # EBITDA = 영업이익 + 감가상각비 + 무형자산상각비
                op  = data[y]["is"].get("opIncome")
                dep = data[y]["cf"].get("depre")
                amt = data[y]["cf"].get("amort")
                if op is None and dep is None and amt is None:
                    return None
                return (op or 0) + (dep or 0) + (amt or 0)

            st.plotly_chart(make_line(years, {
                "EBITDA": [_ebitda(y) for y in years],
            }, "EBITDA 추이 (억원)  =  영업이익 + 감가상각비 + 무형자산상각비"),
                use_container_width=True)

        rows = []
        for y in reversed(years):
            c     = data[y]["cf"]
            dep_v = c.get("depre")
            amt_v = c.get("amort")
            op_v  = data[y]["is"].get("opIncome")
            # EBITDA 계산
            ebitda_v = (
                (op_v or 0) + (dep_v or 0) + (amt_v or 0)
                if (op_v is not None or dep_v is not None or amt_v is not None)
                else None
            )
            rows.append({
                "연도":          y,
                "영업CF":        fmt(c.get("opCF")),
                "투자CF":        fmt(c.get("invCF")),
                "재무CF":        fmt(c.get("finCF")),
                "기말현금":      fmt(c.get("endCash")),
                "감가상각비(D)":     fmt(dep_v),
                "무형자산상각비(A)": fmt(amt_v),
                "EBITDA":        fmt(ebitda_v),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)

        # ── D&A "-" 시 DART CF 원본 계정명 확인 expander ──────────────
        if not has_da:
            # 가장 최근 연도 CF accounts 가져오기
            recent_cf_accounts: list[tuple[str, str]] = []
            for y in reversed(years):
                accs = data[y]["cf"].get("_cf_accounts", [])
                if accs:
                    recent_cf_accounts = accs
                    _debug_year = y
                    break
            if recent_cf_accounts:
                with st.expander(
                    "⚠️ 감가상각비 데이터 없음 — DART CF 계정명 확인",
                    expanded=False,
                ):
                    st.caption(
                        f"**{_debug_year}년** DART 현금흐름표 원본 계정 목록입니다. "
                        "감가상각 관련 계정명을 확인해 알려주시면 ACC dict에 추가하겠습니다. "
                        "thstrm_amount / thstrm_add_amt 모두 비어 있으면 DART API 자체 미제공입니다."
                    )
                    _DA_KEYWORDS = ("상각", "감가", "depreci", "amort")
                    highlighted, others = [], []
                    for row in recent_cf_accounts:
                        nm = row.get("계정명", "")
                        entry = {
                            "계정명":          nm,
                            "thstrm_amount":   row.get("thstrm_amount",  ""),
                            "thstrm_add_amt":  row.get("thstrm_add_amt", ""),
                            "비고": "✅ D&A 의심" if any(k in nm for k in _DA_KEYWORDS) else "",
                        }
                        if any(k in nm for k in _DA_KEYWORDS):
                            highlighted.append(entry)
                        else:
                            others.append(entry)
                    if highlighted:
                        st.markdown("**감가상각 관련 의심 계정:**")
                        st.dataframe(highlighted, hide_index=True, use_container_width=True)
                    st.markdown("**전체 CF 계정 목록:**")
                    st.dataframe(highlighted + others, hide_index=True, use_container_width=True)
# ══════════════════════════════════════════
#  공시·뉴스 탭
# ══════════════════════════════════════════
def _render_news_tab(corp: dict) -> None:
    st.subheader("📢 최근 공시")
    with st.spinner("공시 조회 중..."):
        discs, disc_label = fetch_disclosures(corp["corp_code"])
    if discs:
        for d in discs:
            link_html  = (f'<a href="{d["link"]}" target="_blank" style="color:#2563eb;text-decoration:none;">'
                          f'{d["report_nm"]}</a>') if d["link"] else d["report_nm"]
            badge_html = (f'<span style="background:#f1f5f9;color:#475569;font-size:.65rem;'
                          f'border-radius:3px;padding:1px 5px;margin-right:5px;">{d["corp_cls"]}</span>'
                          ) if d["corp_cls"] else ""
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid #f1f5f9;">'
                f'{badge_html}<span style="font-size:.88rem;color:#1e293b;">{link_html}</span>'
                f'<span style="float:right;font-size:.72rem;color:#94a3b8;">'
                f'{d["rcept_dt"]} · {d["flr_nm"]}</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption(f"공시 없음 — {disc_label}")
    st.divider()
    st.subheader("📰 최근 뉴스")
    with st.spinner("뉴스 수집 중..."):
        news = fetch_news(corp["corp_name"])
    if news:
        for n in news:
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid #f1f5f9;">'
                f'<a href="{n["link"]}" target="_blank" style="font-size:.88rem;color:#1e293b;text-decoration:none;">'
                f'{n["title"]}</a>'
                f'<div style="font-size:.72rem;color:#94a3b8;margin-top:2px;">'
                f'{n["source"]}  ·  {n["date"]}</div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("뉴스를 불러올 수 없습니다.")
# ══════════════════════════════════════════
#  직원 현황 탭
# ══════════════════════════════════════════
def _render_employee_tab(corp: dict) -> None:
    with st.spinner("직원 현황 조회 중..."):
        emp_data = fetch_employee_status(corp["corp_code"], _ver=_CACHE_VER)
    if not emp_data:
        st.caption("직원 현황 데이터를 찾을 수 없습니다.")
        return
    eyears = sorted(emp_data.keys())
    # 정규직 누적 막대 + 합계 라인
    fig_emp = go.Figure()
    fig_emp.add_trace(go.Bar(
        name="남 정규직", x=eyears,
        y=[emp_data[y].get("male", 0) for y in eyears],
        marker_color="#2563eb",
        text=[f'{emp_data[y].get("male", 0):,}' for y in eyears],
        textposition="inside", textfont=dict(size=9, color="white"),
    ))
    fig_emp.add_trace(go.Bar(
        name="여 정규직", x=eyears,
        y=[emp_data[y].get("female", 0) for y in eyears],
        marker_color="#ec4899",
        text=[f'{emp_data[y].get("female", 0):,}' for y in eyears],
        textposition="inside", textfont=dict(size=9, color="white"),
    ))
    fig_emp.add_trace(go.Scatter(
        name="전체합계", x=eyears,
        y=[emp_data[y].get("total", 0) for y in eyears],
        mode="lines+markers+text",
        line=dict(color="#f59e0b", width=2), marker=dict(size=5),
        text=[f'{emp_data[y].get("total", 0):,}' for y in eyears],
        textposition="top center", textfont=dict(size=9, color="#b45309"),
    ))
    fig_emp.update_layout(
        title_text="정규직 직원 수 추이 (명)", title_font_color="#1e293b",
        title_font_size=12, barmode="stack", **PLOTLY_LAYOUT,
    )
    st.plotly_chart(fig_emp, use_container_width=True)
    # 평균 근속연수
    fig_tenure = go.Figure()
    for sex, color in [("m", "#2563eb"), ("f", "#ec4899")]:
        label = "남" if sex == "m" else "여"
        fig_tenure.add_trace(go.Scatter(
            name=label, x=eyears,
            y=[emp_data[y].get(f"avg_tenure_{sex}", 0) for y in eyears],
            mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=5),
        ))
    fig_tenure.update_layout(
        title_text="평균 근속연수 (년)", title_font_color="#1e293b",
        title_font_size=12, **PLOTLY_LAYOUT,
    )
    fig_tenure.update_yaxes(ticksuffix="년", gridcolor="#e2e8f0")
    st.plotly_chart(fig_tenure, use_container_width=True)
    # 1인 평균 연봉
    sal_years = [y for y in eyears
                 if emp_data[y].get("salary_m") or emp_data[y].get("salary_f")]
    if sal_years:
        fig_sal = go.Figure()
        for sex, color, label in [("m", "#2563eb", "남"), ("f", "#ec4899", "여")]:
            vals = [_to_man(emp_data[y].get(f"salary_{sex}")) for y in sal_years]
            fig_sal.add_trace(go.Bar(
                name=label, x=sal_years, y=vals, marker_color=color,
                text=[f'{v:,}만' for v in vals],
                textposition="outside", textfont=dict(size=9),
            ))
        fig_sal.update_layout(
            title_text="1인 평균 연봉 (만원)", title_font_color="#1e293b",
            title_font_size=12, barmode="group", **PLOTLY_LAYOUT,
        )
        fig_sal.update_yaxes(ticksuffix="만", gridcolor="#e2e8f0")
        st.plotly_chart(fig_sal, use_container_width=True)
    # 데이터 테이블
    tbl_rows = [
        {
            "연도": y,
            "전체합계":    f'{emp_data[y].get("total", 0):,}',
            "남 정규직":   f'{emp_data[y].get("male", 0):,}',
            "여 정규직":   f'{emp_data[y].get("female", 0):,}',
            "남 계약직":   f'{emp_data[y].get("male_contract", 0):,}',
            "여 계약직":   f'{emp_data[y].get("female_contract", 0):,}',
            "남 근속(년)": emp_data[y].get("avg_tenure_m", "-"),
            "여 근속(년)": emp_data[y].get("avg_tenure_f", "-"),
            "남 연봉":     _sal_fmt(emp_data[y].get("salary_m")),
            "여 연봉":     _sal_fmt(emp_data[y].get("salary_f")),
        }
        for y in reversed(eyears)
    ]
    st.dataframe(tbl_rows, hide_index=True, use_container_width=True)
# ══════════════════════════════════════════
#  3중 적정주가 산정 (PER · PBR · DCF)
# ══════════════════════════════════════════
def compute_fair_values(
    corp_code: str,
    stock_code: str,
    corp_cls: str,
    wacc: float       = 0.10,
    terminal_g: float = 0.02,
    fcf_growth: float = 0.05,
    proj_years: int   = 5,
    _ver: int         = _CACHE_VER,
) -> dict:
    """
    3중 적정주가 산정 공식 (PER · PBR · DCF)
    ==========================================

    ① PER 기반 적정주가
       EPS(원)       = 당기순이익(억원) × 1억 ÷ 발행주식수
       과거평균PER   = mean( PER_t  for t in 수집된 과거 연도 )
       PER 적정주가  = 과거평균PER × EPS

    ② PBR 기반 적정주가
       BPS(원)       = 자기자본총계(억원) × 1억 ÷ 발행주식수
       과거평균PBR   = mean( PBR_t  for t in 수집된 과거 연도 )
       PBR 적정주가  = 과거평균PBR × BPS

    ③ DCF 내재가치 (잉여현금흐름 할인 모형, Discounted Cash Flow)
       FCF₀(원)      = 최근 3개년 평균 영업활동현금흐름(억원) × 1억
                       ※ 영업CF를 FCF 근사치로 사용 (CAPEX 별도 조정 불가 시)

       현금흐름 PV 합계 (N년간 FCF 현재가치 합):
         PV_FCF = Σ_{t=1}^{N}  FCF₀ × (1 + g_fcf)^t
                                ─────────────────────
                                     (1 + WACC)^t

       잔존가치 (Terminal Value, TV) — 고든성장모형 (Gordon Growth Model):
         FCF_N  = FCF₀ × (1 + g_fcf)^N              ← N년차 FCF
         TV     = FCF_N × (1 + g_terminal)
                  ────────────────────────            ← 영구성장 현금흐름
                      WACC − g_terminal
         PV_TV  = TV ÷ (1 + WACC)^N                 ← TV 현재가치

       기업가치 (Enterprise Value, EV):
         EV     = PV_FCF + PV_TV

       자기자본가치 (Equity Value):
         순부채 = 부채총계(억원) × 1억 − 기말현금(억원) × 1억
         EqV    = EV − 순부채

       DCF 주당 내재가치:
         DCF/주 = max(EqV, 0) ÷ 발행주식수

    ④ 컨센서스 (단순평균):
         Consensus = mean( [PER적정주가, PBR적정주가, DCF내재가치] 중 유효값 )
    """
    result: dict[str, Any] = {"error": None}
    if not _YF_AVAILABLE or not stock_code or not corp_code:
        result["error"] = "비상장 또는 데이터 부족"
        return result
    try:
        # ── 주가·주식수 (캐시된 fetch_yf_annual_data 활용) ──────────
        yf_data = fetch_yf_annual_data(stock_code, corp_cls, corp_code, _ver=_ver)
        if "__error__" in yf_data:
            result["error"] = yf_data["__error__"]
            return result

        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            result["error"] = "ticker 없음 (KS/KQ 모두 시도)"
            return result
        ticker, _ = resolved
        t = yf.Ticker(ticker)

        shares: int | None = None
        try:
            shares = t.fast_info.shares
        except Exception:
            pass
        if not shares:
            shares = (t.info or {}).get("sharesOutstanding")

        current_price: float | None = None
        try:
            current_price = float(t.fast_info.last_price)
        except Exception:
            pass

        if not shares or shares <= 0:
            result["error"] = "발행주식수 없음"
            return result

        # ── 재무데이터 (fetch_all_years 캐시 활용) ──────────────────
        cfs = fetch_all_years(corp_code, "CFS", _ver=_ver)
        ofs = fetch_all_years(corp_code, "OFS", _ver=_ver)
        fin_data = {**ofs, **cfs} if (cfs and ofs) else (cfs or ofs or {})
        if not fin_data:
            result["error"] = "재무데이터 없음"
            return result

        years_sorted = sorted(fin_data.keys(), reverse=True)
        latest_yr    = years_sorted[0] if years_sorted else None
        if not latest_yr:
            result["error"] = "연도 데이터 없음"
            return result

        ld         = fin_data[latest_yr]
        net_income = ld["is"].get("netIncome")   # 억원
        equity     = ld["bs"].get("equity")       # 억원
        liab       = ld["bs"].get("liabilities")  # 억원
        end_cash   = ld["cf"].get("endCash")      # 억원

        # ── ① PER 적정주가 ──────────────────────────────────────────
        # EPS = 당기순이익(억원) × 1e8 / 발행주식수
        # PER 적정주가 = 과거평균PER × EPS
        per_pbr   = yf_data.get("per_pbr", {})
        hist_pers = [
            v["PER"] for v in per_pbr.values()
            if isinstance(v.get("PER"), (int, float)) and v["PER"] > 0
        ]
        avg_per   = round(sum(hist_pers) / len(hist_pers), 1) if hist_pers else None
        per_fair: float | None = None
        if avg_per and net_income and net_income > 0:
            eps      = net_income * 1e8 / shares   # 주당순이익(원)
            per_fair = round(avg_per * eps, 0)

        # ── ② PBR 적정주가 ──────────────────────────────────────────
        # BPS = 자기자본총계(억원) × 1e8 / 발행주식수
        # PBR 적정주가 = 과거평균PBR × BPS
        hist_pbrs = [
            v["PBR"] for v in per_pbr.values()
            if isinstance(v.get("PBR"), (int, float)) and v["PBR"] > 0
        ]
        avg_pbr   = round(sum(hist_pbrs) / len(hist_pbrs), 2) if hist_pbrs else None
        pbr_fair: float | None = None
        if avg_pbr and equity and equity > 0:
            bps      = equity * 1e8 / shares       # 주당순자산(원)
            pbr_fair = round(avg_pbr * bps, 0)

        # ── ③ DCF 내재가치 ──────────────────────────────────────────
        # FCF₀: 최근 최대 3개년 영업CF 평균 (억원 → 원)
        opcfs = [
            fin_data[y]["cf"].get("opCF")
            for y in years_sorted[:3]
            if fin_data[y]["cf"].get("opCF") is not None
        ]
        dcf_fair: float | None     = None
        pv_fcf_total: float | None = None
        pv_tv: float | None        = None
        fcf0_eok: float | None     = None   # 억원 단위 (표시용)

        if opcfs and wacc > terminal_g:
            fcf0     = (sum(opcfs) / len(opcfs)) * 1e8   # 원 단위
            fcf0_eok = sum(opcfs) / len(opcfs)            # 억원 (표시용)

            # 현금흐름 PV 합계: Σ FCF₀(1+g_fcf)^t / (1+WACC)^t, t=1..N
            pv_fcf_total = sum(
                fcf0 * (1 + fcf_growth) ** t / (1 + wacc) ** t
                for t in range(1, proj_years + 1)
            )

            # 잔존가치(Terminal Value): Gordon Growth Model
            fcf_n = fcf0 * (1 + fcf_growth) ** proj_years   # N년차 FCF
            tv    = fcf_n * (1 + terminal_g) / (wacc - terminal_g)
            pv_tv = tv / (1 + wacc) ** proj_years            # TV 현재가치

            # EV = PV_FCF + PV_TV
            # 순부채 = 부채총계 - 기말현금 (원 단위)
            ev       = pv_fcf_total + pv_tv
            net_debt = ((liab or 0) - (end_cash or 0)) * 1e8
            eq_val   = ev - net_debt
            if eq_val > 0:
                dcf_fair = round(eq_val / shares, 0)

        # ── ④ 컨센서스 (유효값 단순평균) ────────────────────────────
        valids    = [v for v in [per_fair, pbr_fair, dcf_fair] if v is not None]
        consensus = round(sum(valids) / len(valids), 0) if valids else None

        return {
            "error":         None,
            "current_price": current_price,
            "per_fair":      per_fair,
            "pbr_fair":      pbr_fair,
            "dcf_fair":      dcf_fair,
            "consensus":     consensus,
            "avg_per":       avg_per,
            "avg_pbr":       avg_pbr,
            # DCF 세부 (억원)
            "pv_fcf":        round(pv_fcf_total / 1e8, 0) if pv_fcf_total else None,
            "pv_tv":         round(pv_tv / 1e8, 0)        if pv_tv        else None,
            "fcf0_eok":      round(fcf0_eok, 0)           if fcf0_eok     else None,
            # 파라미터
            "latest_yr":     latest_yr,
            "shares":        shares,
            "proj_years":    proj_years,
            "wacc":          wacc,
            "terminal_g":    terminal_g,
            "fcf_growth":    fcf_growth,
        }
    except Exception as e:
        return {"error": str(e)}


def _render_valuation_card(fv: dict) -> None:
    """
    PER + PBR + DCF 3중 적정주가 요약 카드 렌더러.

    카드 레이아웃:
      ┌─ 헤더: 제목 · 현재가 · 기준연도 ────────────────────────────┐
      │  ① PER  │  ② PBR  │  ③ DCF  │  컨센서스(하이라이트)       │
      └──────────────────────────────────────────────────────────────┘

    각 셀:
      - 적정주가(원)  +  등락률(현재가 대비 ▲/▼%)
      - sub1: 산정근거 (avg PER·PBR, FCF PV · TV PV)
      - sub2: 산식 한 줄 요약
    """
    if fv.get("error"):
        # 비상장·데이터 부족은 조용히 skip
        skip_msgs = {"비상장 또는 데이터 부족", "ticker 없음 (KS/KQ 모두 시도)"}
        if fv["error"] not in skip_msgs:
            st.caption(f"적정주가 산정 불가: {fv['error']}")
        return

    cur = fv.get("current_price")

    def _upside(fair: float | None) -> str:
        """적정주가 대비 현재가 프리미엄 뱃지 HTML.
        양수 = 현재가가 목표가보다 높다(고평가, 빨강), 음수 = 저평가(초록).
        """
        if fair is None or cur is None or cur == 0 or fair == 0:
            return ""
        up  = (cur - fair) / fair * 100        # 현재가가 목표가보다 얼마나 높은가
        sym = "▲" if up >= 0 else "▼"
        clr = "#dc2626" if up >= 0 else "#16a34a"   # 고평가=빨강, 저평가=초록
        return (
            f'<span style="font-size:.68rem;color:{clr};margin-left:4px;">'
            f'{sym}{abs(up):.1f}%</span>'
        )

    def _fair_cell(label: str, fair: float | None,
                   sub1: str = "", sub2: str = "",
                   highlight: bool = False) -> str:
        """적정가 셀 HTML 블록."""
        border = "2px solid #2563eb" if highlight else "1px solid #e2e8f0"
        bg     = "#eff6ff"           if highlight else "#ffffff"
        lbl_clr = "#2563eb"          if highlight else "#475569"
        if fair is None:
            val_html = (
                '<div style="font-size:.82rem;color:#94a3b8;margin-top:6px;">산정 불가</div>'
            )
        else:
            val_html = (
                f'<div style="font-size:1.05rem;font-weight:700;color:#1e293b;margin-top:6px;">'
                f'{int(fair):,}원{_upside(fair)}</div>'
            )
        s1 = (f'<div style="font-size:.63rem;color:#64748b;margin-top:4px;">{sub1}</div>'
              if sub1 else "")
        s2 = (f'<div style="font-size:.60rem;color:#94a3b8;margin-top:1px;">{sub2}</div>'
              if sub2 else "")
        return (
            f'<div style="flex:1;min-width:140px;text-align:center;'
            f'padding:12px 8px;border:{border};border-radius:8px;'
            f'background:{bg};margin:4px;">'
            f'<div style="font-size:.68rem;font-weight:600;color:{lbl_clr};">{label}</div>'
            f'{val_html}{s1}{s2}'
            f'</div>'
        )

    def _cur_card() -> str:
        """④ 현재가 기준 셀 HTML (보라색 테두리, 참조용)."""
        if cur is None:
            return ""
        con = fv.get("consensus")
        if con and con > 0:
            prem = (cur - con) / con * 100
            sym  = "▲" if prem >= 0 else "▼"
            clr  = "#dc2626" if prem >= 0 else "#16a34a"
            con_line = (
                f'컨센서스 대비 '
                f'<span style="color:{clr};font-weight:600;">{sym}{abs(prem):.1f}%</span>'
            )
        else:
            con_line = ""
        return (
            f'<div style="flex:1;min-width:140px;text-align:center;'
            f'padding:12px 8px;border:1.5px solid #7c3aed;border-radius:8px;'
            f'background:#faf5ff;margin:4px;">'
            f'<div style="font-size:.68rem;font-weight:600;color:#7c3aed;">④ 현재가 (기준)</div>'
            f'<div style="font-size:1.05rem;font-weight:700;color:#1e293b;margin-top:6px;">'
            f'{int(cur):,}원</div>'
            f'<div style="font-size:.63rem;color:#64748b;margin-top:4px;">{con_line}</div>'
            f'<div style="font-size:.60rem;color:#94a3b8;margin-top:1px;">실시간 시장가격</div>'
            f'</div>'
        )

    cur_html = f'{int(cur):,}원' if cur else "현재가 없음"

    # ① PER 셀 설명
    per_sub1 = f"과거평균 PER {fv['avg_per']}x" if fv.get("avg_per") else ""
    per_sub2 = "= 과거평균PER × EPS"

    # ② PBR 셀 설명
    pbr_sub1 = f"과거평균 PBR {fv['avg_pbr']}x" if fv.get("avg_pbr") else ""
    pbr_sub2 = "= 과거평균PBR × BPS"

    # ③ DCF 셀 설명 (PV_FCF + PV_TV 표시)
    dcf_parts: list[str] = []
    if fv.get("pv_fcf") is not None:
        dcf_parts.append(f"현금흐름PV {int(fv['pv_fcf']):,}억")
    if fv.get("pv_tv") is not None:
        dcf_parts.append(f"잔존가치PV {int(fv['pv_tv']):,}억")
    dcf_sub1 = " · ".join(dcf_parts)
    dcf_sub2 = (
        f"WACC {fv['wacc']*100:.1f}% · g∞ {fv['terminal_g']*100:.1f}%"
        f" · FCFg {fv['fcf_growth']*100:.1f}% · {fv['proj_years']}년"
    )

    # ④ 컨센서스 셀 설명
    valids_n  = sum(1 for v in [fv.get("per_fair"), fv.get("pbr_fair"), fv.get("dcf_fair")]
                    if v is not None)
    con_sub1  = "PER + PBR + DCF 단순평균"
    con_sub2  = f"(유효값 {valids_n}개 평균)" if valids_n < 3 else ""

    st.markdown(
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;'
        f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:12px 14px;margin:8px 0 4px 0;">'
        # 헤더
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'margin-bottom:8px;">'
        f'<span style="font-size:.8rem;font-weight:700;color:#1e293b;">📐 3중 적정주가 산정</span>'
        f'<span style="font-size:.72rem;color:#64748b;">'
        f'현재가 <b style="color:#1e293b;">{cur_html}</b>'
        f'&nbsp;·&nbsp;기준 {fv.get("latest_yr","")}년 재무</span>'
        f'</div>'
        # 4개 셀
        f'<div style="display:flex;flex-wrap:wrap;">'
        + _fair_cell("① PER 적정주가",  fv.get("per_fair"),  per_sub1, per_sub2)
        + _fair_cell("② PBR 적정주가",  fv.get("pbr_fair"),  pbr_sub1, pbr_sub2)
        + _fair_cell("③ DCF 내재가치",  fv.get("dcf_fair"),  dcf_sub1, dcf_sub2)
        + _cur_card()
        + _fair_cell("컨센서스 (평균)", fv.get("consensus"), con_sub1, con_sub2,
                     highlight=True)
        + f'</div></div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════
#  검색 헬퍼
# ══════════════════════════════════════════
def _on_search_enter() -> None:
    _run_search(st.session_state.get("_search_input", ""))
def _run_search(q: str) -> None:
    """검색 실행 — 가장 일치하는 법인을 session_state에 저장."""
    q = (q or "").strip()
    if not q:
        return
    try:
        corps = load_corp_list()
        results = search_corps(q, corps)
    except requests.exceptions.ConnectionError:
        st.session_state["selected_corp"] = None
        st.session_state["_search_no_result"] = ""
        st.error("DART API 서버에 연결할 수 없습니다. 네트워크 상태를 확인하세요.")
        return
    except requests.exceptions.Timeout:
        st.session_state["selected_corp"] = None
        st.session_state["_search_no_result"] = ""
        st.error("DART API 응답 시간이 초과되었습니다. 잠시 후 다시 시도하세요.")
        return
    except requests.exceptions.HTTPError as e:
        st.session_state["selected_corp"] = None
        st.session_state["_search_no_result"] = ""
        code = e.response.status_code if e.response is not None else "?"
        if code == 401:
            st.error("DART API 키가 유효하지 않습니다. Streamlit Secrets의 DART_KEY를 확인하세요.")
        else:
            st.error(f"DART API 오류 (HTTP {code}): {e}")
        return
    except Exception as e:
        st.session_state["selected_corp"] = None
        st.session_state["_search_no_result"] = ""
        st.error(f"기업 목록 조회 중 오류 발생: {e}")
        return
    if results:
        st.session_state["selected_corp"]     = results[0]
        st.session_state["_search_no_result"] = ""
    else:
        st.session_state["selected_corp"]     = None
        st.session_state["_search_no_result"] = q
# ══════════════════════════════════════════
#  메인 UI
# ══════════════════════════════════════════
def main() -> None:
    if not DART_KEY:
        st.error(
            "DART API 키가 설정되지 않았습니다.\n\n"
            "**로컬 실행:** `.streamlit/secrets.toml` 에 `DART_KEY = \"your_key\"` 추가\n\n"
            "**Streamlit Cloud:** 앱 설정 → Secrets 에 동일하게 입력"
        )
        st.stop()
    # 스티키 헤더
    st.markdown(
        """
        <style>
        .stickytop { position: sticky; top: 0; z-index: 999; background: #f8fafc;
                     padding: 8px 0 6px; border-bottom: 1px solid #e2e8f0; margin-bottom: 8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.container():
        st.markdown('<div class="stickytop">', unsafe_allow_html=True)
        col_logo, col_search, col_btn = st.columns([1, 5, 1])
        with col_logo:
            st.markdown(
                '<span class="dart-title" style="font-size:1.1rem;font-weight:800;'
                'color:#2563eb;white-space:nowrap;">📊 DART 기업 분석</span>',
                unsafe_allow_html=True,
            )
        with col_search:
            st.text_input(
                "기업 검색",
                placeholder="회사명 또는 종목코드 입력 (예: 삼성전자, 005930)",
                key="_search_input",
                on_change=_on_search_enter,
                label_visibility="collapsed",
            )
        with col_btn:
            if st.button("검색", use_container_width=True):
                _run_search(st.session_state.get("_search_input", ""))
        st.markdown("</div>", unsafe_allow_html=True)

    corp = st.session_state.get("selected_corp")
    no_result_q = st.session_state.get("_search_no_result", "")
    if no_result_q:
        st.warning(f"검색 결과가 없습니다: **{no_result_q}**")
    if not corp:
        st.info("회사명 또는 종목코드를 입력하여 검색하세요.")
        return

    ov = fetch_company_overview(corp["corp_code"], corp.get("stock_code", ""))

    # 회사 정보 카드
    st.markdown(
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
        f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:14px 18px;margin:0 0 10px 0;">'
        f'<div style="display:flex;align-items:baseline;gap:10px;">'
        f'<span style="font-size:1.25rem;font-weight:800;color:#1e293b;">{corp["corp_name"]}</span>'
        + (f'<span style="font-size:.82rem;color:#2563eb;font-weight:600;">{corp.get("stock_code","")}</span>'
           if corp.get("stock_code") else "")
        + (f'<span style="font-size:.75rem;color:#64748b;">{ov.get("cls_label","")}</span>'
           if ov.get("cls_label") else "")
        + f'</div>'
        + (f'<div style="font-size:.75rem;color:#475569;margin-top:4px;">{ov.get("sector","")}'
           + (f' &nbsp;|&nbsp; {ov.get("product","")}' if ov.get("product") else "")
           + f'</div>' if ov.get("sector") else "")
        + (f'<div style="font-size:.72rem;color:#94a3b8;margin-top:2px;">'
           + "  &nbsp;|&nbsp;  ".join(filter(None, [
               ov.get("est_dt",""), ov.get("acc_mt",""), ov.get("adres",""),
               f'<a href="{ov["hm_url"]}" target="_blank" style="color:#2563eb;">{ov["hm_url"]}</a>'
               if ov.get("hm_url") else "",
           ])) + f'</div>' if any(ov.get(k) for k in ("est_dt","acc_mt","adres","hm_url")) else "")
        + f'</div>',
        unsafe_allow_html=True,
    )

    if corp.get("stock_code"):
        with st.expander("⚙️ 적정주가 파라미터 설정", expanded=False):
            _vc1, _vc2, _vc3, _vc4 = st.columns(4)
            with _vc1:
                _wacc  = st.number_input(
                    "WACC 할인율 (%)", 1.0, 30.0, 10.0, 0.5, key="val_wacc",
                    help="가중평균자본비용 — DCF 분모에 적용"
                ) / 100
            with _vc2:
                _tg    = st.number_input(
                    "영구성장률 g (%)", 0.0, 10.0, 2.0, 0.5, key="val_tg",
                    help="Terminal Value 계산에 사용하는 무한 성장률 (WACC 미만이어야 함)"
                ) / 100
            with _vc3:
                _fcfg  = st.number_input(
                    "FCF 성장률 (%)", -10.0, 30.0, 5.0, 0.5, key="val_fcfg",
                    help="예측기간 N년 동안 적용할 FCF 연간 성장률"
                ) / 100
            with _vc4:
                _years = int(st.number_input(
                    "예측기간 (년)", 3, 15, 5, 1, key="val_years",
                    help="DCF 명시적 현금흐름 예측 기간"
                ))
        with st.spinner("적정주가 산정 중..."):
            _fv = compute_fair_values(
                corp["corp_code"], corp.get("stock_code", ""),
                ov.get("corp_cls_raw", "Y"),
                _wacc, _tg, _fcfg, _years, _CACHE_VER,
            )
        _render_valuation_card(_fv)

    # 환율 + 미국채 카드
    md = fetch_market_data()
    if md and md.get("usd_krw"):
        st.markdown(
            f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:4px 4px 2px;margin:0 0 12px 0;">'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">'
            + _fx_card_item("원 / 달러",       md["usd_krw"],    md.get("usd_krw_chg"),    "원", ".1f")
            + _fx_card_item("원 / 100엔",      md["jpy100_krw"], md.get("jpy100_krw_chg"), "원", ".1f")
            + _fx_card_item("엔 / 달러",       md["usd_jpy"],    md.get("usd_jpy_chg"),    "엔", ".2f")
            + _fx_card_item("10년 채권 이자율", md["bond10y"],    md.get("bond10y_chg"),    "%",  ".3f")
            + f'</div>',
            unsafe_allow_html=True,
        )

    tab_stock, tab_sh, tab_fs, tab_news, tab_emp = st.tabs(
        ["📈 주식", "🏛 주주 현황", "📊 재무제표", "📢 공시 · 뉴스", "👥 직원 현황"]
    )
    with tab_stock:
        try:
            render_stock_chart(
                corp.get("stock_code", ""),
                corp["corp_name"],
                ov.get("corp_cls_raw", "Y"),
                corp_code=corp.get("corp_code", ""),
            )
        except Exception as e:
            st.error(f"주식 차트 로딩 오류: {e}")
    with tab_sh:
        _render_shareholder_tab(corp.get("corp_code", ""))
    with tab_fs:
        _render_fs_tab(corp)
    with tab_news:
        _render_news_tab(corp)
    with tab_emp:
        _render_employee_tab(corp)

if __name__ == "__main__":
    main()
