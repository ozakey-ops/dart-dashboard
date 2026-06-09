"""
다트 재무 대시보드 — Streamlit 모바일 웹앱
============================================
설치:  pip install streamlit plotly requests
실행:  streamlit run streamlit_app.py
배포:  share.streamlit.io (무료)
"""

import streamlit as st
import requests
import zipfile
import io
import xml.etree.ElementTree as ET
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ══════════════════════════════════════════
#  ★ 설정 — API Key 입력
# ══════════════════════════════════════════
DART_KEY = "901de77da059b85e095a99ab9f2baf3264f7281f"
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
_CACHE_VER = 9

COLORS = {
    "blue":   "#2563eb",
    "red":    "#dc2626",
    "green":  "#16a34a",
    "orange": "#ea580c",
    "purple": "#7c3aed",
}

# ─── 페이지 설정 ───

st.set_page_config(
    page_title="기업 재무 대시보드",
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


def search_corps(name, all_corps):
    exact   = [c for c in all_corps if c["corp_name"] == name]
    partial = [c for c in all_corps if name in c["corp_name"]]
    matches = exact if exact else partial
    if not matches:
        return []
    matches.sort(key=lambda c: (c["corp_name"] != name, not bool(c["stock_code"]), c["corp_name"]))
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


# ─── 환율 ───

@st.cache_data(ttl=3600, show_spinner=False)   # 1시간 캐시
def fetch_exchange_rates():
    """Frankfurter API로 환율 + 전일 대비 변화 조회."""
    try:
        from datetime import timedelta
        # 최신 환율
        r = requests.get("https://api.frankfurter.app/latest?from=USD&to=KRW,JPY", timeout=8)
        d = r.json()
        krw = d["rates"]["KRW"]
        jpy = d["rates"]["JPY"]
        latest_date = d.get("date", "")

        # 최근 5거래일 시계열로 전일 데이터 확보
        start = (datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        r2 = requests.get(
            f"https://api.frankfurter.app/{start}..{latest_date}?from=USD&to=KRW,JPY",
            timeout=8
        )
        d2 = r2.json()
        dates_sorted = sorted(d2.get("rates", {}).keys())

        krw_prev = jpy_prev = None
        if len(dates_sorted) >= 2:
            prev = d2["rates"][dates_sorted[-2]]
            krw_prev = prev.get("KRW")
            jpy_prev = prev.get("JPY")

        def chg(cur, prev):
            if cur is None or prev is None:
                return None
            return round(cur - prev, 2)

        usd_krw    = round(krw, 1)
        jpy100_krw = round(krw / jpy * 100, 1)
        jpy_usd    = round(jpy, 2)

        usd_krw_chg    = chg(krw, krw_prev)
        jpy100_krw_chg = chg(krw / jpy * 100, (krw_prev / jpy_prev * 100) if krw_prev and jpy_prev else None)
        jpy_usd_chg    = chg(jpy, jpy_prev)

        return {
            "usd_krw":         usd_krw,
            "jpy100_krw":      jpy100_krw,
            "jpy_usd":         jpy_usd,
            "usd_krw_chg":     round(usd_krw_chg, 1)    if usd_krw_chg    is not None else None,
            "jpy100_krw_chg":  round(jpy100_krw_chg, 1) if jpy100_krw_chg is not None else None,
            "jpy_usd_chg":     round(jpy_usd_chg, 2)    if jpy_usd_chg    is not None else None,
            "date":            latest_date,
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
def fetch_disclosures(corp_code, count=5):
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
def fetch_news(company_name, count=5):
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


def render_stock_chart(stock_code, corp_name, corp_cls="Y"):
    """캔들스틱 + 거래량 차트 (일/월/연봉 선택)."""
    if not stock_code:
        return
    # 기간 선택 + 이평선 입력 (한 줄)
    col_period, col_ma1, col_ma2 = st.columns([5, 1, 1])
    with col_period:
        period_labels = ["6달", "2년", "3년", "월봉", "연봉"]
        sel = st.radio("기간", period_labels, horizontal=True,
                       key=f"sp_{stock_code}", label_visibility="collapsed")
    with col_ma1:
        ma_period1 = int(st.number_input("이평선1", min_value=0, max_value=300,
                                         value=25, key=f"ma1b_{stock_code}"))
    with col_ma2:
        ma_period2 = int(st.number_input("이평선2", min_value=0, max_value=300,
                                         value=200, key=f"ma2b_{stock_code}"))
    tf_map = {"6달": "6mo", "2년": "24mo", "3년": "36mo", "월봉": "month", "연봉": "year"}
    hint = "  ·  두 번 탭  자동 스케일"
    title_map = {
        "6달": f"{corp_name}  일봉 (최근 6개월){hint}",
        "2년": f"{corp_name}  일봉 (최근 2년){hint}",
        "3년": f"{corp_name}  일봉 (최근 3년){hint}",
        "월봉": f"{corp_name}  월봉 (최근 10년){hint}",
        "연봉": f"{corp_name}  연봉 (최근 20년){hint}",
    }
    is_daily = sel in ("6달", "2년", "3년")

    with st.spinner("주가 데이터 조회 중..."):
        chart_data = fetch_stock_chart(stock_code, corp_cls, tf_map[sel], _ver=6)
    if not chart_data:
        st.caption("주가 데이터를 불러올 수 없습니다.")
        return
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
        title=dict(text=title_map[sel], font=dict(size=13, color="#1e293b"), x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(248,250,252,1)",
        font=dict(color="#64748b", size=11),
        xaxis_rangeslider_visible=False,
        margin=dict(l=8, r=8, t=38, b=8),
        height=420,
        showlegend=show_ma,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
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
        <div style="font-size:1.15rem;font-weight:700;color:#1e293b;line-height:1.2;">DART 재무 대시보드</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 검색 영역
    col1, col2 = st.columns([4, 1])
    with col1:
        query = st.text_input("", placeholder="회사명 입력 (예: 삼성전자)",
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
          <div>회사명을 입력하고 검색하세요</div>
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

    # 환율 카드
    fx = fetch_exchange_rates()
    if fx:
        def fx_item(label, value, chg, unit="원"):
            if chg is not None and chg != 0:
                sym   = "▲" if chg > 0 else "▼"
                color = "#dc2626" if chg > 0 else "#2563eb"
                chg_html = (f'<span style="font-size:.65rem;color:{color};margin-left:4px;">'
                            f'{sym}{abs(chg):,.2f}</span>')
            else:
                chg_html = ""
            return (f'<div style="flex:1;text-align:center;padding:8px 4px;">'
                    f'<div style="font-size:.68rem;color:#64748b;margin-bottom:3px;">{label}</div>'
                    f'<div style="font-size:1rem;font-weight:700;color:#1e293b;">'
                    f'{value:,.1f}{chg_html}'
                    f'<span style="font-size:.68rem;font-weight:400;color:#94a3b8;margin-left:3px;">{unit}</span></div>'
                    f'</div>')
        st.markdown(
            f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:4px 8px;margin:0 0 12px 0;">'
            f'<div style="display:flex;align-items:center;border-bottom:none;">'
            f'{fx_item("원 / 달러",  fx["usd_krw"],    fx.get("usd_krw_chg"))}'
            f'<div style="color:#e2e8f0;">│</div>'
            f'{fx_item("원 / 100엔", fx["jpy100_krw"], fx.get("jpy100_krw_chg"))}'
            f'<div style="color:#e2e8f0;">│</div>'
            f'{fx_item("엔 / 달러",  fx["jpy_usd"],    fx.get("jpy_usd_chg"), "엔")}'
            f'</div>'
            f'<div style="text-align:right;font-size:.62rem;color:#cbd5e1;padding:0 8px 4px;">'
            f'기준일 {fx["date"]}</div>'
            f'</div>',
            unsafe_allow_html=True
        )

    # 주가 차트
    render_stock_chart(corp.get("stock_code", ""), corp["corp_name"], ov.get("corp_cls_raw", "Y"))

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
        st.session_state[cache_key]           = data
        st.session_state[cache_key + "_fs"]   = fs_div
        st.session_state[cache_key + "_corp"] = corp["corp_code"]
        st.session_state[cache_key + "_ver"]  = _CACHE_VER
        st.session_state[cache_key + "_years"] = (YEARS[0], YEARS[-1])
    else:
        data   = st.session_state[cache_key]
        fs_div = st.session_state.get(cache_key + "_fs", "CFS")

    if not data:
        st.error("재무데이터를 불러올 수 없습니다.")
        return

    years = sorted(data.keys())
    fs_label = "연결재무제표" if fs_div == "CFS" else "별도재무제표"
    st.caption(f"{fs_label} 기준 · {years[0]}~{years[-1]} · 단위: 억원")

    # ── KPI 카드 ──
    ly = years[-1]
    py = years[-2] if len(years) >= 2 else None
    ld = data[ly]
    pd = data[py] if py else {}

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("매출액 (최근)", ld["is"].get("revenue"),   pd.get("is", {}).get("revenue"))
        kpi_card("자산총계 (최근)", ld["bs"].get("assets"),  pd.get("bs", {}).get("assets"))
    with c2:
        kpi_card("영업이익 (최근)", ld["is"].get("opIncome"),  pd.get("is", {}).get("opIncome"))
        kpi_card("부채비율", pct(ld["bs"].get("liabilities"), ld["bs"].get("equity")),
                 pct(pd.get("bs", {}).get("liabilities"), pd.get("bs", {}).get("equity")),
                 is_pct=True, invert=True)
    with c3:
        kpi_card("순이익 (최근)", ld["is"].get("netIncome"), pd.get("is", {}).get("netIncome"))
        kpi_card("영업이익률", pct(ld["is"].get("opIncome"), ld["is"].get("revenue")),
                 pct(pd.get("is", {}).get("opIncome"), pd.get("is", {}).get("revenue")),
                 is_pct=True)

    st.divider()

    # ── 탭 ──
    tab_bs, tab_is, tab_cf = st.tabs(["📋 재무상태표", "💰 손익계산서", "💧 현금흐름표"])

    # 재무상태표
    with tab_bs:
        c1, c2 = st.columns(2)
        with c1:
            fig = make_bar(years,
                           {"자산총계": [data[y]["bs"].get("assets")      for y in years],
                            "부채총계": [data[y]["bs"].get("liabilities")  for y in years],
                            "자본총계": [data[y]["bs"].get("equity")       for y in years]},
                           "자산 · 부채 · 자본 (억원)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = make_line(years,
                            {"부채비율(%)":     [pct(data[y]["bs"].get("liabilities"), data[y]["bs"].get("equity")) for y in years],
                             "자기자본비율(%)": [pct(data[y]["bs"].get("equity"),      data[y]["bs"].get("assets"))  for y in years]},
                            "부채비율 & 자기자본비율", is_pct=True)
            st.plotly_chart(fig, use_container_width=True)

        re_data = {"이익잉여금": [data[y]["bs"].get("retainedEarnings") for y in years]}
        fig_re = make_line(years, re_data, "이익잉여금 추이 (억원)")
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

    # 손익계산서
    with tab_is:
        c1, c2 = st.columns(2)
        with c1:
            fig = make_bar(years,
                           {"매출액":   [data[y]["is"].get("revenue")   for y in years],
                            "영업이익": [data[y]["is"].get("opIncome")  for y in years],
                            "순이익":   [data[y]["is"].get("netIncome") for y in years]},
                           "매출 · 영업이익 · 순이익 (억원)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
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
                         "영업이익": fmt(s.get("opIncome")),
                         "순이익":   fmt(s.get("netIncome")),
                         "영업이익률": f"{opm:.1f}%" if opm else "-",
                         "순이익률":   f"{npm:.1f}%" if npm else "-"})
        st.dataframe(rows, hide_index=True, use_container_width=True)

    # 현금흐름표
    with tab_cf:
        c1, c2 = st.columns(2)
        with c1:
            fig = make_bar(years,
                           {"영업CF":  [data[y]["cf"].get("opCF")   for y in years],
                            "투자CF":  [data[y]["cf"].get("invCF")  for y in years],
                            "재무CF":  [data[y]["cf"].get("finCF")  for y in years]},
                           "현금흐름 (억원)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = make_line(years,
                            {"기말현금": [data[y]["cf"].get("endCash") for y in years]},
                            "기말현금 추이 (억원)")
            st.plotly_chart(fig, use_container_width=True)

        rows = []
        for y in reversed(years):
            c = data[y]["cf"]
            rows.append({"연도": y,
                         "영업CF":  fmt(c.get("opCF")),
                         "투자CF":  fmt(c.get("invCF")),
                         "재무CF":  fmt(c.get("finCF")),
                         "기말현금": fmt(c.get("endCash"))})
        st.dataframe(rows, hide_index=True, use_container_width=True)

    st.divider()

    # ── 공시 ──
    st.subheader("📢 최근 공시")
    with st.spinner("공시 조회 중..."):
        discs, disc_label = fetch_disclosures(corp["corp_code"])
    if discs:
        for d in discs:
            link_html = (f'<a href="{d["link"]}" target="_blank" '
                         f'style="color:#2563eb;text-decoration:none;">' 
                         f'{d["report_nm"]}</a>') if d["link"] else d["report_nm"]
            badge_html = (f'<span style="background:#f1f5f9;color:#475569;'
                          f'font-size:.65rem;border-radius:3px;padding:1px 5px;'
                          f'margin-right:5px;">{d["corp_cls"]}</span>') if d["corp_cls"] else ""
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid #f1f5f9;">' 
                f'{badge_html}' 
                f'<span style="font-size:.88rem;color:#1e293b;">{link_html}</span>' 
                f'<span style="float:right;font-size:.72rem;color:#94a3b8;">' 
                f'{d["rcept_dt"]} · {d["flr_nm"]}</span></div>',
                unsafe_allow_html=True
            )
    else:
        st.caption(f"공시 없음 — {disc_label}")

    st.divider()

    # ── 뉴스 ──
    st.subheader("📰 최근 뉴스")
    with st.spinner("뉴스 수집 중..."):
        news = fetch_news(corp["corp_name"])
    if news:
        for n in news:
            st.markdown(
                f'<div style="padding:8px 0;border-bottom:1px solid #f1f5f9;">' 
                f'<a href="{n["link"]}" target="_blank" ' 
                f'style="font-size:.88rem;color:#1e293b;text-decoration:none;">' 
                f'{n["title"]}</a>' 
                f'<div style="font-size:.72rem;color:#94a3b8;margin-top:2px;">' 
                f'{n["source"]}  ·  {n["date"]}</div></div>',
                unsafe_allow_html=True
            )
    else:
        st.caption("뉴스를 불러올 수 없습니다.")


# ══════════════════════════════════════════
#  메인
# ══════════════════════════════════════════
if __name__ == "__main__":
    main()
