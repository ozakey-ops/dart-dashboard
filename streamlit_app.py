"""
DART 재무 대시보드 — Streamlit 모바일 웹앱
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

BASE       = "https://opendart.fss.or.kr/api"
YEARS      = list(range(2006, 2026))

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
_CACHE_VER = 5

COLORS = {
    "blue":   "#2563eb",
    "red":    "#dc2626",
    "green":  "#16a34a",
    "orange": "#ea580c",
    "purple": "#7c3aed",
    "yellow": "#ca8a04",
}

# ─── 페이지 설정 ───

st.set_page_config(
    page_title="DART 재무 대시보드",
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
    """거래소 공시(pblntf_ty=I) 우선, 없으면 전체 공시에서 최신 5건."""
    base_params = {
        "crtfc_key":  DART_KEY,
        "corp_code":  corp_code,
        "page_count": max(count * 3, 15),   # 여유 있게 조회
        "page_no":    1,
        "sort":       "date",
        "sort_mth":   "desc",
    }
    # 1차: 거래소 공시
    try:
        r = requests.get(f"{BASE}/list.json",
                         params={**base_params, "pblntf_ty": "I"}, timeout=10)
        d = r.json()
        if d.get("status") == "000" and d.get("list"):
            return _parse_disc_list(d["list"], count), "거래소공시"
    except Exception:
        pass
    # 2차: 정기공시 (사업보고서·분기보고서 등)
    try:
        r = requests.get(f"{BASE}/list.json",
                         params={**base_params, "pblntf_ty": "A"}, timeout=10)
        d = r.json()
        if d.get("status") == "000" and d.get("list"):
            return _parse_disc_list(d["list"], count), "정기공시"
    except Exception:
        pass
    # 3차: 전체 공시 (필터 없음)
    try:
        r = requests.get(f"{BASE}/list.json", params=base_params, timeout=10)
        d = r.json()
        if d.get("status") == "000" and d.get("list"):
            return _parse_disc_list(d["list"], count), "전체공시"
        return [], d.get("message", "조회 결과 없음")
    except Exception as e:
        return [], str(e)


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
    fig.update_layout(title_text=title, title_font_color="#cdd9e5",
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
    fig.update_layout(title_text=title, title_font_color="#cdd9e5",
                      title_font_size=12,
                      yaxis=dict(ticksuffix=suffix, gridcolor="#273047",
                                 tickfont=dict(color="#768390")),
                      **{k: v for k, v in PLOTLY_LAYOUT.items() if k != "yaxis"})
    return fig


def make_mixed(years, bar_series, line_series, title):
    fig = make_subplots(specs=[[{"secondary_y": False}]])
    for name, vals in bar_series.items():
        fig.add_trace(go.Bar(name=name, x=years, y=vals,
                             marker_color=COLORS["blue"], opacity=0.75,
                             marker_line_width=0))
    line_colors = [COLORS["orange"], COLORS["purple"]]
    for i, (name, vals) in enumerate(line_series.items()):
        fig.add_trace(go.Scatter(name=name, x=years, y=vals, mode="lines+markers",
                                 line=dict(color=line_colors[i], width=2),
                                 marker=dict(size=5)))
    fig.update_layout(title_text=title, title_font_color="#cdd9e5",
                      title_font_size=12, barmode="group", **PLOTLY_LAYOUT)
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
        <div style="font-size:.72rem;color:#64748b;margin-top:2px;">전자공시 OpenAPI · 최대 20년 재무제표 분석</div>
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
          <div style="font-size:.8rem;margin-top:.5rem;">최대 20년치 재무제표를 자동으로 불러옵니다</div>
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

    # 재무데이터 로드
    st.markdown(f"""
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;
                box-shadow:0 1px 3px rgba(0,0,0,.06);
                padding:12px 18px;margin:12px 0;display:flex;align-items:center;gap:12px;">
      <div style="background:linear-gradient(135deg,#2563eb,#7c3aed);border-radius:8px;
                  padding:4px 12px;font-weight:700;color:#fff;">{corp['corp_name'][:2]}</div>
      <div>
        <div style="font-weight:700;color:#1e293b;">{corp['corp_name']}</div>
        <div style="font-size:.72rem;color:#64748b;">코드: {corp['corp_code']}
          {'&nbsp;·&nbsp;상장: '+corp['stock_code'] if corp['stock_code'] else ''}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    cache_key = f"{corp['corp_code']}_data"
    if cache_key not in st.session_state or st.session_state.get(cache_key + "_corp") != corp["corp_code"]:
        with st.spinner(f"{corp['corp_name']} 재무데이터 수집 중 (최대 20년)..."):
            data = fetch_all_years(corp["corp_code"], "CFS")
            if not data:
                data = fetch_all_years(corp["corp_code"], "OFS")
                fs_div = "OFS"
            else:
                fs_div = "CFS"
        st.session_state[cache_key] = data
        st.session_state[cache_key + "_fs"]   = fs_div
        st.session_state[cache_key + "_corp"] = corp["corp_code"]
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
        for y in years:
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
            fig = make_mixed(years,
                             {"매출액": [data[y]["is"].get("revenue")   for y in years]},
                             {"영업이익": [data[y]["is"].get("opIncome")  for y in years],
                              "순이익":   [data[y]["is"].get("netIncome") for y in years]},
                             "매출 · 영업이익 · 순이익 (억원)")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = make_line(years,
                            {"영업이익률(%)": [pct(data[y]["is"].get("opIncome"),  data[y]["is"].get("revenue")) for y in years],
                             "순이익률(%)":   [pct(data[y]["is"].get("netIncome"), data[y]["is"].get("revenue")) for y in years]},
                            "수익성 비율", is_pct=True)
            st.plotly_chart(fig, use_container_width=True)

        rows = []
        for y in years:
            i = data[y]["is"]
            om = pct(i.get("opIncome"),  i.get("revenue"))
            nm = pct(i.get("netIncome"), i.get("revenue"))
            rows.append({"연도": y, "매출액": fmt(i.get("revenue")),
                         "영업이익": fmt(i.get("opIncome")), "순이익": fmt(i.get("netIncome")),
                         "영업이익률": f"{om:.1f}%" if om else "-",
                         "순이익률": f"{nm:.1f}%" if nm else "-"})
        st.dataframe(rows, hide_index=True, use_container_width=True)

    # 현금흐름표
    with tab_cf:
        cf1, cf2 = st.columns(2)
        with cf1:
            fig = make_bar(years,
                           {"영업활동": [data[y]["cf"].get("opCF")  for y in years],
                            "투자활동": [data[y]["cf"].get("invCF") for y in years],
                            "재무활동": [data[y]["cf"].get("finCF") for y in years]},
                           "현금흐름 추이 (억원)")
            st.plotly_chart(fig, use_container_width=True)
        with cf2:
            ec_data = {"기말현금및현금성자산": [data[y]["cf"].get("endCash") for y in years]}
            fig_ec = make_line(years, ec_data, "기말현금및현금성자산 추이 (억원)")
            st.plotly_chart(fig_ec, use_container_width=True)

        rows = []
        for y in years:
            c = data[y]["cf"]
            rows.append({"연도": y, "영업활동": fmt(c.get("opCF")),
                         "투자활동": fmt(c.get("invCF")), "재무활동": fmt(c.get("finCF")),
                         "기말현금": fmt(c.get("endCash"))})
        st.dataframe(rows, hide_index=True, use_container_width=True)

    # ── 최신 공시 ──
    st.divider()
    with st.spinner("공시 목록 조회 중..."):
        disc_list, disc_label = fetch_disclosures(corp["corp_code"])

    st.markdown(f"#### 📋 최근 공시 · <span style='font-size:.8rem;color:#64748b;font-weight:400;'>{disc_label}</span>",
                unsafe_allow_html=True)

    if not disc_list:
        st.info(f"공시 정보를 불러올 수 없습니다. ({disc_label})")
    else:
        for item in disc_list:
            link_attr = f'href="{item["link"]}" target="_blank"' if item["link"] else ""
            cls_badge = (f'<span style="font-size:.68rem;background:#eff6ff;color:#2563eb;'
                         f'border-radius:4px;padding:1px 6px;margin-right:6px;">'
                         f'{item["corp_cls"]}</span>') if item["corp_cls"] else ""
            st.markdown(f"""
            <a {link_attr} style="text-decoration:none;">
              <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;
                          padding:11px 16px;margin-bottom:7px;
                          box-shadow:0 1px 3px rgba(0,0,0,.05);
                          display:flex;align-items:center;gap:12px;">
                <div style="width:6px;height:6px;border-radius:50%;background:#2563eb;flex-shrink:0;margin-top:2px;"></div>
                <div style="flex:1;">
                  <div style="font-size:.88rem;font-weight:600;color:#1e293b;line-height:1.4;">{item['report_nm']}</div>
                  <div style="display:flex;gap:6px;align-items:center;margin-top:4px;flex-wrap:wrap;">
                    {cls_badge}
                    <span style="font-size:.72rem;color:#64748b;">{item['flr_nm']}</span>
                    <span style="font-size:.72rem;color:#94a3b8;">{item['rcept_dt']}</span>
                  </div>
                </div>
                <div style="font-size:.75rem;color:#2563eb;flex-shrink:0;">→</div>
              </div>
            </a>
            """, unsafe_allow_html=True)

    # ── 최신 뉴스 ──
    st.divider()
    st.markdown("#### 📰 최신 뉴스")
    with st.spinner("뉴스 검색 중..."):
        news_list = fetch_news(corp["corp_name"])

    if not news_list:
        st.info("뉴스를 불러올 수 없습니다.")
    else:
        for n in news_list:
            st.markdown(f"""
            <a href="{n['link']}" target="_blank" style="text-decoration:none;">
              <div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;
                          padding:12px 16px;margin-bottom:8px;
                          box-shadow:0 1px 3px rgba(0,0,0,.05);">
                <div style="font-size:.88rem;font-weight:600;color:#1e293b;
                            line-height:1.4;margin-bottom:5px;">{n['title']}</div>
                               <div style="display:flex;gap:10px;align-items:center;">
                  <span style="font-size:.72rem;color:#2563eb;font-weight:500;">{n['source']}</span>
                  <span style="font-size:.7rem;color:#94a3b8;">{n['date']}</span>
                </div>
              </div>
            </a>
            """, unsafe_allow_html=True)

    st.caption(f"데이터: 금융감독원 전자공시(DART) · 뉴스: Google News · 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')}")


if __name__ == "__main__":
    main()
