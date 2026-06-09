"""
기업 주식 시황 및 재무 대시보드 — Streamlit 모바일 웹앱
============================================
설치:  pip install streamlit plotly requests
실행:  streamlit run streamlit_app.py
배포:  share.streamlit.io (무료)
"""

import os
import streamlit as st
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ══════════════════════════════════════════
#  API Key — Streamlit Secrets 또는 환경변수
#  로컬: .streamlit/secrets.toml 에 DART_KEY = "your_key"
#  Streamlit Cloud: Settings > Secrets 에 동일하게 입력
# ══════════════════════════════════════════
try:
    DART_KEY = st.secrets.get("DART_KEY", os.environ.get("DART_KEY", ""))
except Exception:
    DART_KEY = os.environ.get("DART_KEY", "")
# ══════════════════════════════════════════

BASE          = "https://opendart.fss.or.kr/api"
_LATEST_YEAR  = datetime.now().year - 1        # 마지막 완료 사업연도
YEARS         = list(range(_LATEST_YEAR - 14, _LATEST_YEAR + 1))  # 현재 기준 최근 15년

ACC = {
    "assets":      ["자산총계"],
    "liabilities": ["부채총계"],
    "equity":      ["자본총계", "자본합계"],
    "revenue":     ["매출액", "수익(매출액)", "영업수익", "매출", "총수익"],
    "opIncome":    ["영업이익", "영업이익(손실)", "영업손익"],
    "netIncome":   ["당기순이익", "당기순이익(손실)", "당기순손익"],
    # ↓ DART 실제 계정명 기준 (이미지에서 확인)
    "retainedEarnings": ["이익잉여금(결손금)", "이익잉여금", "결손금",
                         "미처분이익잉여금", "미처리결손금"],
    "opCF":        ["영업활동으로 인한 현금흐름", "영업활동현금흐름"],
    "invCF":       ["투자활동으로 인한 현금흐름", "투자활동현금흐름"],
    "finCF":       ["재무활동으로 인한 현금흐름", "재무활동현금흐름"],
    # ↓ DART 실제 계정명 기준 (이미지에서 확인)
    "endCash":     ["기말현금및현금성자산", "기말의현금및현금성자산",
                    "현금및현금성자산의기말잔액", "기말현금및현금성자산잔액"],
}

# 캐시 버전 — 이 숫자를 바꾸면 이전 캐시가 무효화됩니다
_CACHE_VER = 10

COLORS = {
    "blue":   "#2563eb",
    "red":    "#dc2626",
    "green":  "#16a34a",
    "orange": "#ea580c",
    "purple": "#7c3aed",
}

# ─── 페이지 설정 ───

st.set_page_config(
    page_title="기업 주식 시황 및 재무 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  /* Streamlit 기본 헤더/툴바 숨김 */
  [data-testid="stHeader"]           { display:none !important; }
  [data-testid="stToolbar"]          { display:none !important; }
  #MainMenu                          { display:none !important; }
  footer                             { display:none !important; }

  /* 배경 & 기본 색상 — 라이트 테마 */
  [data-testid="stAppViewContainer"] { background:#f8fafc; color:#1e293b; }
  [data-testid="stSidebar"]          { background:#f1f5f9; }
  body                               { background:#f8fafc; }

  /* 상단 여백 제거 */
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

  /* ── 모바일 반응형 ── */
  @media (max-width: 768px) {
    /* 좌우 여백 축소 */
    .block-container { padding-left:0.5rem !important; padding-right:0.5rem !important; }

    /* 헤더 타이틀 폰트 축소 */
    .dart-title { font-size:.95rem !important; }

    /* 수식 입력 최소 너비 보장 */
    [data-testid="stNumberInput"] input { min-width: 0 !important; font-size:.88rem !important; }

    /* 데이터프레임 가로 스크롤 */
    .stDataFrame { overflow-x: auto !important; }

    /* 탭 폰트 축소 */
    [data-testid="stTab"] { font-size:.82rem !important; padding: 6px 8px !important; }

    /* 메트릭 카드 패딩 축소 */
    .metric-card { padding:10px 12px !important; }
    .metric-value { font-size:1rem !important; }

  }

  @media (max-width: 480px) {
    /* 초소형 화면: 모든 다열 레이아웃을 1열로 스택 */
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      min-width: 45% !important;
      flex: 1 1 45% !important;
    }
    /* 3열 이상은 완전 1열로 */
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(3)) > [data-testid="stColumn"] {
      min-width: 100% !important;
      flex: none !important;
    }
  }
</style>
""", unsafe_allow_html=True)


# ─── 유틸 ───

def clean(s):
    return (s or "").replace(" ", "")


def parse_amt(item):
    try:
        return round(int(item.get("thstrm_amount", "").replace(",", "")) / 1e8)
    except Exception:
        return None

def find_amount(items, keys):
    """계정과목 검색: 1) 완전일치 → 2) 키가 계정명 안에 있음 → 3) 계정명이 키 안에 있음"""
    for key in keys:
        kc = clean(key)
        for item in items:
            if clean(item.get("account_nm", "")) == kc:
                v = parse_amt(item)
                if v is not None: return v
    for key in keys:
        kc = clean(key)
        for item in items:
            nm = clean(item.get("account_nm", ""))
            if kc in nm or nm in kc:   # ← 양방향 포함 검색
                v = parse_amt(item)
                if v is not None: return v
    return None

def find_retained_earnings(bs_items):
    """이익잉여금 전용 검색 — '이익잉여금' 포함 계정 우선, 없으면 '결손금' 계정"""
    # 1단계: 기존 키 리스트 검색
    r = find_amount(bs_items, ACC["retainedEarnings"])
    if r is not None: return r
    # 2단계: 계정명에 '이익잉여금' 포함된 항목 직접 탐색
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "이익잉여금" in nm:
            v = parse_amt(item)
            if v is not None: return v
    # 3단계: '결손금' 포함 항목
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "결손금" in nm:
            v = parse_amt(item)
            if v is not None: return v
    return None

def find_end_cash(cf_items):
    """기말현금및현금성자산 전용 검색"""
    # 1단계: 기존 키 리스트 검색
    r = find_amount(cf_items, ACC["endCash"])
    if r is not None: return r
    # 2단계: '기말' + '현금' 동시 포함 항목 탐색
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "기말" in nm and "현금" in nm:
            v = parse_amt(item)
            if v is not None: return v
    # 3단계: '현금및현금성자산' + 마지막 항목 (CF의 맨 끝 현금 잔액)
    candidates = []
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "현금및현금성자산" in nm:
            v = parse_amt(item)
            if v is not None: candidates.append((nm, v))
    # 마지막에 등장하는 '현금및현금성자산' 항목이 기말 잔액일 가능성이 높음
    if candidates:
        return candidates[-1][1]
    return None


def fmt(n):
    if n is None:
        return "-"
    return f"{int(n):,}"


def pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)


# ─── 기업 목록 (캐시) ───

@st.cache_data(ttl=604800, show_spinner=False)   # 7일 캐시
def load_corp_list():
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


def search_corps(query, all_corps):
    q = query.strip()
    ql = q.lower()
    # 종목코드로 검색 (6자리 숫자 또는 A+숫자)
    if q.isdigit() or (len(q) >= 2 and q[0].upper() == "A" and q[1:].isdigit()):
        stock_q = q.lstrip("Aa")
        matches = [c for c in all_corps if c["stock_code"] == stock_q or c["stock_code"] == q]
    else:
        exact   = [c for c in all_corps if c["corp_name"].lower() == ql]
        partial = [c for c in all_corps if ql in c["corp_name"].lower()]
        matches = exact if exact else partial
    if not matches:
        return []
    matches.sort(key=lambda c: (c["corp_name"].lower() != ql, not bool(c["stock_code"]), c["corp_name"]))
    return matches[:20]


# ─── 재무데이터 ───

@st.cache_data(ttl=3600, show_spinner=False)   # 1시간 캐시
def fetch_all_years(corp_code, fs_div, _ver=_CACHE_VER):  # _ver 변경 시 캐시 무효화
    all_data = {}
    for year in YEARS:
        d = fetch_year(corp_code, year, fs_div)
        if d:
            all_data[str(year)] = d
    return all_data


def fetch_year(corp_code, year, fs_div):
    try:
        r = requests.get(
            f"{BASE}/fnlttSinglAcntAll.json",
            params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                    "bsns_year": year, "reprt_code": "11011", "fs_div": fs_div},
            timeout=15
        )
        d = r.json()
        if d.get("status") != "000" or not d.get("list"):
            return None
        lst = d["list"]
        bs  = [x for x in lst if x.get("sj_div") == "BS"]
        isl = [x for x in lst if x.get("sj_div") == "IS"]
        if not isl:
            isl = [x for x in lst if x.get("sj_div") == "CIS"]
        cf  = [x for x in lst if x.get("sj_div") == "CF"]
        result = {
            "bs": {"assets":           find_amount(bs,  ACC["assets"]),
                   "liabilities":      find_amount(bs,  ACC["liabilities"]),
                   "equity":           find_amount(bs,  ACC["equity"]),
                   "retainedEarnings": find_retained_earnings(bs)},
            "is": {"revenue":   find_amount(isl, ACC["revenue"]),
                   "opIncome":  find_amount(isl, ACC["opIncome"]),
                   "netIncome": find_amount(isl, ACC["netIncome"])},
            "cf": {"opCF":   find_amount(cf, ACC["opCF"]),
                   "invCF":  find_amount(cf, ACC["invCF"]),
                   "finCF":  find_amount(cf, ACC["finCF"]),
                   "endCash": find_end_cash(cf)},
        }
        has_data = any(v is not None for sec in result.values() for v in sec.values())
        return result if has_data else None
    except Exception:
        return None


# ─── 기업 개요 ───

@st.cache_data(ttl=86400, show_spinner=False)   # 1일 캐시
def fetch_company_overview(corp_code, stock_code):
    """DART company.json으로 기업 기본 정보를 조회합니다."""
    result = {}

    # 1. DART 기본 정보
    try:
        r = requests.get(f"{BASE}/company.json",
                         params={"crtfc_key": DART_KEY, "corp_code": corp_code},
                         timeout=10)
        d = r.json()
        if d.get("status") == "000":
            cls_map = {"Y": "유가증권(KOSPI)", "K": "코스닥(KOSDAQ)", "N": "코넥스", "E": "기타"}
            est = d.get("est_dt", "")
            result = {
                "ceo_nm":    d.get("ceo_nm", ""),
                "corp_cls":     cls_map.get(d.get("corp_cls", ""), ""),
                "corp_cls_raw": d.get("corp_cls", "Y"),
                "est_dt":    f"{est[:4]}.{est[4:6]}" if len(est) >= 6 else "",
                "acc_mt":    f"{d.get('acc_mt', '')}월" if d.get("acc_mt") else "",
                "phn_no":    d.get("phn_no", ""),
                "adres":     d.get("adres", ""),
                "hm_url":    (lambda u: ("https://" + u) if u and not u.startswith(("http://","https://")) else u)
                             ((d.get("hm_url") or "").strip().rstrip("/")),
            }
    except Exception:
        pass
    return result


# ─── 시장 데이터 (환율 + 미국채) ───

@st.cache_data(ttl=300, show_spinner=False)   # 5분 캐시 (실시간)
def fetch_market_data():
    """yfinance로 환율 4종 + 미국채 10년 수익률 실시간 조회."""
    try:
        import yfinance as yf
        # 심볼 → (배수, 소수점자리)
        cfg = {
            "USDKRW=X": (1,   1),   # USD/KRW
            "JPYKRW=X":  (100, 1),   # 100JPY/KRW
            "USDJPY=X":  (1,   2),   # USD/JPY
            "^TNX":      (1,   3),   # 미국채 10Y (%)
        }
        raw = {}
        for sym, (mul, nd) in cfg.items():
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=True)
            if hist.empty:
                continue
            hist = hist.dropna(subset=["Close"])
            dates = sorted(hist.index)
            cur  = round(float(hist.loc[dates[-1],  "Close"]) * mul, nd)
            prev = round(float(hist.loc[dates[-2], "Close"]) * mul, nd) if len(dates) >= 2 else None
            chg  = round(cur - prev, nd) if prev is not None else None
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


# ─── 공시 ───

def _parse_disc_list(items, count):
    """DART list.json 항목 → 공시 카드 데이터로 변환."""
    result = []
    for item in items[:count]:
        rcept_dt = item.get("rcept_dt", "")
        if len(rcept_dt) == 8:
            rcept_dt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"
        rcept_no = item.get("rcept_no", "")
        link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
        corp_cls_map = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}
        corp_cls = corp_cls_map.get(item.get("corp_cls", ""), "")
        result.append({
            "report_nm": item.get("report_nm", "").strip(),
            "flr_nm":    item.get("flr_nm", "").strip(),
            "rcept_dt":  rcept_dt,
            "corp_cls":  corp_cls,
            "link":      link,
        })
    return result


@st.cache_data(ttl=1800, show_spinner=False)   # 30분 캐시
def fetch_disclosures(corp_code, count=15):
    """DART 공시 목록 조회 — 날짜 범위 명시, 공시유형 순서대로 폴백."""
    from datetime import timedelta
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")  # 최근 2년

    base_params = {
        "crtfc_key":  DART_KEY,
        "corp_code":  corp_code,
        "bgn_de":     bgn_de,
        "end_de":     end_de,
        "page_count": count,
        "page_no":    1,
    }

    # 거래소공시 → 주요사항보고 → 정기공시 → 전체공시 순 시도
    attempts = [
        ("I", "거래소공시"),
        ("B", "주요사항보고"),
        ("A", "정기공시"),
        ("",  "전체공시"),
    ]
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
            continue
    return [], last_err or "공시 조회 실패"


# ─── 뉴스 ───

@st.cache_data(ttl=1800, show_spinner=False)   # 30분 캐시
def fetch_news(company_name, count=15):
    """Google News RSS로 최신 뉴스 수집."""
    try:
        import urllib.parse
        query = urllib.parse.quote(company_name)
        url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:count]
        news = []
        for item in items:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "").strip()
            src   = item.findtext("source", "").strip()
            # 제목에서 언론사 제거 ("제목 - 언론사" 형태)
            if " - " in title:
                title, src = title.rsplit(" - ", 1)
            # 날짜 파싱
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(pub)
                pub_fmt = dt.strftime("%m/%d %H:%M")
            except Exception:
                pub_fmt = pub[:16] if pub else ""
            news.append({"title": title.strip(), "link": link,
                         "source": src.strip(), "date": pub_fmt})
        return news
    except Exception:
        return []


# ─── 최대주주 현황 (DART majorstock) ───

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_major_shareholders(corp_code, _ver=4):
    """DART hyslrSttus.json — 임원·주요주주 소유현황 조회.
    사업보고서 우선, 최근 5년 폴백.
    반환: list of dict or []
    """
    if not corp_code:
        return []

    cur_year = datetime.now().year
    # 사업보고서(11011) → 반기(11012) 순으로, 최근 5년
    candidates = []
    for y in range(cur_year - 1, cur_year - 6, -1):
        candidates.append((y, "11011"))
    for y in range(cur_year - 1, cur_year - 4, -1):
        candidates.append((y, "11012"))

    for bsns_year, reprt_code in candidates:
        try:
            r = requests.get(
                f"{BASE}/hyslrSttus.json",
                params={
                    "crtfc_key": DART_KEY,
                    "corp_code": corp_code,
                    "bsns_year": str(bsns_year),
                    "reprt_code": reprt_code,
                },
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue

            items = data.get("list") or []
            rows = []
            for item in items:
                name      = (item.get("nm") or "").strip()
                relation  = (item.get("relate") or "").strip()
                stock_knd = (item.get("stock_knd") or "").strip()
                rm        = (item.get("rm") or "").strip()
                stlm_dt   = (item.get("stlm_dt") or "").strip()   # 결산일

                shares_s    = (item.get("trmend_posesn_stock_co") or "").replace(",", "").strip()
                ratio_pct_s = (item.get("trmend_posesn_stock_qota_rt") or "").replace(",", "").strip()

                # "계" 합계 row 제외
                if name in ("계", "합계", ""):
                    continue

                try:
                    shares = int(shares_s) if shares_s else 0
                except ValueError:
                    shares = 0
                try:
                    ratio_pct = float(ratio_pct_s) if ratio_pct_s else None
                except ValueError:
                    ratio_pct = None

                rows.append({
                    "name":      name,
                    "relation":  relation,
                    "shares":    shares,
                    "ratio":     ratio_pct,
                    "stock_knd": stock_knd,
                    "rm":        rm,
                    "stlm_dt":   stlm_dt,
                    "year":      bsns_year,
                    "rcode":     reprt_code,
                })

            if rows:
                return rows
        except Exception:
            continue

    return []


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_major_shareholder_history(corp_code, _ver=1):
    """DART hyslrChgSttus.json — 최대주주 변동현황 조회.
    사업보고서 우선, 최근 5년 폴백.
    반환: list of dict or []
    """
    if not corp_code:
        return []

    cur_year = datetime.now().year
    candidates = []
    for y in range(cur_year - 1, cur_year - 6, -1):
        candidates.append((y, "11011"))
    for y in range(cur_year - 1, cur_year - 4, -1):
        candidates.append((y, "11012"))

    for bsns_year, reprt_code in candidates:
        try:
            r = requests.get(
                f"{BASE}/hyslrChgSttus.json",
                params={
                    "crtfc_key": DART_KEY,
                    "corp_code": corp_code,
                    "bsns_year": str(bsns_year),
                    "reprt_code": reprt_code,
                },
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue

            items = data.get("list") or []
            rows = []
            for item in items:
                nm       = (item.get("mxmm_shrholdr_nm") or "").strip()
                chg_on   = (item.get("change_on") or "").strip()
                shares_s = (item.get("posesn_stock_co") or "").replace(",", "").strip()
                ratio_s  = (item.get("qota_rt") or "").strip()
                cause    = (item.get("change_cause") or "").strip()
                rm       = (item.get("rm") or "").strip()
                stlm_dt  = (item.get("stlm_dt") or "").strip()

                # 의미 없는 "-" 단일값 행 건너뜀
                if nm in ("-", ""):
                    continue

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
                    "chg_on":  chg_on,
                    "shares":  shares,
                    "ratio":   ratio,
                    "cause":   cause,
                    "rm":      rm,
                    "stlm_dt": stlm_dt,
                    "year":    bsns_year,
                    "rcode":   reprt_code,
                })

            if rows:
                return rows
        except Exception:
            continue

    return []


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_large_holding_reports(corp_code, count=20, _ver=1):
    """DART majorstock.json — 대량보유상황보고 조회.
    corp_code만으로 호출; 최근 count건 반환.
    반환: list of dict or []
    """
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
        items = data.get("list") or []
        rows = []
        for item in sorted(items, key=lambda x: x.get("rcept_dt", ""), reverse=True)[:count]:
            stkqy_s    = (item.get("stkqy") or "").replace(",", "").strip()
            stkqy_irds_s = (item.get("stkqy_irds") or "").replace(",", "").strip()
            try:
                stkqy = int(stkqy_s) if stkqy_s else None
            except ValueError:
                stkqy = None
            try:
                stkqy_irds = int(stkqy_irds_s) if stkqy_irds_s not in ("", "-") else None
            except ValueError:
                stkqy_irds = None
            try:
                stkrt = float(item.get("stkrt") or 0)
            except (ValueError, TypeError):
                stkrt = None
            try:
                stkrt_irds = float(item.get("stkrt_irds") or 0)
            except (ValueError, TypeError):
                stkrt_irds = None
            rows.append({
                "rcept_dt":    item.get("rcept_dt", ""),
                "rcept_no":    item.get("rcept_no", ""),
                "report_tp":   item.get("report_tp", ""),
                "repror":      item.get("repror", ""),
                "stkqy":       stkqy,
                "stkqy_irds":  stkqy_irds,
                "stkrt":       stkrt,
                "stkrt_irds":  stkrt_irds,
                "report_resn": (item.get("report_resn") or "").replace("\n", " / ").strip(),
            })
        return rows
    except Exception:
        return []



@st.cache_data(ttl=1800, show_spinner=False)
def fetch_executive_stock_reports(corp_code, count=30, _ver=1):
    """DART elestock.json — 임원·주요주주 소유보고 (corp_code only, no bsns_year)."""
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
        items = data.get("list") or []
        results = []
        for item in items:
            irds_raw = (item.get("sp_stock_lmp_irds_cnt") or "0").replace(",", "")
            try:
                irds = int(irds_raw)
            except ValueError:
                irds = 0
            results.append({
                "rcept_no":      item.get("rcept_no", ""),
                "rcept_dt":      item.get("rcept_dt", ""),
                "repror":        (item.get("repror") or "").strip(),
                "rgist_at":      (item.get("isu_exctv_rgist_at") or "").strip(),
                "ofcps":         (item.get("isu_exctv_ofcps") or "").strip(),
                "shares":        (item.get("sp_stock_lmp_cnt") or "0").replace(",", "").strip(),
                "irds":          irds,
                "irds_raw":      item.get("sp_stock_lmp_irds_cnt", "0"),
            })
        results.sort(key=lambda x: x["rcept_dt"], reverse=True)
        return results[:count]
    except Exception:
        return []


def _emp_parse_int(v):
    """'-' 또는 빈 값 → 0, 나머지는 콤마 제거 후 int."""
    s = (v or "").strip()
    if not s or s == "-":
        return 0
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0

def _emp_parse_float(v):
    """'-' 또는 빈 값 → 0.0, 나머지는 콤마 제거 후 float."""
    s = (v or "").strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0

def _emp_parse_salary(v):
    """jan_salary_am(1인 평균 연봉, 원) → int(원) or None."""
    s = (v or "").strip().replace(",", "")
    if not s or s == "-" or not s.isdigit():
        return None
    val = int(s)
    return val if val > 0 else None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_employee_status(corp_code, cache_ver=1):
    """DART empSttus.json — 2015년 이후 연도별 직원 현황 (사업보고서 기준).
    fo_bbm=='성별합계' 행으로 남/여 정규직·계약직·합계·급여를 반환.
    반환: { year_str: { male, female, total, male_contract, female_contract,
                        male_total, female_total,
                        avg_tenure_m, avg_tenure_f,
                        salary_m(원), salary_f(원) } }
    """
    if not DART_KEY:
        return {}
    fetch_years = list(range(2015, datetime.now().year))  # 2015 ~ 전년도
    result = {}
    for year in fetch_years:
        try:
            r = requests.get(
                f"{BASE}/empSttus.json",
                params={
                    "crtfc_key":  DART_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  str(year),
                    "reprt_code": "11011",
                },
                timeout=10,
            )
            raw = r.json()
            if raw.get("status") != "000":
                continue
            all_items = raw.get("list") or []
            if not all_items:
                continue

            # ── 집계 행 추출 ──
            # 전략: fo_bbm에 "합계" 포함된 행 우선 → 없으면 성별별 sm 최댓값 행 사용
            def _pick_agg(sex):
                rows = [x for x in all_items
                        if (x.get("sexdstn") or "").strip() == sex]
                if not rows:
                    return None
                # "합계" 포함 fo_bbm 우선
                agg = [x for x in rows if "합계" in (x.get("fo_bbm") or "")]
                if agg:
                    return agg[0]
                # 없으면 sm(전체) 최대 행
                return max(rows, key=lambda x: _emp_parse_int(x.get("sm")))

            rec = {}
            for sex, prefix in [("남", "male"), ("여", "female")]:
                item = _pick_agg(sex)
                if not item:
                    continue
                rec[prefix]                  = _emp_parse_int(item.get("rgllbr_co"))
                rec[f"{prefix}_contract"]    = _emp_parse_int(item.get("cnttk_co"))
                rec[f"{prefix}_total"]       = _emp_parse_int(item.get("sm"))
                rec[f"avg_tenure_{prefix[0]}"] = _emp_parse_float(item.get("avrg_cnwk_sdytrn"))
                rec[f"salary_{prefix[0]}"]   = _emp_parse_salary(item.get("jan_salary_am"))

            if rec:
                rec["total"] = rec.get("male_total", 0) + rec.get("female_total", 0)
                result[str(year)] = rec
        except Exception:
            continue
    return result


# ─── 주가 차트 (yfinance / Yahoo Finance) ───

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_stock_chart(stock_code, corp_cls="Y", timeframe="6mo", _ver=6):
    """Yahoo Finance(yfinance)로 주가 OHLCV 조회.
    corp_cls: "Y"=KOSPI(.KS) / "K"=KOSDAQ(.KQ)
    timeframe: "day"(일봉) / "month"(월봉) / "year"(연봉)
    """
    try:
        import yfinance as yf
        suffix  = ".KQ" if corp_cls == "K" else ".KS"
        ticker  = f"{stock_code}{suffix}"
        # 기간 & 간격 설정
        cfg = {
            "6mo":   dict(period="6mo",  interval="1d"),
            "24mo":  dict(period="2y",   interval="1d"),
            "36mo":  dict(period="3y",   interval="1d"),
            "month": dict(period="10y",  interval="1mo"),
            "year":  dict(period="max",  interval="3mo"),   # 분기 집계 후 연도별 처리
        }
        kwargs = cfg.get(timeframe, cfg["6mo"])
        df = yf.Ticker(ticker).history(**kwargs, auto_adjust=True)
        if df.empty:
            return []

        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        df = df[df["Volume"] > 0]
        if timeframe in ("6mo", "24mo", "36mo"):
            df = df[df.index.dayofweek < 5]       # 일봉: 주말 제거 (0=월 ~ 4=금)
            df = df[df["High"] > df["Low"]]        # 일봉: 고가=저가인 phantom 캔들 제거
        data = []
        for dt, row in df.iterrows():
            data.append({
                "date":   str(dt)[:10],
                "year":   str(dt)[:4],
                "open":   round(float(row["Open"]),   0),
                "high":   round(float(row["High"]),   0),
                "low":    round(float(row["Low"]),    0),
                "close":  round(float(row["Close"]),  0),
                "volume": float(row["Volume"]),
            })

        # 연봉: 분기 데이터를 연도별로 집계
        if timeframe == "year" and data:  # noqa
            yearly = {}
            for d in data:
                yr = d["year"]
                if yr not in yearly:
                    yearly[yr] = {k: d[k] for k in d}
                    yearly[yr]["date"] = yr
                else:
                    yearly[yr]["high"]    = max(yearly[yr]["high"], d["high"])
                    yearly[yr]["low"]     = min(yearly[yr]["low"],  d["low"])
                    yearly[yr]["close"]   = d["close"]
                    yearly[yr]["volume"] += d["volume"]
            data = sorted(yearly.values(), key=lambda x: x["date"])

        return data
    except Exception:
        return []


# ─── pykrx 시장 데이터 ───

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_market_cap_history(stock_code, _ver=1):
    """pykrx: 연도별 시가총액 (최근 12년)."""
    try:
        from pykrx import stock as krx
        end   = datetime.now().strftime("%Y%m%d")
        start = str(datetime.now().year - 12) + "0101"
        df = krx.get_market_cap(start, end, stock_code, freq="y")
        if df is None or df.empty:
            return {"__error__": "데이터 없음 (비상장 또는 조회 불가 종목)"}
        result = {}
        for dt, row in df.iterrows():
            year = str(dt)[:4]
            result[year] = {
                "mktcap": round(int(row.get("시가총액", 0)) / 1e8),
                "shares": int(row.get("상장주식수", 0)),
            }
        return result
    except Exception as e:
        return {"__error__": str(e)}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_investor_trading(stock_code, _ver=1):
    """pykrx: 투자자별 일별 순매수 + 기간 합계 매수/매도/순매수 (최근 1년)."""
    try:
        from pykrx import stock as krx
        from datetime import timedelta
        end   = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        df_daily = krx.get_market_trading_value_by_date(start, end, stock_code)
        df_total = krx.get_market_trading_value_by_investor(start, end, stock_code)
        return {"daily": df_daily, "total": df_total}
    except Exception as e:
        return {"__error__": str(e)}


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_valuation_history(stock_code, _ver=1):
    """pykrx: 월별 PER/PBR/DIV 추이 (최근 5년)."""
    try:
        from pykrx import stock as krx
        end   = datetime.now().strftime("%Y%m%d")
        start = str(datetime.now().year - 5) + "0101"
        df = krx.get_market_fundamental(start, end, stock_code, freq="m")
        if df is None or df.empty:
            return {"__error__": "데이터 없음"}
        return {"df": df}
    except Exception as e:
        return {"__error__": str(e)}


def render_stock_chart(stock_code, corp_name, corp_cls="Y", corp_code=None):
    """캔들스틱 + 거래량 차트 (일/월/연봉 선택)."""
    if not stock_code:
        return
    # 기간 선택 (전체 너비)
    period_labels = ["6달", "2년", "3년", "월봉", "연봉"]
    sel = st.radio("기간", period_labels, horizontal=True,
                   key=f"sp_{stock_code}", label_visibility="collapsed")
    # 이평선 입력 — 2열로 분리 (모바일에서도 충분한 너비 확보)
    col_ma1, col_ma2 = st.columns(2)
    with col_ma1:
        ma_period1 = int(st.number_input("이평선1", min_value=0, max_value=300,
                                         value=25, key=f"ma1b_{stock_code}"))
    with col_ma2:
        ma_period2 = int(st.number_input("이평선2", min_value=0, max_value=300,
                                         value=200, key=f"ma2b_{stock_code}"))
    tf_map = {"6달": "6mo", "2년": "24mo", "3년": "36mo", "월봉": "month", "연봉": "year"}
    title_map = {
        "6달": f"{corp_name}  일봉 (최근 6개월)",
        "2년": f"{corp_name}  일봉 (최근 2년)",
        "3년": f"{corp_name}  일봉 (최근 3년)",
        "월봉": f"{corp_name}  월봉 (최근 10년)",
        "연봉": f"{corp_name}  연봉 (최근 20년)",
    }
    is_daily = sel in ("6달", "2년", "3년")

    with st.spinner("주가 데이터 조회 중..."):
        chart_data = fetch_stock_chart(stock_code, corp_cls, tf_map[sel], _ver=6)
    if not chart_data:
        st.caption("주가 데이터를 불러올 수 없습니다.")
        return

    # ── 시세 정보 바 (일봉만) ──
    if is_daily:
        last = chart_data[-1]
        prev_close = chart_data[-2]["close"] if len(chart_data) >= 2 else None
        chg_val = round(last["close"] - prev_close, 0) if prev_close else 0
        chg_pct = round(chg_val / prev_close * 100, 2) if prev_close and prev_close != 0 else 0
        turnover_eok = round(last["close"] * last["volume"] / 1e8, 1)
        clr = "#dc2626" if chg_val >= 0 else "#2563eb"
        sym = "▲" if chg_val > 0 else "▼" if chg_val < 0 else "━"
        def ic(lbl, val, color="#475569"):
            return (f'<span style="margin-right:12px;white-space:nowrap;">'
                    f'<span style="font-size:.65rem;color:#94a3b8;">{lbl} </span>'
                    f'<span style="font-size:.82rem;font-weight:600;color:{color};">{val}</span>'
                    f'</span>')
        info_cells = (
              ic("시가",   f"{last['open']:,.0f}")
            + ic("고가",   f"{last['high']:,.0f}", "#dc2626")
            + ic("저가",   f"{last['low']:,.0f}",  "#2563eb")
            + ic("종가",   f"{last['close']:,.0f}")
            + ic("대비",   f"{sym}{abs(int(chg_val)):,}", clr)
            + ic("등락률", f"{sym}{abs(chg_pct):.2f}%", clr)
            + ic("거래량", f"{last['volume']:,.0f}")
            + ic("거래대금", f"{turnover_eok:,.0f}억")
        )
        st.markdown(
            f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;'
            f'padding:6px 12px;margin-bottom:6px;display:flex;align-items:center;'
            f'justify-content:space-between;overflow-x:auto;">'
            f'<div style="white-space:nowrap;">{info_cells}</div>'
            f'<div style="font-size:.65rem;color:#94a3b8;white-space:nowrap;margin-left:12px;">{last["date"]}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    dates   = [d["date"]   for d in chart_data]
    opens_  = [d["open"]   for d in chart_data]
    highs   = [d["high"]   for d in chart_data]
    lows    = [d["low"]    for d in chart_data]
    closes  = [d["close"]  for d in chart_data]
    volumes = [d["volume"] for d in chart_data]
    # 상승=빨강 / 하락=파랑 (한국식)
    vol_colors = ["#dc2626" if c >= o else "#2563eb"
                  for c, o in zip(closes, opens_)]
    ma_cfg = [(ma_period1, "#f59e0b"), (ma_period2, "#8b5cf6")]
    show_ma = is_daily and any(p > 0 and len(closes) >= p for p, _ in ma_cfg)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.04, row_heights=[0.72, 0.28])
    fig.add_trace(go.Candlestick(
        x=dates, open=opens_, high=highs, low=lows, close=closes,
        name="주가",
        increasing_line_color="#dc2626", increasing_fillcolor="#dc2626",
        decreasing_line_color="#2563eb", decreasing_fillcolor="#2563eb",
        line_width=1,
    ), row=1, col=1)
    # 이평선 (일봉 + period > 0 일 때만)
    if is_daily:
        for ma_p, ma_color in ma_cfg:
            if ma_p > 0 and len(closes) >= ma_p:
                ma_vals = [None] * (ma_p - 1) + [
                    round(sum(closes[j - ma_p:j]) / ma_p, 0)
                    for j in range(ma_p, len(closes) + 1)
                ]
                fig.add_trace(go.Scatter(
                    x=dates, y=ma_vals, mode="lines",
                    name=f"이평선{ma_p}",
                    line=dict(color=ma_color, width=1.4),
                ), row=1, col=1)
    fig.add_trace(go.Bar(
        x=dates, y=volumes, name="거래량",
        marker_color=vol_colors, opacity=0.75,
    ), row=2, col=1)
    fig.update_layout(
        title=dict(text=title_map[sel], font=dict(size=12, color="#1e293b"), x=0, y=0.98,
                   yanchor="top"),
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
        fig.update_yaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0",
                         tickformat=",", row=row, col=1)
    # 일봉: category 축으로 설정 → 거래 없는 날 공백 제거, 캔들 연속 표시
    if is_daily:
        n = len(dates)
        nticks = min(n, 12)   # 최대 12개 눈금만 표시
        fig.update_xaxes(type="category", nticks=nticks, tickangle=-45)
    fig.update_yaxes(title_text="거래량", tickformat=".3s", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)

    # ── 최대주주 현황 + 지분변동 공시 ──
    if corp_code:
        def _section_header(title, sub=""):
            sub_html = (f'<span style="font-size:.68rem;font-weight:400;color:#94a3b8;'
                        f'margin-left:6px;">{sub}</span>') if sub else ""
            st.markdown(
                f'<div style="font-size:.78rem;font-weight:700;color:#1e293b;'
                f'margin:14px 0 6px;border-left:3px solid #2563eb;padding-left:8px;">'
                f'{title}{sub_html}</div>',
                unsafe_allow_html=True,
            )

        # ① 최대주주 현황 테이블
        with st.spinner("최대주주 데이터 조회 중..."):
            shareholders = fetch_major_shareholders(corp_code)

        rcode_label = {"11011": "사업보고서", "11012": "반기보고서",
                       "11013": "1분기보고서", "11014": "3분기보고서"}

        if shareholders:
            ref = shareholders[0]
            stlm_dt   = ref.get("stlm_dt", "")
            ref_label = f"{ref['year']}년 {rcode_label.get(ref['rcode'], ref['rcode'])}"
            if stlm_dt:
                ref_label += f"  ·  결산일 {stlm_dt}"
            _section_header("최대주주·임원 소유현황", ref_label)

            rows_html = ""
            for i, sh in enumerate(shareholders):
                bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
                ratio_str  = f"{sh['ratio']:.2f}%" if sh["ratio"] is not None else "-"
                shares_str = f"{sh['shares']:,}" if sh["shares"] else "-"
                knd_badge  = (f'<span style="font-size:.62rem;background:#e0f2fe;'
                              f'color:#0369a1;border-radius:4px;padding:1px 5px;'
                              f'margin-left:4px;">{sh["stock_knd"]}</span>'
                              if sh.get("stock_knd") else "")
                rm_str     = sh.get("rm", "") or ""
                rows_html += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;">'
                    f'{sh["name"]}{knd_badge}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#64748b;text-align:center;">{sh["relation"]}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;white-space:nowrap;">{shares_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.78rem;font-weight:600;color:#2563eb;text-align:right;white-space:nowrap;">{ratio_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">{rm_str}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="background:#f1f5f9;">'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:left;font-weight:600;">주주명</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:center;font-weight:600;">관계</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">보유주식수</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">지분율</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">비고</th>'
                f'</tr></thead>'
                f'<tbody>{rows_html}</tbody>'
                f'</table></div>',
                unsafe_allow_html=True,
            )
        else:
            _section_header("최대주주·임원 소유현황")
            st.caption("소유현황 데이터를 찾을 수 없습니다.")

        # ② 최대주주 변동현황 테이블
        with st.spinner("최대주주 변동현황 조회 중..."):
            sh_history = fetch_major_shareholder_history(corp_code)

        if sh_history:
            ref_h = sh_history[0]
            h_label = f"{ref_h['year']}년 {rcode_label.get(ref_h['rcode'], ref_h['rcode'])}"
            if ref_h.get("stlm_dt"):
                h_label += f"  ·  결산일 {ref_h['stlm_dt']}"
            _section_header("최대주주 변동현황", h_label)

            rows_h = ""
            for i, sh in enumerate(sh_history):
                bg        = "#f8fafc" if i % 2 == 0 else "#ffffff"
                shares_str = f"{sh['shares']:,}" if sh["shares"] is not None else "-"
                ratio_str  = f"{sh['ratio']:.2f}%" if sh["ratio"] is not None else "-"
                chg_on     = sh.get("chg_on") or "-"
                cause      = sh.get("cause") or "-"
                rm_str     = sh.get("rm") or ""
                rows_h += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;">{sh["nm"]}</td>'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#64748b;text-align:center;white-space:nowrap;">{chg_on}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;">{shares_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.78rem;font-weight:600;color:#2563eb;text-align:right;">{ratio_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#64748b;">{cause}</td>'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;">{rm_str}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="background:#f1f5f9;">'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:left;font-weight:600;">최대주주명</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:center;font-weight:600;">변동일</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">보유주식수</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">지분율</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">변동원인</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">비고</th>'
                f'</tr></thead>'
                f'<tbody>{rows_h}</tbody>'
                f'</table></div>',
                unsafe_allow_html=True,
            )
        else:
            _section_header("최대주주 변동현황")
            st.caption("변동현황 데이터를 찾을 수 없습니다.")

        # ③ 대량보유상황보고
        with st.spinner("대량보유상황보고 조회 중..."):
            large_holdings = fetch_large_holding_reports(corp_code, count=15)

        _section_header("대량보유상황보고")
        if large_holdings:
            rows_lh = ""
            for i, lh in enumerate(large_holdings):
                bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
                stkqy_str = f"{lh['stkqy']:,}" if lh["stkqy"] is not None else "-"
                stkrt_str = f"{lh['stkrt']:.2f}%" if lh["stkrt"] is not None else "-"
                if lh["stkqy_irds"] is not None and lh["stkqy_irds"] != 0:
                    irds_color = "#dc2626" if lh["stkqy_irds"] > 0 else "#2563eb"
                    irds_sym   = "▲" if lh["stkqy_irds"] > 0 else "▼"
                    irds_str   = (f'<span style="color:{irds_color};font-size:.72rem;">'
                                  f'{irds_sym}{abs(lh["stkqy_irds"]):,}</span>')
                    rt_irds_color = "#dc2626" if (lh["stkrt_irds"] or 0) > 0 else "#2563eb"
                    rt_irds_sym   = "▲" if (lh["stkrt_irds"] or 0) > 0 else "▼"
                    rt_irds_str   = (f'<span style="color:{rt_irds_color};font-size:.72rem;">'
                                     f'{rt_irds_sym}{abs(lh["stkrt_irds"] or 0):.2f}%</span>')
                else:
                    irds_str    = '<span style="color:#94a3b8;font-size:.72rem;">-</span>'
                    rt_irds_str = irds_str
                dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={lh['rcept_no']}"
                tp_badge = (f'<span style="font-size:.62rem;background:#f0fdf4;color:#166534;'
                            f'border-radius:4px;padding:1px 5px;">{lh["report_tp"]}</span>'
                            if lh.get("report_tp") else "")
                resn = lh.get("report_resn", "")
                resn_short = resn[:40] + "…" if len(resn) > 40 else resn
                rows_lh += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">'
                    f'<a href="{dart_url}" target="_blank" style="color:#94a3b8;text-decoration:none;">'
                    f'{lh["rcept_dt"]}</a></td>'
                    f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;white-space:nowrap;">'
                    f'{lh["repror"]}&nbsp;{tp_badge}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;">{stkqy_str}</td>'
                    f'<td style="padding:5px 8px;text-align:right;">{irds_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;font-weight:600;color:#1e293b;text-align:right;">{stkrt_str}</td>'
                    f'<td style="padding:5px 8px;text-align:right;">{rt_irds_str}</td>'
                    f'<td style="padding:5px 8px;font-size:.70rem;color:#64748b;" title="{resn}">{resn_short}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="background:#f1f5f9;">'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">접수일</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">보고자</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">보유주식수</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">증감</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">지분율</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">증감율</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">보고사유</th>'
                f'</tr></thead>'
                f'<tbody>{rows_lh}</tbody>'
                f'</table></div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("대량보유상황보고 데이터를 찾을 수 없습니다.")

        # ④ 임원·주요주주 소유보고
        with st.spinner("임원·주요주주 소유보고 조회 중..."):
            exec_reports = fetch_executive_stock_reports(corp_code, count=15, _ver=_CACHE_VER)

        _section_header("임원·주요주주 소유보고")
        if exec_reports:
            rows_er = ""
            for i, er in enumerate(exec_reports):
                bg = "#f8fafc" if i % 2 == 0 else "#ffffff"
                dt = er["rcept_dt"]
                dt_fmt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}" if len(dt) == 8 else dt
                dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={er['rcept_no']}"
                irds = er["irds"]
                irds_raw = er["irds_raw"]
                if irds > 0:
                    irds_cell = f'<span style="color:#dc2626;font-size:.72rem;">▲{irds_raw}</span>'
                elif irds < 0:
                    irds_cell = f'<span style="color:#2563eb;font-size:.72rem;">▼{irds_raw.lstrip("-")}</span>'
                else:
                    irds_cell = f'<span style="color:#94a3b8;font-size:.72rem;">-</span>'
                rgist = er["rgist_at"].replace("비등기임원", "비등기").replace("등기임원", "등기")
                rgist_badge = (f'<span style="font-size:.62rem;background:#f0fdf4;color:#166534;'
                               f'border-radius:4px;padding:1px 5px;">{rgist}</span>'
                               if rgist else "")
                ofcps = er["ofcps"] or "-"
                try:
                    shares_fmt = f'{int(er["shares"]):,}'
                except Exception:
                    shares_fmt = er["shares"]
                rows_er += (
                    f'<tr style="background:{bg};">'
                    f'<td style="padding:5px 8px;font-size:.72rem;color:#94a3b8;white-space:nowrap;">'
                    f'<a href="{dart_url}" target="_blank" style="color:#94a3b8;text-decoration:none;">'
                    f'{dt_fmt}</a></td>'
                    f'<td style="padding:5px 8px;font-size:.78rem;color:#1e293b;font-weight:500;white-space:nowrap;">'
                    f'{er["repror"]}&nbsp;{rgist_badge}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;white-space:nowrap;">{ofcps}</td>'
                    f'<td style="padding:5px 8px;font-size:.75rem;color:#1e293b;text-align:right;white-space:nowrap;">{shares_fmt}</td>'
                    f'<td style="padding:5px 8px;text-align:right;white-space:nowrap;">{irds_cell}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<div style="overflow-x:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:8px;">'
                f'<table style="width:100%;border-collapse:collapse;">'
                f'<thead><tr style="background:#f1f5f9;">'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">접수일</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">보고자</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;font-weight:600;">직위</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">보유주식수</th>'
                f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;text-align:right;font-weight:600;">증감</th>'
                f'</tr></thead>'
                f'<tbody>{rows_er}</tbody>'
                f'</table></div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("임원·주요주주 소유보고 데이터를 찾을 수 없습니다.")

        # ────────────────────────────────────
        # ⑤ 연도별 시가총액 추이
        # ────────────────────────────────────
        _section_header("연도별 시가총액 추이")
        with st.spinner("시가총액 데이터 조회 중..."):
            cap_data = fetch_market_cap_history(stock_code)
        if cap_data.get("__error__"):
            st.caption(f"오류: {cap_data['__error__']}")
        elif cap_data:
            cap_years = sorted(k for k in cap_data if not k.startswith("_"))
            cap_vals  = [cap_data[y]["mktcap"] for y in cap_years]
            fig_cap = go.Figure()
            fig_cap.add_trace(go.Bar(
                x=cap_years,
                y=cap_vals,
                marker_color="#2563eb",
                text=[f'{v:,.0f}억' for v in cap_vals],
                textposition="outside",
                textfont=dict(size=9),
            ))
            fig_cap.update_layout(
                title_text="시가총액 (억원)",
                title_font_color="#1e293b", title_font_size=12,
                **PLOTLY_LAYOUT,
            )
            fig_cap.update_yaxes(tickformat=",")
            st.plotly_chart(fig_cap, use_container_width=True)

        # ────────────────────────────────────
        # ⑥ 투자자별 수급
        # ────────────────────────────────────
        _section_header("투자자별 수급 (최근 1년)")
        with st.spinner("수급 데이터 조회 중..."):
            inv_data = fetch_investor_trading(stock_code)
        if inv_data.get("__error__"):
            st.caption(f"오류: {inv_data['__error__']}")
        elif inv_data:
            df_daily = inv_data.get("daily")
            df_total = inv_data.get("total")

            # 누적 순매수 라인 — 개인 / 외국인 / 기관합계
            if df_daily is not None and not df_daily.empty:
                key_inv = [c for c in ["기관합계", "개인", "외국인"] if c in df_daily.columns]
                if key_inv:
                    clr_inv = {"기관합계": "#8b5cf6", "개인": "#2563eb", "외국인": "#dc2626"}
                    fig_inv = go.Figure()
                    for inv in key_inv:
                        cum = df_daily[inv].cumsum() / 1e8
                        fig_inv.add_trace(go.Scatter(
                            name=inv,
                            x=df_daily.index.astype(str).tolist(),
                            y=cum.tolist(),
                            mode="lines",
                            line=dict(color=clr_inv.get(inv, "#64748b"), width=1.5),
                        ))
                    fig_inv.update_layout(
                        title_text="누적 순매수 (억원)",
                        title_font_color="#1e293b", title_font_size=12,
                        **PLOTLY_LAYOUT,
                    )
                    fig_inv.update_yaxes(tickformat=",", ticksuffix="억")
                    st.plotly_chart(fig_inv, use_container_width=True)

            # 기간 합계 — 매수 / 매도 / 순매수 그룹 막대
            if df_total is not None and not df_total.empty:
                show_inv = [i for i in ["기관합계", "개인", "외국인"] if i in df_total.index]
                if show_inv:
                    col_map = {"매수": "#dc2626", "매도": "#2563eb", "순매수": "#f59e0b"}
                    fig_tot = go.Figure()
                    for col, clr in col_map.items():
                        if col in df_total.columns:
                            fig_tot.add_trace(go.Bar(
                                name=col,
                                x=show_inv,
                                y=[df_total.loc[i, col] / 1e8 for i in show_inv],
                                marker_color=clr,
                            ))
                    fig_tot.update_layout(
                        title_text="기간합계 매수·매도·순매수 (억원)",
                        title_font_color="#1e293b", title_font_size=12,
                        barmode="group", **PLOTLY_LAYOUT,
                    )
                    fig_tot.update_yaxes(tickformat=",", ticksuffix="억")
                    st.plotly_chart(fig_tot, use_container_width=True)

        # ────────────────────────────────────
        # ⑦ 밸류에이션 PER / PBR / DIV
        # ────────────────────────────────────
        _section_header("밸류에이션 추이 (월별 PER · PBR · DIV)")
        with st.spinner("밸류에이션 데이터 조회 중..."):
            val_raw = fetch_valuation_history(stock_code)
        if val_raw and val_raw.get("__error__"):
            st.caption(f"오류: {val_raw['__error__']}")
            val_df = None
        else:
            val_df = val_raw.get("df") if val_raw else None
        if val_df is not None and not val_df.empty:
            dates_v = val_df.index.astype(str).tolist()

            # PER / PBR — 이중 Y축
            fig_pb = make_subplots(specs=[[{"secondary_y": True}]])
            if "PER" in val_df.columns:
                fig_pb.add_trace(go.Scatter(
                    name="PER", x=dates_v, y=val_df["PER"].tolist(),
                    mode="lines", line=dict(color="#2563eb", width=1.5),
                ), secondary_y=False)
            if "PBR" in val_df.columns:
                fig_pb.add_trace(go.Scatter(
                    name="PBR", x=dates_v, y=val_df["PBR"].tolist(),
                    mode="lines", line=dict(color="#dc2626", width=1.5),
                ), secondary_y=True)
            fig_pb.update_layout(
                title_text="PER (좌축) · PBR (우축)",
                title_font=dict(size=12, color="#1e293b"),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(248,250,252,1)",
                font=dict(color="#64748b", size=11),
                legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#1e293b", size=11),
                            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=40, t=50, b=10),
                height=280,
                hovermode="x unified",
            )
            fig_pb.update_xaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0")
            fig_pb.update_yaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0", secondary_y=False,
                                 title_text="PER")
            fig_pb.update_yaxes(gridcolor="#e2e8f0", linecolor="#e2e8f0", secondary_y=True,
                                 title_text="PBR")
            st.plotly_chart(fig_pb, use_container_width=True)

            # DIV 배당수익률
            if "DIV" in val_df.columns:
                fig_div = go.Figure()
                fig_div.add_trace(go.Scatter(
                    name="배당수익률",
                    x=dates_v, y=val_df["DIV"].tolist(),
                    mode="lines",
                    line=dict(color="#16a34a", width=1.5),
                    fill="tozeroy", fillcolor="rgba(22,163,74,0.1)",
                ))
                fig_div.update_layout(
                    title_text="배당수익률 DIV (%)",
                    title_font_color="#1e293b", title_font_size=12,
                    **PLOTLY_LAYOUT,
                )
                fig_div.update_yaxes(ticksuffix="%", gridcolor="#e2e8f0")
                st.plotly_chart(fig_div, use_container_width=True)
        elif val_df is None:
            st.caption("밸류에이션 데이터를 불러올 수 없습니다.")


# ─── 차트 ───

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(248,250,252,1)",
    font=dict(color="#64748b", size=11),
    xaxis=dict(gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
    yaxis=dict(gridcolor="#e2e8f0", tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#1e293b", size=11)),
    margin=dict(l=10, r=10, t=30, b=10),
    height=280,
)


def make_bar(years, series, title):
    fig = go.Figure()
    colors_list = [COLORS["blue"], COLORS["red"], COLORS["green"],
                   COLORS["orange"], COLORS["purple"]]
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Bar(name=name, x=years, y=vals,
                             marker_color=colors_list[i % len(colors_list)],
                             marker_line_width=0))
    fig.update_layout(title_text=title, title_font_color="#1e293b",
                      title_font_size=12, barmode="group", **PLOTLY_LAYOUT)
    return fig


def make_line(years, series, title, is_pct=False):
    fig = go.Figure()
    colors_list = [COLORS["orange"], COLORS["purple"], COLORS["green"],
                   COLORS["blue"], COLORS["red"]]
    for i, (name, vals) in enumerate(series.items()):
        fig.add_trace(go.Scatter(name=name, x=years, y=vals, mode="lines+markers",
                                 line=dict(color=colors_list[i % len(colors_list)], width=2),
                                 marker=dict(size=5)))
    suffix = "%" if is_pct else ""
    fig.update_layout(title_text=title, title_font_color="#1e293b",
                      title_font_size=12,
                      yaxis=dict(ticksuffix=suffix, gridcolor="#273047",
                                 tickfont=dict(color="#768390")),
                      **{k: v for k, v in PLOTLY_LAYOUT.items() if k != "yaxis"})
    return fig



# ─── KPI 카드 ───

def kpi_card(label, cur, prev, is_pct=False, invert=False):
    if cur is None:
        val_str = "-"
        delta_html = ""
    else:
        val_str = f"{cur:.1f}%" if is_pct else fmt(cur)
        if prev is not None:
            diff = cur - prev
            if is_pct:
                d_str = f"{abs(diff):.1f}%p"
            else:
                d_str = f"{abs(int(diff)):,}"
                p_str = f"{abs(diff/prev*100):.1f}%" if prev != 0 else "—"
                d_str += f" ({p_str})"
            is_up = diff > 0
            good  = (not invert and is_up) or (invert and not is_up)
            cls   = "up" if good else "down" if diff != 0 else "flat"
            sym   = "▲" if diff > 0 else "▼" if diff < 0 else "—"
            delta_html = f'<div class="metric-delta {cls}">{sym} {d_str}</div>'
        else:
            delta_html = '<div class="metric-delta flat">전년 데이터 없음</div>'

    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{val_str}</div>
      {delta_html}
    </div>
    """, unsafe_allow_html=True)


# ─── 메인 UI ───

def main():
    # API 키 확인
    if not DART_KEY:
        st.error(
            "DART API 키가 설정되지 않았습니다.\n\n"
            "**로컬 실행:** 프로젝트 루트에 `.streamlit/secrets.toml` 파일을 만들고 아래 내용을 추가하세요.\n"
            "```\nDART_KEY = \"your_dart_api_key\"\n```\n\n"
            "**Streamlit Cloud:** 앱 설정 → Secrets 에 동일하게 입력하세요."
        )
        st.stop()

    # 헤더 (스티키 — 스크롤해도 상단 고정)
    st.markdown("""
    <div style="position:sticky;top:0;z-index:999;
                background:#fff;
                border-bottom:1px solid #e2e8f0;
                box-shadow:0 1px 4px rgba(0,0,0,.06);
                padding:14px 20px;margin:-1rem -1rem 1.2rem -1rem;
                display:flex;align-items:center;gap:12px;">
      <div style="width:38px;height:38px;border-radius:10px;flex-shrink:0;
                  background:linear-gradient(135deg,#2563eb,#7c3aed);
                  display:flex;align-items:center;justify-content:center;font-size:18px;">📊</div>
      <div>
        <div class="dart-title" style="font-size:1.15rem;font-weight:700;color:#1e293b;line-height:1.2;">기업 주식 시황 및 재무 대시보드</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 검색 영역
    col1, col2 = st.columns([4, 1])
    with col1:
        query = st.text_input("", placeholder="회사명 또는 종목코드 입력 (예: 삼성전자, samsung, 005930)",
                              label_visibility="collapsed", key="query")
    with col2:
        search_btn = st.button("🔍 검색")

    # 기업 목록 로드
    if search_btn and query:
        st.session_state["search_query"] = query
        st.session_state["selected_corp"] = None
        st.session_state["data"] = None

    if "search_query" not in st.session_state:
        st.markdown("""
        <div style="text-align:center;padding:3rem;color:#768390;">
          <div style="font-size:2rem;margin-bottom:1rem;">📊</div>
          <div>회사명 또는 종목코드를 입력하고 검색하세요</div>
          <div style="font-size:.8rem;margin-top:.5rem;">K-IFRS 기준 최대 15년 재무제표를 불러옵니다</div>
        </div>
        """, unsafe_allow_html=True)
        return

    # 기업 검색
    with st.spinner("기업 목록 조회 중..."):
        try:
            all_corps = load_corp_list()
        except Exception as e:
            st.error(f"기업 목록을 불러올 수 없습니다: {e}")
            return

    q = st.session_state.get("search_query", "")
    results = search_corps(q, all_corps)

    if not results:
        st.warning(f"'{q}' 검색 결과가 없습니다. 공식 기업명으로 다시 검색해주세요.")
        return

    # 기업 선택
    if len(results) == 1:
        st.session_state["selected_corp"] = results[0]
    else:
        options = [f"{c['corp_name']}  {'[상장:'+c['stock_code']+']' if c['stock_code'] else '[비상장]'}  ({c['corp_code']})"
                   for c in results]
        sel_idx = st.selectbox("검색 결과에서 선택하세요", range(len(options)),
                               format_func=lambda i: options[i], key="corp_select")
        st.session_state["selected_corp"] = results[sel_idx]

    corp = st.session_state.get("selected_corp")
    if not corp:
        return

    # 기업 개요 조회
    with st.spinner("기업 정보 조회 중..."):
        ov = fetch_company_overview(corp["corp_code"], corp.get("stock_code", ""))

    # 기업 카드
    cls_badge = (f'<span style="background:#eff6ff;color:#2563eb;font-size:.68rem;'
                 f'border-radius:4px;padding:2px 7px;margin-left:8px;font-weight:600;">'
                 f'{ov.get("corp_cls","")}</span>') if ov.get("corp_cls") else ""

    meta_rows = []
    if ov.get("ceo_nm"):   meta_rows.append(f'<span><b>대표</b> {ov["ceo_nm"]}</span>')
    if ov.get("est_dt"):   meta_rows.append(f'<span><b>설립</b> {ov["est_dt"]}</span>')
    if ov.get("acc_mt"):   meta_rows.append(f'<span><b>결산</b> {ov["acc_mt"]}</span>')
    if ov.get("phn_no"):   meta_rows.append(f'<span><b>전화</b> {ov["phn_no"]}</span>')
    meta_html = (''.join(
        f'<span style="color:#94a3b8;margin:0 6px;">|</span>{m}' if i else m
        for i, m in enumerate(meta_rows)
    )) if meta_rows else ""

    addr_html = (f'<div style="font-size:.72rem;color:#64748b;margin-top:4px;">'
                 f'📍 {ov["adres"]}</div>') if ov.get("adres") else ""
    url_html  = (f'<div style="font-size:.72rem;margin-top:2px;">'
                 f'🌐 <a href="{ov["hm_url"]}" target="_blank" style="color:#2563eb;">'
                 f'{ov["hm_url"]}</a></div>') if ov.get("hm_url") else ""

    st.markdown(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;
                box-shadow:0 1px 3px rgba(0,0,0,.06);
                padding:14px 18px;margin:12px 0;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:{'8px' if meta_rows else '0'};">
        <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);border-radius:8px;
                    padding:4px 12px;font-weight:700;color:#fff;flex-shrink:0;">
          {corp['corp_name'][:2]}</div>
        <div style="flex:1;">
          <div style="font-weight:700;color:#1e293b;font-size:1.05rem;">
            {corp['corp_name']}{cls_badge}</div>
          <div style="font-size:.72rem;color:#94a3b8;margin-top:2px;">
            코드: {corp['corp_code']}
            {'&nbsp;·&nbsp;상장: '+corp['stock_code'] if corp['stock_code'] else ''}
          </div>
        </div>
      </div>
      {f'<div style="font-size:.78rem;color:#475569;margin-top:4px;">{meta_html}</div>' if meta_html else ''}
      {addr_html}{url_html}
    </div>
    """, unsafe_allow_html=True)

    # 환율 + 미국채 카드
    md = fetch_market_data()
    if md and md.get("usd_krw"):
        def fx_item(label, value, chg, unit="", fmt=".1f"):
            if value is None:
                return ""
            if chg is not None and chg != 0:
                sym_c  = "▲" if chg > 0 else "▼"
                color  = "#dc2626" if chg > 0 else "#2563eb"
                chg_html = (f'<span style="font-size:.62rem;color:{color};margin-left:3px;">'
                            f'{sym_c}{abs(chg):{fmt}}</span>')
            else:
                chg_html = ""
            val_str = f"{value:,.3f}" if fmt == ".3f" else (f"{value:,.2f}" if fmt == ".2f" else f"{value:,.1f}")
            unit_html = (f'<span style="font-size:.65rem;font-weight:400;color:#94a3b8;margin-left:2px;">{unit}</span>'
                         if unit else "")
            return (f'<div style="flex:1;min-width:45%;text-align:center;padding:8px 6px;">'
                    f'<div style="font-size:.65rem;color:#64748b;margin-bottom:2px;white-space:nowrap;">{label}</div>'
                    f'<div style="font-size:.95rem;font-weight:700;color:#1e293b;white-space:nowrap;">'
                    f'{val_str}{chg_html}{unit_html}</div>'
                    f'</div>')
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
            unsafe_allow_html=True
        )

    # ══ 메인 3탭 ══
    tab_stock, tab_fs, tab_news, tab_emp = st.tabs(["📈 주식", "📊 재무제표", "📢 공시 · 뉴스", "👥 직원 현황"])

    # ────────────────────────────────────────
    # 탭 1 : 주식
    # ────────────────────────────────────────
    with tab_stock:
        render_stock_chart(corp.get("stock_code", ""), corp["corp_name"],
                           ov.get("corp_cls_raw", "Y"), corp_code=corp.get("corp_code", ""))

    # ────────────────────────────────────────
    # 탭 2 : 재무제표
    # ────────────────────────────────────────
    with tab_fs:
        cache_key = f"{corp['corp_code']}_data"
        need_fetch = (
            cache_key not in st.session_state
            or st.session_state.get(cache_key + "_corp") != corp["corp_code"]
            or st.session_state.get(cache_key + "_ver")  != _CACHE_VER
            or st.session_state.get(cache_key + "_years") != (YEARS[0], YEARS[-1])
        )
        if need_fetch:
            with st.spinner(f"{corp['corp_name']} 재무데이터 수집 중 (K-IFRS 기준 최대 15년)..."):
                data = fetch_all_years(corp["corp_code"], "CFS")
                if not data:
                    data = fetch_all_years(corp["corp_code"], "OFS")
                    fs_div = "OFS"
                else:
                    fs_div = "CFS"
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
        else:
            years = sorted(data.keys())
            fs_label = "연결재무제표" if fs_div == "CFS" else "별도재무제표"
            st.caption(f"{fs_label} 기준 · {years[0]}~{years[-1]} · 단위: 억원")

            # KPI 카드
            ly = years[-1]
            py = years[-2] if len(years) >= 2 else None
            ld = data[ly]
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

            # 재무제표 서브탭
            sub_bs, sub_is, sub_cf = st.tabs(["📋 재무상태표", "💰 손익계산서", "💧 현금흐름표"])

            with sub_bs:
                fig = make_bar(years,
                               {"자산총계": [data[y]["bs"].get("assets")     for y in years],
                                "부채총계": [data[y]["bs"].get("liabilities") for y in years],
                                "자본총계": [data[y]["bs"].get("equity")      for y in years]},
                               "자산 · 부채 · 자본 (억원)")
                st.plotly_chart(fig, use_container_width=True)
                fig = make_line(years,
                                {"부채비율(%)":     [pct(data[y]["bs"].get("liabilities"), data[y]["bs"].get("equity")) for y in years],
                                 "자기자본비율(%)": [pct(data[y]["bs"].get("equity"),      data[y]["bs"].get("assets"))  for y in years]},
                                "부채비율 & 자기자본비율", is_pct=True)
                st.plotly_chart(fig, use_container_width=True)
                fig_re = make_line(years,
                                   {"이익잉여금": [data[y]["bs"].get("retainedEarnings") for y in years]},
                                   "이익잉여금 추이 (억원)")
                st.plotly_chart(fig_re, use_container_width=True)
                rows = []
                for y in reversed(years):
                    b = data[y]["bs"]
                    dr = pct(b.get("liabilities"), b.get("equity"))
                    er = pct(b.get("equity"), b.get("assets"))
                    rows.append({"연도": y, "자산총계": fmt(b.get("assets")),
                                 "부채총계": fmt(b.get("liabilities")), "자본총계": fmt(b.get("equity")),
                                 "이익잉여금": fmt(b.get("retainedEarnings")),
                                 "부채비율": f"{dr:.1f}%" if dr else "-",
                                 "자기자본비율": f"{er:.1f}%" if er else "-"})
                st.dataframe(rows, hide_index=True, use_container_width=True)

            with sub_is:
                fig = make_bar(years,
                               {"매출액":   [data[y]["is"].get("revenue")   for y in years],
                                "영업이익": [data[y]["is"].get("opIncome")  for y in years],
                                "순이익":   [data[y]["is"].get("netIncome") for y in years]},
                               "매출 · 영업이익 · 순이익 (억원)")
                st.plotly_chart(fig, use_container_width=True)
                fig = make_line(years,
                                {"영업이익률(%)": [pct(data[y]["is"].get("opIncome"),  data[y]["is"].get("revenue")) for y in years],
                                 "순이익률(%)":   [pct(data[y]["is"].get("netIncome"), data[y]["is"].get("revenue")) for y in years]},
                                "이익률 추이", is_pct=True)
                st.plotly_chart(fig, use_container_width=True)
                rows = []
                for y in reversed(years):
                    s = data[y]["is"]
                    opm = pct(s.get("opIncome"),  s.get("revenue"))
                    npm = pct(s.get("netIncome"), s.get("revenue"))
                    rows.append({"연도": y, "매출액": fmt(s.get("revenue")),
                                 "영업이익": fmt(s.get("opIncome")), "순이익": fmt(s.get("netIncome")),
                                 "영업이익률": f"{opm:.1f}%" if opm else "-",
                                 "순이익률":   f"{npm:.1f}%" if npm else "-"})
                st.dataframe(rows, hide_index=True, use_container_width=True)

            with sub_cf:
                fig = make_bar(years,
                               {"영업CF": [data[y]["cf"].get("opCF")  for y in years],
                                "투자CF": [data[y]["cf"].get("invCF") for y in years],
                                "재무CF": [data[y]["cf"].get("finCF") for y in years]},
                               "현금흐름 (억원)")
                st.plotly_chart(fig, use_container_width=True)
                fig = make_line(years,
                                {"기말현금": [data[y]["cf"].get("endCash") for y in years]},
                                "기말현금 추이 (억원)")
                st.plotly_chart(fig, use_container_width=True)
                rows = []
                for y in reversed(years):
                    c = data[y]["cf"]
                    rows.append({"연도": y, "영업CF": fmt(c.get("opCF")),
                                 "투자CF": fmt(c.get("invCF")), "재무CF": fmt(c.get("finCF")),
                                 "기말현금": fmt(c.get("endCash"))})
                st.dataframe(rows, hide_index=True, use_container_width=True)

    # ────────────────────────────────────────
    # 탭 3 : 공시 · 뉴스
    # ────────────────────────────────────────
    with tab_news:
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
                    unsafe_allow_html=True
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
                    unsafe_allow_html=True
                )
        else:
            st.caption("뉴스를 불러올 수 없습니다.")

    # ────────────────────────────────────────
    # 탭 4 : 직원 현황
    # ────────────────────────────────────────
    with tab_emp:
        with st.spinner("직원 현황 조회 중..."):
            emp_data = fetch_employee_status(corp["corp_code"], cache_ver=_CACHE_VER)

        if not emp_data:
            st.caption("직원 현황 데이터를 찾을 수 없습니다.")
        else:
            eyears = sorted(emp_data.keys())   # 문자열 연도 오름차순

            # ── ① 정규직 남/여 누적 막대 ──
            fig_emp = go.Figure()
            fig_emp.add_trace(go.Bar(
                name="남 정규직",
                x=eyears,
                y=[emp_data[y].get("male", 0) for y in eyears],
                marker_color="#2563eb",
                text=[f'{emp_data[y].get("male", 0):,}' for y in eyears],
                textposition="inside",
                textfont=dict(size=9, color="white"),
            ))
            fig_emp.add_trace(go.Bar(
                name="여 정규직",
                x=eyears,
                y=[emp_data[y].get("female", 0) for y in eyears],
                marker_color="#ec4899",
                text=[f'{emp_data[y].get("female", 0):,}' for y in eyears],
                textposition="inside",
                textfont=dict(size=9, color="white"),
            ))
            fig_emp.add_trace(go.Scatter(
                name="전체합계",
                x=eyears,
                y=[emp_data[y].get("total", 0) for y in eyears],
                mode="lines+markers+text",
                line=dict(color="#f59e0b", width=2),
                marker=dict(size=5),
                text=[f'{emp_data[y].get("total", 0):,}' for y in eyears],
                textposition="top center",
                textfont=dict(size=9, color="#b45309"),
            ))
            fig_emp.update_layout(
                title_text="정규직 직원 수 추이 (명)",
                title_font_color="#1e293b", title_font_size=12,
                barmode="stack", **PLOTLY_LAYOUT,
            )
            st.plotly_chart(fig_emp, use_container_width=True)

            # ── ② 평균 근속연수 ──
            fig_tenure = go.Figure()
            fig_tenure.add_trace(go.Scatter(
                name="남", x=eyears,
                y=[emp_data[y].get("avg_tenure_m", 0) for y in eyears],
                mode="lines+markers",
                line=dict(color="#2563eb", width=2), marker=dict(size=5),
            ))
            fig_tenure.add_trace(go.Scatter(
                name="여", x=eyears,
                y=[emp_data[y].get("avg_tenure_f", 0) for y in eyears],
                mode="lines+markers",
                line=dict(color="#ec4899", width=2), marker=dict(size=5),
            ))
            fig_tenure.update_layout(
                title_text="평균 근속연수 (년)",
                title_font_color="#1e293b", title_font_size=12,
                **PLOTLY_LAYOUT,
            )
            fig_tenure.update_yaxes(ticksuffix="년", gridcolor="#e2e8f0")
            st.plotly_chart(fig_tenure, use_container_width=True)

            # ── ③ 1인 평균 연봉 (데이터 있는 연도만) ──
            sal_years = [y for y in eyears
                         if emp_data[y].get("salary_m") or emp_data[y].get("salary_f")]
            if sal_years:
                def _to_man(v):   # 원 → 만원
                    return round((v or 0) / 10_000)
                fig_sal = go.Figure()
                fig_sal.add_trace(go.Bar(
                    name="남",
                    x=sal_years,
                    y=[_to_man(emp_data[y].get("salary_m")) for y in sal_years],
                    marker_color="#2563eb",
                    text=[f'{_to_man(emp_data[y].get("salary_m")):,}만' for y in sal_years],
                    textposition="outside", textfont=dict(size=9),
                ))
                fig_sal.add_trace(go.Bar(
                    name="여",
                    x=sal_years,
                    y=[_to_man(emp_data[y].get("salary_f")) for y in sal_years],
                    marker_color="#ec4899",
                    text=[f'{_to_man(emp_data[y].get("salary_f")):,}만' for y in sal_years],
                    textposition="outside", textfont=dict(size=9),
                ))
                fig_sal.update_layout(
                    title_text="1인 평균 연봉 (만원)",
                    title_font_color="#1e293b", title_font_size=12,
                    barmode="group", **PLOTLY_LAYOUT,
                )
                fig_sal.update_yaxes(ticksuffix="만", gridcolor="#e2e8f0")
                st.plotly_chart(fig_sal, use_container_width=True)

            # ── 데이터 테이블 ──
            tbl_rows = []
            for y in reversed(eyears):
                d = emp_data[y]
                def _sal_fmt(v):
                    return f'{round((v or 0)/10_000):,}만원' if v else "-"
                tbl_rows.append({
                    "연도":        y,
                    "전체합계":    f'{d.get("total", 0):,}',
                    "남 정규직":   f'{d.get("male", 0):,}',
                    "여 정규직":   f'{d.get("female", 0):,}',
                    "남 계약직":   f'{d.get("male_contract", 0):,}',
                    "여 계약직":   f'{d.get("female_contract", 0):,}',
                    "남 근속(년)": d.get("avg_tenure_m", "-"),
                    "여 근속(년)": d.get("avg_tenure_f", "-"),
                    "남 연봉":     _sal_fmt(d.get("salary_m")),
                    "여 연봉":     _sal_fmt(d.get("salary_f")),
                })
            st.dataframe(tbl_rows, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════
#  메인
# ══════════════════════════════════════════
if __name__ == "__main__":
    main()
