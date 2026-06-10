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
import streamlit.components.v1 as components
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
try:
    DART_KEY = st.secrets.get("DART_KEY", os.environ.get("DART_KEY", ""))
except Exception:
    DART_KEY = os.environ.get("DART_KEY", "")

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
_CACHE_VER = 21

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
    try:
        return round(int(item.get("thstrm_amount", "").replace(",", "")) / 1e8)
    except Exception:
        return None


def find_amount(items: list[dict], keys: list[str]) -> int | None:
    """계정과목 검색: 완전일치 → 양방향 포함 검색"""
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
            if kc in nm or nm in kc:
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

@st.cache_data(ttl=TTL_WEEKLY, show_spinner=False)
def load_corp_list() -> list[dict]:
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": DART_KEY}, timeout=30)
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
        result = {
            "bs": {
                "assets":           find_amount(bs, ACC["assets"]),
                "liabilities":      find_amount(bs, ACC["liabilities"]),
                "equity":           find_amount(bs, ACC["equity"]),
                "retainedEarnings": find_retained_earnings(bs),
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
            },
        }
        has_data = any(v is not None for sec in result.values() for v in sec.values())
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
        import urllib.parse
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


@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_large_holding_reports(corp_code: str, count: int = 20, _ver: int = _CACHE_VER) -> list[dict]:
    if not corp_code:
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
    if not DART_KEY:
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
        results = []
        for item in (data.get("list") or []):
            irds_raw = (item.get("sp_stock_lmp_irds_cnt") or "0").replace(",", "")
            try:
                irds = int(irds_raw)
            except ValueError:
                irds = 0
            results.append({
                "rcept_no": item.get("rcept_no", ""),
                "rcept_dt": item.get("rcept_dt", ""),
                "repror":   (item.get("repror") or "").strip(),
                "rgist_at": (item.get("isu_exctv_rgist_at") or "").strip(),
                "ofcps":    (item.get("isu_exctv_ofcps") or "").strip(),
                "shares":   (item.get("sp_stock_lmp_cnt") or "0").replace(",", "").strip(),
                "irds":     irds,
                "irds_raw": item.get("sp_stock_lmp_irds_cnt", "0"),
            })
        results.sort(key=lambda x: x["rcept_dt"], reverse=True)
        return results[:count]
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


@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_employee_status(corp_code: str, _ver: int = _CACHE_VER) -> dict:
    if not DART_KEY:
        return {}
    fetch_years = list(range(2015, datetime.now().year))
    result: dict[str, dict] = {}
    for year in fetch_years:
        try:
            r = requests.get(
                f"{BASE}/empSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": "11011"},
                timeout=10,
            )
            raw = r.json()
            if raw.get("status") != "000":
                continue
            all_items = raw.get("list") or []
            if not all_items:
                continue

            def _pick_agg(sex: str) -> dict | None:
                rows = [x for x in all_items if (x.get("sexdstn") or "").strip() == sex]
                if not rows:
                    return None
                agg = [x for x in rows if "합계" in (x.get("fo_bbm") or "")]
                return agg[0] if agg else max(rows, key=lambda x: _emp_parse_int(x.get("sm")))

            rec: dict[str, Any] = {}
            for sex, prefix in [("남", "male"), ("여", "female")]:
                item = _pick_agg(sex)
                if not item:
                    continue
                rec[prefix]                    = _emp_parse_int(item.get("rgllbr_co"))
                rec[f"{prefix}_contract"]      = _emp_parse_int(item.get("cnttk_co"))
                rec[f"{prefix}_total"]         = _emp_parse_int(item.get("sm"))
                rec[f"avg_tenure_{prefix[0]}"] = _emp_parse_float(item.get("avrg_cnwk_sdytrn"))
                rec[f"salary_{prefix[0]}"]     = _emp_parse_salary(item.get("jan_salary_am"))

            if rec:
                rec["total"] = rec.get("male_total", 0) + rec.get("female_total", 0)
                result[str(year)] = rec
        except Exception:
            continue
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
        cfg = {
            "6mo":   dict(period="6mo",  interval="1d"),
            "24mo":  dict(period="2y",   interval="1d"),
            "36mo":  dict(period="3y",   interval="1d"),
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

        hist = t.history(period="12y", interval="1mo", auto_adjust=True)
        if hist.empty:
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

                    def _get_yf(df_T: pd.DataFrame, idx, keys: list[str]) -> float | None:
                        for k in keys:
                            if k in df_T.columns:
                                v = df_T.loc[idx, k]
                                if pd.notna(v):
                                    return float(v)
                        return None

                    for idx_date in fin_T.index:
                        yr    = idx_date.year
                        close = year_closes.get(yr)
                        if close is None or not shares or shares <= 0:
                            continue
                        ni = _get_yf(fin_T, idx_date, NI_KEYS)
                        eq = None
                        if not bs_T.empty:
                            closest = min(bs_T.index, key=lambda d: abs((d - idx_date).days))
                            eq = _get_yf(bs_T, closest, EQ_KEYS)
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

def _render_mktcap_chart(stock_code: str, corp_cls: str, corp_code: str) -> None:
    _section_header("연도별 시가총액", "과거: 연말 종가 기준 · 현재 연도: 당일 현재가 기준 (억 원)")
    yf_data = fetch_yf_annual_data(stock_code, corp_cls, corp_code, _ver=_CACHE_VER)
    if "__error__" in yf_data:
        st.caption(f"시가총액 데이터를 가져올 수 없습니다: {yf_data['__error__']}")
        return
    mktcap = yf_data.get("mktcap", {})
    if not mktcap:
        st.caption("시가총액을 계산하기 위한 데이터가 부족합니다 (발행주식수 미확인).")
        return
    cur_yr_str = str(datetime.now().year)
    years_mc   = sorted(mktcap.keys())
    vals_mc    = [mktcap[y] for y in years_mc]
    bar_colors = [COLORS["orange"] if y == cur_yr_str else COLORS["blue"] for y in years_mc]
    fig = go.Figure(go.Bar(
        x=years_mc, y=vals_mc, marker_color=bar_colors,
        text=[f"{v:,}" for v in vals_mc],
        textposition="outside", textfont=dict(size=9, color="#64748b"),
    ))
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "xaxis")},
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
        yaxis=dict(title="억 원", tickformat=",", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b")),
    )
    st.plotly_chart(fig, use_container_width=True)
    return yf_data  # type: ignore[return-value]


def _render_per_pbr_chart(yf_data: dict) -> None:
    _section_header("PER / PBR 밸류에이션 추이", "연말 종가 기준 · 오늘: trailing 기준")
    per_pbr = yf_data.get("per_pbr", {})
    if not per_pbr:
        st.caption("PER/PBR 계산에 필요한 재무데이터(순이익, 자본총계)를 가져올 수 없습니다.")
        return

    today_key = datetime.now().strftime("%Y-%m-%d")

    def _is_year_key(k: str) -> bool:
        return len(k) == 4 and k.isdigit()

    # 오래된 날짜 키를 오늘 날짜 키로 갱신
    for stale in [k for k in list(per_pbr.keys()) if not _is_year_key(k) and k != today_key]:
        per_pbr[today_key] = per_pbr.pop(stale)

    hist_keys  = sorted([k for k in per_pbr if _is_year_key(k)], key=int)
    date_keys  = sorted([k for k in per_pbr if not _is_year_key(k)])
    years_pp   = hist_keys + date_keys
    per_vals   = [per_pbr[y].get("PER") for y in years_pp]
    pbr_vals   = [per_pbr[y].get("PBR") for y in years_pp]

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
    ), secondary_y=False)
    fig.add_trace(go.Scatter(
        x=years_pp, y=pbr_vals, name="PBR", mode="lines+markers",
        line=dict(color=COLORS["orange"], width=2, dash="dot"), marker=_marker(COLORS["orange"]),
        connectgaps=True,
    ), secondary_y=True)
    fig.update_layout(
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "legend", "xaxis")},
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
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
#  주가 차트 메인
# ══════════════════════════════════════════

def render_stock_chart(stock_code: str, corp_name: str,
                       corp_cls: str = "Y", corp_code: str = "") -> None:
    if not stock_code:
        return

    period_labels = ["6달", "2년", "3년", "월봉", "연봉"]
    sel = st.radio("기간", period_labels, horizontal=True,
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

        def ic(lbl: str, val: str, color: str = "#475569") -> str:
            return (
                f'<span style="margin-right:12px;white-space:nowrap;">'
                f'<span style="font-size:.65rem;color:#94a3b8;">{lbl} </span>'
                f'<span style="font-size:.82rem;font-weight:600;color:{color};">{val}</span>'
                f'</span>'
            )

        info_cells = (
              ic("시가",   f"{last['open']:,.0f}")
            + ic("고가",   f"{last['high']:,.0f}", "#dc2626")
            + ic("저가",   f"{last['low']:,.0f}",  "#2563eb")
            + ic("종가",   f"{last['close']:,.0f}")
            + ic("대비",   f"{sym}{abs(int(chg_val)):,}", clr)
            + ic("등락률", f"{sym}{abs(chg_pct):.2f}%", clr)
            + ic("거래량", f"{last['volume']:,.0f}")
            + ic("거래대금", f"{turnover:,.0f}억")
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
        yf_data = fetch_yf_annual_data(stock_code, corp_cls, corp_code, _ver=_CACHE_VER)
        if "__error__" not in yf_data:
            _section_header("연도별 시가총액", "과거: 연말 종가 기준 · 현재 연도: 당일 현재가 기준 (억 원)")
            mktcap = yf_data.get("mktcap", {})
            if mktcap:
                cur_yr_str = str(datetime.now().year)
                years_mc   = sorted(mktcap.keys())
                vals_mc    = [mktcap[y] for y in years_mc]
                bar_colors = [COLORS["orange"] if y == cur_yr_str else COLORS["blue"]
                              for y in years_mc]
                fig_mc = go.Figure(go.Bar(
                    x=years_mc, y=vals_mc, marker_color=bar_colors,
                    text=[f"{v:,}" for v in vals_mc],
                    textposition="outside", textfont=dict(size=9, color="#64748b"),
                ))
                fig_mc.update_layout(
                    **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "xaxis")},
                    xaxis=dict(type="category", gridcolor="#e2e8f0",
                               tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
                    yaxis=dict(title="억 원", tickformat=",", gridcolor="#e2e8f0",
                               tickfont=dict(color="#64748b")),
                )
                st.plotly_chart(fig_mc, use_container_width=True)
            else:
                st.caption("시가총액을 계산하기 위한 데이터가 부족합니다 (발행주식수 미확인).")

            _render_per_pbr_chart(yf_data)
        else:
            st.caption(f"시가총액 데이터를 가져올 수 없습니다: {yf_data['__error__']}")

        _render_shareholder_section(corp_code)
        _render_large_holdings(corp_code)
        _render_executive_reports(corp_code)


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
        rows = []
        for y in reversed(years):
            c = data[y]["cf"]
            rows.append({
                "연도": y, "영업CF": fmt(c.get("opCF")),
                "투자CF": fmt(c.get("invCF")), "재무CF": fmt(c.get("finCF")),
                "기말현금": fmt(c.get("endCash")),
            })
        st.dataframe(rows, hide_index=True, use_container_width=True)


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
        def _to_man(v: int | None) -> int:
            return round((v or 0) / 10_000)

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
    def _sal_fmt(v: int | None) -> str:
        return f'{round((v or 0) / 10_000):,}만원' if v else "-"

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
    st.markdown("""
    <div style="position:sticky;top:0;z-index:999;
                background:#fff;border-bottom:1px solid #e2e8f0;
                box-shadow:0 1px 4px rgba(0,0,0,.06);
                padding:14px 20px;margin:-1rem -1rem 1.2rem -1rem;
                display:flex;align-items:center;gap:12px;">
      <div style="width:38px;height:38px;border-radius:10px;flex-shrink:0;
                  background:linear-gradient(135deg,#2563eb,#7c3aed);
                  display:flex;align-items:center;justify-content:center;font-size:18px;">📊</div>
      <div>
        <div class="dart-title" style="font-size:1.15rem;font-weight:700;color:#1e293b;line-height:1.2;">
          기업 주식 시황 및 재무 대시보드</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 검색창 ──
    def _run_search(q: str) -> None:
        """검색 실행 — session_state에 결과 저장."""
        q = (q or "").strip()
        if not q:
            return
        try:
            corps = load_corp_list()
            results = search_corps(q, corps)[:10]
        except Exception:
            results = []
        # 정확히 이름이 일치하는 법인이 있으면 바로 선택 (자동완성 클릭 포함)
        exact = [c for c in results if c["corp_name"] == q]
        if exact:
            st.session_state["selected_corp"]  = exact[0]
            st.session_state["_ac_results"]    = []
        elif len(results) == 1:
            st.session_state["selected_corp"]  = results[0]
            st.session_state["_ac_results"]    = []
        elif results:
            st.session_state["_ac_results"]    = results
            st.session_state["selected_corp"]  = None
        else:
            st.session_state["_ac_results"]    = []
            st.session_state["_ac_no_result"]  = q

    def _on_query_change() -> None:
        q = st.session_state.get("_search_input", "").strip()
        st.session_state["_ac_no_result"] = ""
        if q:
            _run_search(q)
        else:
            st.session_state["_ac_results"] = []

    # 검색창 + 자동완성 CSS
    st.markdown("""
    <style>
    div[data-testid="stTextInput"] input { font-size: 1rem !important; }

    /* ── 자동완성 radio 드롭다운 스타일 ── */
    div[data-testid="stRadio"] {
        margin-top: -4px !important;
    }
    div[data-testid="stRadio"] > div {
        border: 1px solid #d0d0d0 !important;
        border-top: none !important;
        border-radius: 0 0 8px 8px !important;
        overflow: hidden !important;
        box-shadow: 0 4px 10px rgba(0,0,0,.08) !important;
        gap: 0 !important;
    }
    /* 헤더 레이블 숨김 */
    div[data-testid="stRadio"] > label { display: none !important; }
    /* 라디오 원 숨김 */
    div[data-testid="stRadio"] label > div:first-child { display: none !important; }
    /* 각 항목 행 스타일 */
    div[data-testid="stRadio"] label {
        display: flex !important;
        align-items: center !important;
        padding: 10px 14px !important;
        border-bottom: 1px solid #f2f2f2 !important;
        margin: 0 !important;
        background: white !important;
        cursor: pointer !important;
        font-size: 14px !important;
        color: #202020 !important;
        font-weight: 400 !important;
        letter-spacing: -.3px !important;
    }
    div[data-testid="stRadio"] label:last-of-type { border-bottom: none !important; }
    div[data-testid="stRadio"] label:hover { background: #f8f8f8 !important; }
    /* 선택된 항목 강조 제거 */
    div[data-testid="stRadio"] label[data-checked="true"] {
        background: #f0f7ff !important;
    }
    </style>""", unsafe_allow_html=True)

    ac_results: list[dict] = st.session_state.get("_ac_results", [])

    col_inp, col_btn = st.columns([5, 1])
    with col_inp:
        st.text_input(
            "",
            placeholder="회사명 또는 종목코드 입력 (예: 삼성전자, 005930)",
            key="_search_input",
            label_visibility="collapsed",
            on_change=_on_query_change,
        )
        # 자동완성 드롭다운 — st.radio 기반 (네이티브 Streamlit 클릭 처리)
        if ac_results:
            _name_map = {c["corp_code"]: c for c in ac_results}
            _codes    = [c["corp_code"] for c in ac_results]

            def _fmt_ac(code: str) -> str:
                c     = _name_map.get(code, {})
                stock = c.get("stock_code", "") or "비상장"
                name  = c.get("corp_name", "")
                # 돋보기 아이콘 + 이름 + 종목코드(우측)
                pad = "　" * max(1, 18 - len(name))   # 전각 공백으로 우측 정렬 근사
                return f"🔍  {name}{pad}{stock}"

            sel = st.radio(
                "", _codes,
                format_func=_fmt_ac,
                key="ac_radio",
                index=None,
                label_visibility="collapsed",
            )
            if sel and sel in _name_map:
                st.session_state["selected_corp"] = _name_map[sel]
                st.session_state["_ac_results"]   = []
                st.rerun()

    with col_btn:
        if st.button("🔍 검색", use_container_width=True, key="search_btn"):
            _run_search(st.session_state.get("_search_input", ""))

    no_result_q = st.session_state.get("_ac_no_result", "")
    if no_result_q:
        st.warning(f"'{no_result_q}' 검색 결과가 없습니다.")

    # 아직 아무 기업도 선택되지 않은 경우 → 안내 화면
    corp = st.session_state.get("selected_corp")
    if not corp:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:#768390;">
          <div style="font-size:2rem;margin-bottom:1rem;">📊</div>
          <div>회사명 또는 종목코드를 입력하고 검색하세요</div>
          <div style="font-size:.8rem;margin-top:.5rem;">K-IFRS 기준 최대 15년 재무제표를 불러옵니다</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # 기업 개요
    with st.spinner("기업 정보 조회 중..."):
        ov = fetch_company_overview(corp["corp_code"], corp.get("stock_code", ""))

    cls_badge = (
        f'<span style="background:#eff6ff;color:#2563eb;font-size:.68rem;'
        f'border-radius:4px;padding:2px 7px;margin-left:8px;font-weight:600;">'
        f'{ov.get("corp_cls","")}</span>'
    ) if ov.get("corp_cls") else ""

    meta_parts = []
    if ov.get("ceo_nm"):  meta_parts.append(f'<span><b>대표</b> {ov["ceo_nm"]}</span>')
    if ov.get("est_dt"):  meta_parts.append(f'<span><b>설립</b> {ov["est_dt"]}</span>')
    if ov.get("acc_mt"):  meta_parts.append(f'<span><b>결산</b> {ov["acc_mt"]}</span>')
    if ov.get("phn_no"):  meta_parts.append(f'<span><b>전화</b> {ov["phn_no"]}</span>')
    sep        = '<span style="color:#94a3b8;margin:0 6px;">|</span>'
    meta_html  = sep.join(meta_parts)
    addr_html  = f'<div style="font-size:.72rem;color:#64748b;margin-top:4px;">📍 {ov["adres"]}</div>' if ov.get("adres") else ""
    url_html   = (f'<div style="font-size:.72rem;margin-top:2px;">🌐 '
                  f'<a href="{ov["hm_url"]}" target="_blank" style="color:#2563eb;">{ov["hm_url"]}</a></div>'
                  ) if ov.get("hm_url") else ""

    st.markdown(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;
                box-shadow:0 1px 3px rgba(0,0,0,.06);padding:14px 18px;margin:12px 0;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:{'8px' if meta_parts else '0'};">
        <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);border-radius:8px;
                    padding:4px 12px;font-weight:700;color:#fff;flex-shrink:0;">
          {corp['corp_name'][:2]}</div>
        <div style="flex:1;">
          <div style="font-weight:700;color:#1e293b;font-size:1.05rem;">{corp['corp_name']}{cls_badge}</div>
          <div style="font-size:.72rem;color:#94a3b8;margin-top:2px;">
            코드: {corp['corp_code']}
            {'&nbsp;·&nbsp;상장: '+corp['stock_code'] if corp['stock_code'] else ''}</div>
        </div>
      </div>
      {f'<div style="font-size:.78rem;color:#475569;margin-top:4px;">{meta_html}</div>' if meta_html else ''}
      {addr_html}{url_html}
    </div>
    """, unsafe_allow_html=True)

    # 환율 + 미국채 카드
    md = fetch_market_data()
    if md and md.get("usd_krw"):
        def fx_item(label: str, value: float | None,
                    chg: float | None, unit: str = "", num_fmt: str = ".1f") -> str:
            """환율 카드 셀 — num_fmt 파라미터명으로 전역 fmt() 함수 충돌 방지."""
            if value is None:
                return ""
            if chg is not None and chg != 0:
                sym_c    = "▲" if chg > 0 else "▼"
                color    = "#dc2626" if chg > 0 else "#2563eb"
                chg_html = (f'<span style="font-size:.62rem;color:{color};margin-left:3px;">'
                            f'{sym_c}{abs(chg):{num_fmt}}</span>')
            else:
                chg_html = ""
            val_str  = f"{value:,.3f}" if num_fmt == ".3f" else (
                f"{value:,.2f}" if num_fmt == ".2f" else f"{value:,.1f}"
            )
            unit_html = (f'<span style="font-size:.65rem;font-weight:400;color:#94a3b8;margin-left:2px;">{unit}</span>'
                         if unit else "")
            return (
                f'<div style="flex:1;min-width:45%;text-align:center;padding:8px 6px;">'
                f'<div style="font-size:.65rem;color:#64748b;margin-bottom:2px;white-space:nowrap;">{label}</div>'
                f'<div style="font-size:.95rem;font-weight:700;color:#1e293b;white-space:nowrap;">'
                f'{val_str}{chg_html}{unit_html}</div>'
                f'</div>'
            )

        st.markdown(
            f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:4px 4px 2px;margin:0 0 12px 0;">'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">'
            + fx_item("원 / 달러",       md["usd_krw"],    md.get("usd_krw_chg"),    "원", ".1f")
            + fx_item("원 / 100엔",      md["jpy100_krw"], md.get("jpy100_krw_chg"), "원", ".1f")
            + fx_item("엔 / 달러",       md["usd_jpy"],    md.get("usd_jpy_chg"),    "엔", ".2f")
            + fx_item("10년 채권 이자율", md["bond10y"],    md.get("bond10y_chg"),    "%",  ".3f")
            + f'</div>'
            f'<div style="text-align:right;font-size:.62rem;color:#94a3b8;padding:0 8px 4px;">'
            f'기준일 {md["date"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ══ 메인 탭 ══
    tab_stock, tab_fs, tab_news, tab_emp = st.tabs(
        ["📈 주식", "📊 재무제표", "📢 공시 · 뉴스", "👥 직원 현황"]
    )

    with tab_stock:
        try:
            render_stock_chart(
                corp.get("stock_code", ""), corp["corp_name"],
                ov.get("corp_cls_raw", "Y"), corp_code=corp.get("corp_code", ""),
            )
        except Exception as e:
            st.error(f"주식 차트 로딩 오류: {e}")

    with tab_fs:
        _render_fs_tab(corp)

    with tab_news:
        _render_news_tab(corp)

    with tab_emp:
        _render_employee_tab(corp)


# ══════════════════════════════════════════
if __name__ == "__main__":
    main()
