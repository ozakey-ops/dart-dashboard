"""
기업 주식 시황 및 재무 대시보드 — 엔트리포인트
설치:  pip install streamlit plotly requests yfinance pandas
실행:  streamlit run streamlit_app.py
"""
import streamlit as st

from modules.api import (
    fetch_company_overview,
    fetch_market_data,
    load_corp_list,
    search_corps,
)
from modules.constants import DART_KEY, _CACHE_VER
from modules.utils import _fx_card_html
from tabs.employees import render_employee_tab
from tabs.financials import render_fs_tab
from tabs.news import render_news_tab
from tabs.shareholders import render_shareholders_tab
from tabs.stock import render_stock_tab

# ── 페이지 설정 ──
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
#  검색 헬퍼
# ══════════════════════════════════════════

def _on_search_enter() -> None:
    _run_search(st.session_state.get("_search_input", ""))


def _run_search(q: str) -> None:
    q = (q or "").strip()
    if not q:
        return
    try:
        corps   = load_corp_list()
        results = search_corps(q, corps)
    except Exception:
        results = []
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

    # 검색창
    col_inp, col_btn = st.columns([5, 1])
    with col_inp:
        st.text_input(
            "",
            placeholder="회사명 또는 종목코드 입력 (예: 삼성전자, 005930)",
            key="_search_input",
            label_visibility="collapsed",
            on_change=_on_search_enter,
        )
    with col_btn:
        if st.button("🔍 검색", use_container_width=True, key="search_btn"):
            _run_search(st.session_state.get("_search_input", ""))

    no_result_q = st.session_state.get("_search_no_result", "")
    if no_result_q:
        st.warning(f"'{no_result_q}' 검색 결과가 없습니다.")

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
    sep       = '<span style="color:#94a3b8;margin:0 6px;">|</span>'
    meta_html = sep.join(meta_parts)
    addr_html = (f'<div style="font-size:.72rem;color:#64748b;margin-top:4px;">📍 {ov["adres"]}</div>'
                 if ov.get("adres") else "")
    url_html  = (f'<div style="font-size:.72rem;margin-top:2px;">🌐 '
                 f'<a href="{ov["hm_url"]}" target="_blank" style="color:#2563eb;">{ov["hm_url"]}</a></div>'
                 if ov.get("hm_url") else "")

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
        st.markdown(
            f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
            f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:4px 4px 2px;margin:0 0 12px 0;">'
            f'<div style="display:flex;flex-wrap:wrap;align-items:center;">'
            + _fx_card_html("원 / 달러",       md["usd_krw"],    md.get("usd_krw_chg"),    "원", ".1f")
            + _fx_card_html("원 / 100엔",      md["jpy100_krw"], md.get("jpy100_krw_chg"), "원", ".1f")
            + _fx_card_html("엔 / 달러",       md["usd_jpy"],    md.get("usd_jpy_chg"),    "엔", ".2f")
            + _fx_card_html("10년 채권 이자율", md["bond10y"],    md.get("bond10y_chg"),    "%",  ".3f")
            + f'</div>'
            f'<div style="text-align:right;font-size:.62rem;color:#94a3b8;padding:0 8px 4px;">'
            f'기준일 {md["date"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # 메인 탭
    corp_code = corp.get("corp_code", "")
    tab_stock, tab_sh, tab_fs, tab_news, tab_emp = st.tabs([
        "📈 주식", "🏦 주주 현황", "📊 재무제표", "📢 공시 · 뉴스", "👥 직원 현황",
    ])

    with tab_stock:
        try:
            render_stock_tab(
                corp.get("stock_code", ""), corp["corp_name"],
                ov.get("corp_cls_raw", "Y"), corp_code=corp_code,
            )
        except Exception as e:
            st.error(f"주식 차트 로딩 오류: {e}")

    with tab_sh:
        render_shareholders_tab(corp_code)

    with tab_fs:
        render_fs_tab(corp)

    with tab_news:
        render_news_tab(corp)

    with tab_emp:
        render_employee_tab(corp)


if __name__ == "__main__":
    main()
