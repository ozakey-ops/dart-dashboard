"""
주식 탭 렌더러 — 캔들차트, 시가총액, PER/PBR, EV/EBITDA, DCF, 적정가 카드
"""
from __future__ import annotations

from datetime import datetime, timedelta

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from modules.api import (
    fetch_all_years,
    fetch_stock_chart,
    fetch_year,
    fetch_yf_annual_data,
    _resolve_ticker,
)
from modules.constants import _CACHE_VER, COLORS, PLOTLY_LAYOUT
from modules.utils import _is_year_key, _section_header, _stock_info_cell

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False


# ══════════════════════════════════════════
#  내부 헬퍼
# ══════════════════════════════════════════

def _load_fs_data(corp_code: str) -> dict:
    """재무 데이터 로드 (session_state 캐시 우선)."""
    cached = st.session_state.get(f"{corp_code}_data")
    if cached:
        return cached
    cfs = fetch_all_years(corp_code, "CFS")
    ofs = fetch_all_years(corp_code, "OFS")
    return {**ofs, **cfs} if (cfs and ofs) else (cfs or ofs or {})


# ══════════════════════════════════════════
#  서브 렌더러
# ══════════════════════════════════════════

def _render_mktcap_chart(stock_code: str, corp_cls: str, corp_code: str) -> dict | None:
    _section_header("연도별 시가총액", "과거: 연말 종가 기준 · 현재 연도: 당일 현재가 기준 (억 원)")
    yf_data = fetch_yf_annual_data(stock_code, corp_cls, corp_code, _ver=_CACHE_VER)
    if "__error__" in yf_data:
        st.caption(f"시가총액 데이터를 가져올 수 없습니다: {yf_data['__error__']}")
        return None
    mktcap = yf_data.get("mktcap", {})
    if not mktcap:
        st.caption("시가총액을 계산하기 위한 데이터가 부족합니다 (발행주식수 미확인).")
        return None
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
    return yf_data


def _render_per_pbr_chart(yf_data: dict) -> None:
    _section_header("PER / PBR 밸류에이션 추이", "연말 종가 기준 · 오늘: trailing 기준")
    per_pbr = yf_data.get("per_pbr", {})
    if not per_pbr:
        st.caption("PER/PBR 계산에 필요한 재무데이터(순이익, 자본총계)를 가져올 수 없습니다.")
        return

    today_key = datetime.now().strftime("%Y-%m-%d")
    for stale in [k for k in list(per_pbr.keys()) if not _is_year_key(k) and k != today_key]:
        per_pbr[today_key] = per_pbr.pop(stale)

    hist_keys = sorted([k for k in per_pbr if _is_year_key(k)], key=int)
    date_keys = sorted([k for k in per_pbr if not _is_year_key(k)])
    years_pp  = hist_keys + date_keys
    per_vals  = [per_pbr[y].get("PER") for y in years_pp]
    pbr_vals  = [per_pbr[y].get("PBR") for y in years_pp]

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


def _render_ev_ebitda_chart(corp_code: str, yf_data: dict) -> None:
    _section_header(
        "EV/EBITDA 추이",
        "EV = 시가총액 + 부채총계 − 기말현금 · EBITDA = 영업이익 + 감가상각비(D) + 상각비(A)",
    )
    mktcap = yf_data.get("mktcap", {})
    if not mktcap:
        st.caption("시가총액 데이터가 없어 EV/EBITDA를 계산할 수 없습니다.")
        return

    with st.spinner("재무 데이터 조회 중..."):
        fs_data = _load_fs_data(corp_code)
    if not fs_data:
        st.caption("재무 데이터를 불러올 수 없어 EV/EBITDA를 계산할 수 없습니다.")
        return

    ev_ebitda_map: dict[str, float] = {}
    da_missing_years: list[str] = []

    for yr_str, mc in mktcap.items():
        if not _is_year_key(yr_str):
            continue
        fd = fs_data.get(yr_str)
        if not fd:
            continue
        liabilities = fd["bs"].get("liabilities") or 0
        cash        = fd["cf"].get("endCash")     or 0
        op_income   = fd["is"].get("opIncome")
        if not op_income or op_income <= 0:
            continue
        dep    = abs(fd["cf"].get("depreciationDA") or 0)
        amt    = abs(fd["cf"].get("amortizationIA") or 0)
        ebitda = op_income + dep + amt
        if dep == 0 and amt == 0:
            da_missing_years.append(yr_str)
        ev = mc + liabilities - cash
        ev_ebitda_map[yr_str] = round(ev / ebitda, 1)

    if not ev_ebitda_map:
        st.caption("EV/EBITDA를 계산하기 위한 데이터가 충분하지 않습니다.")
        return

    if da_missing_years:
        st.caption(
            f"⚠️ {', '.join(sorted(da_missing_years))}년 감가상각비를 찾지 못해 "
            "영업이익만으로 EBITDA를 근사했습니다."
        )

    years_ev = sorted(ev_ebitda_map.keys(), key=int)
    vals_ev  = [ev_ebitda_map[y] for y in years_ev]
    avg_ev   = round(sum(vals_ev) / len(vals_ev), 1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=years_ev, y=vals_ev, name="EV/EBITDA",
        mode="lines+markers+text",
        line=dict(color=COLORS["purple"], width=2),
        marker=dict(size=6),
        text=[str(v) for v in vals_ev],
        textposition="top center", textfont=dict(size=9, color=COLORS["purple"]),
    ))
    fig.add_hline(y=avg_ev, line_dash="dot", line_color="#94a3b8",
                  annotation_text=f"평균 {avg_ev}x",
                  annotation_position="bottom right",
                  annotation_font=dict(size=10, color="#94a3b8"))
    fig.update_layout(
        title_text="EV/EBITDA 추이 (배)", title_font_color="#1e293b", title_font_size=12,
        yaxis=dict(ticksuffix="x", gridcolor="#e2e8f0", tickfont=dict(color="#64748b")),
        xaxis=dict(type="category", gridcolor="#e2e8f0",
                   tickfont=dict(color="#64748b"), linecolor="#e2e8f0"),
        **{k: v for k, v in PLOTLY_LAYOUT.items() if k not in ("yaxis", "xaxis")},
    )
    st.plotly_chart(fig, use_container_width=True)

    da_years = [y for y in years_ev
                if (fs_data.get(y, {}).get("cf", {}).get("depreciationDA") or
                    fs_data.get(y, {}).get("cf", {}).get("amortizationIA"))]
    if da_years:
        da_rows = []
        for y in da_years:
            fd     = fs_data[y]
            oi     = fd["is"].get("opIncome") or 0
            dep    = abs(fd["cf"].get("depreciationDA") or 0)
            amt    = abs(fd["cf"].get("amortizationIA") or 0)
            ebitda = oi + dep + amt
            da_rows.append({
                "연도": y,
                "영업이익(억)":     f"{oi:,}",
                "감가상각비 D(억)": f"{dep:,}" if dep else "-",
                "무형상각비 A(억)": f"{amt:,}" if amt else "-",
                "EBITDA(억)":      f"{ebitda:,}",
            })
        st.dataframe(da_rows, hide_index=True, use_container_width=True)


def _render_dcf_calculator(corp_code: str) -> None:
    _section_header("간이 DCF 내재가치 계산기",
                    "FCF = 영업현금흐름(OCF) 근사 · 결과는 참고용이며 투자 조언이 아닙니다")

    with st.spinner("재무 데이터 조회 중..."):
        fs_data = _load_fs_data(corp_code)
    if not fs_data:
        st.caption("재무 데이터를 불러올 수 없습니다.")
        return

    years   = sorted(fs_data.keys())
    recent  = years[-3:] if len(years) >= 3 else years
    ocf_vals = [fs_data[y]["cf"].get("opCF")
                for y in recent if fs_data[y]["cf"].get("opCF")]
    if not ocf_vals:
        st.caption("현금흐름 데이터가 없어 DCF를 계산할 수 없습니다.")
        return

    base_fcf = round(sum(ocf_vals) / len(ocf_vals))
    st.caption(
        f"기준 FCF: 최근 **{len(ocf_vals)}년** 평균 영업CF "
        f"= **{base_fcf:,}억원** "
        f"({', '.join(str(v)+' 억' for v in ocf_vals)})"
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        g1 = st.number_input("성장률 — 향후 5년 (%)", min_value=-20.0, max_value=50.0,
                             value=8.0, step=0.5, key=f"dcf_g1_{corp_code}") / 100
    with c2:
        gt = st.number_input("영구 성장률 (%)", min_value=0.0, max_value=8.0,
                             value=2.0, step=0.5, key=f"dcf_gt_{corp_code}") / 100
    with c3:
        wacc = st.number_input("할인율 — WACC (%)", min_value=1.0, max_value=30.0,
                               value=10.0, step=0.5, key=f"dcf_wacc_{corp_code}") / 100

    if wacc <= gt:
        st.warning("할인율(WACC)이 영구 성장률보다 커야 합니다.")
        return

    fcf    = float(base_fcf)
    pv_sum = 0.0
    rows: list[dict] = []
    for n in range(1, 6):
        fcf  *= (1 + g1)
        pv    = fcf / (1 + wacc) ** n
        pv_sum += pv
        rows.append({"연도": f"Y+{n}", "예상 FCF": round(fcf), "현재가치 PV": round(pv)})

    terminal_val = rows[-1]["예상 FCF"] * (1 + gt) / (wacc - gt)
    pv_terminal  = terminal_val / (1 + wacc) ** 5
    intrinsic    = round(pv_sum + pv_terminal)

    g1_pct   = round(g1   * 100, 1)
    gt_pct   = round(gt   * 100, 1)
    wacc_pct = round(wacc * 100, 1)
    fcf5     = rows[-1]["예상 FCF"]

    kpi_html = (
        '<div style="display:flex;gap:12px;margin:12px 0;">'
        '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;">'
        '<div style="font-size:.68rem;color:#64748b;margin-bottom:4px;">DCF 내재가치</div>'
        f'<div style="font-size:1.1rem;font-weight:700;color:#1e293b;">{intrinsic:,}억원</div>'
        '<div style="font-size:.62rem;color:#94a3b8;margin-top:6px;line-height:1.6;">'
        '= 현금흐름 PV 합계 + 잔존가치 PV'
        '</div>'
        '</div>'
        '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;">'
        '<div style="font-size:.68rem;color:#64748b;margin-bottom:4px;">현금흐름 PV 합계</div>'
        f'<div style="font-size:1.1rem;font-weight:700;color:#1e293b;">{round(pv_sum):,}억원</div>'
        '<div style="font-size:.62rem;color:#94a3b8;margin-top:6px;line-height:1.6;">'
        f'= Σ FCFₙ × (1+{g1_pct}%)ⁿ ÷ (1+{wacc_pct}%)ⁿ &nbsp;[n=1~5]'
        '</div>'
        '</div>'
        '<div style="flex:1;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;">'
        '<div style="font-size:.68rem;color:#64748b;margin-bottom:4px;">잔존가치(Terminal) PV</div>'
        f'<div style="font-size:1.1rem;font-weight:700;color:#1e293b;">{round(pv_terminal):,}억원</div>'
        '<div style="font-size:.62rem;color:#94a3b8;margin-top:6px;line-height:1.6;">'
        f'= FCF₅({fcf5:,}억) × (1+{gt_pct}%) ÷ ({wacc_pct}%−{gt_pct}%) ÷ (1+{wacc_pct}%)⁵'
        '</div>'
        '</div>'
        '</div>'
    )
    st.markdown(kpi_html, unsafe_allow_html=True)

    yrs  = [r["연도"]        for r in rows]
    fcfs = [r["예상 FCF"]    for r in rows]
    pvs  = [r["현재가치 PV"] for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(name="예상 FCF (억원)", x=yrs, y=fcfs,
                         marker_color=COLORS["blue"], marker_line_width=0,
                         text=[f"{v:,}" for v in fcfs],
                         textposition="outside", textfont=dict(size=9)))
    fig.add_trace(go.Bar(name="현재가치 PV (억원)", x=yrs, y=pvs,
                         marker_color=COLORS["orange"], marker_line_width=0,
                         text=[f"{v:,}" for v in pvs],
                         textposition="outside", textfont=dict(size=9)))
    fig.update_layout(
        title_text="연도별 FCF / 현재가치 (억원)",
        title_font_color="#1e293b", title_font_size=12,
        barmode="group", **PLOTLY_LAYOUT,
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _render_fair_value_card(corp_code: str, yf_data: dict,
                             stock_code: str, corp_cls: str) -> None:
    _section_header("적정 주가 종합 분석",
                    "PER · PBR · DCF 세 가지 방식의 평균을 종합 적정가로 사용 — 투자 조언 아님")

    if not _YF_AVAILABLE or not stock_code:
        st.caption("주가 데이터(yfinance)가 필요합니다.")
        return

    try:
        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            st.caption("티커를 확인할 수 없습니다.")
            return
        ticker_str, _ = resolved
        t = yf.Ticker(ticker_str)
        cur_price: float = float(t.fast_info.last_price)
        shares: int | None = t.fast_info.shares or (t.info or {}).get("sharesOutstanding")
    except Exception as e:
        st.caption(f"현재가 조회 실패: {e}")
        return

    if not shares or shares <= 0:
        st.caption("발행주식수를 확인할 수 없습니다.")
        return

    with st.spinner("재무 데이터 조회 중..."):
        fs_data = _load_fs_data(corp_code)
    if not fs_data:
        st.caption("재무 데이터를 불러올 수 없습니다.")
        return

    years  = sorted(fs_data.keys())
    latest = years[-1]
    ld     = fs_data[latest]

    per_pbr = yf_data.get("per_pbr", {})
    hist_pers = [v["PER"] for v in per_pbr.values()
                 if isinstance(v, dict) and v.get("PER") and v["PER"] > 0]
    avg_per   = round(sum(hist_pers) / len(hist_pers), 1) if hist_pers else None
    net_income = ld["is"].get("netIncome")
    eps = (net_income * 1e8 / shares) if (net_income and net_income > 0) else None
    per_fair = round(eps * avg_per) if (eps and avg_per) else None

    hist_pbrs = [v["PBR"] for v in per_pbr.values()
                 if isinstance(v, dict) and v.get("PBR") and v["PBR"] > 0]
    avg_pbr   = round(sum(hist_pbrs) / len(hist_pbrs), 2) if hist_pbrs else None
    equity = ld["bs"].get("equity")
    bps    = (equity * 1e8 / shares) if (equity and equity > 0) else None
    pbr_fair = round(bps * avg_pbr) if (bps and avg_pbr) else None

    recent   = years[-3:] if len(years) >= 3 else years
    ocf_vals = [fs_data[y]["cf"].get("opCF") for y in recent if fs_data[y]["cf"].get("opCF")]
    dcf_fair = None
    if ocf_vals:
        base_fcf = sum(ocf_vals) / len(ocf_vals)
        g1, gt, wacc = 0.08, 0.02, 0.10
        fcf, pv_sum = base_fcf, 0.0
        for n in range(1, 6):
            fcf *= (1 + g1)
            pv_sum += fcf / (1 + wacc) ** n
        tv     = fcf * (1 + gt) / (wacc - gt)
        pv_tv  = tv / (1 + wacc) ** 5
        dcf_fair = round((pv_sum + pv_tv) * 1e8 / shares)

    valids    = [v for v in [per_fair, pbr_fair, dcf_fair] if v]
    consensus = round(sum(valids) / len(valids)) if valids else None

    def gap(fair: int | None) -> tuple[float | None, str, str]:
        if fair is None:
            return None, "-", "#94a3b8"
        g = (fair - cur_price) / cur_price * 100
        color = "#16a34a" if g > 0 else "#dc2626"
        sym   = "▲" if g > 0 else "▼"
        return g, f"{sym}{abs(g):.1f}%", color

    _, per_gap_str,  per_gap_clr  = gap(per_fair)
    _, pbr_gap_str,  pbr_gap_clr  = gap(pbr_fair)
    _, dcf_gap_str,  dcf_gap_clr  = gap(dcf_fair)
    _, cons_gap_str, cons_gap_clr = gap(consensus)

    def _card(title: str, fair: int | None, gap_str: str, gap_clr: str, sub: str = "") -> str:
        val     = f"{fair:,}원" if fair else "-"
        sub_div = (f'<div style="font-size:.62rem;color:#94a3b8;margin-top:2px;">{sub}</div>'
                   if sub else "")
        return (
            f'<div style="flex:1;min-width:140px;background:#f8fafc;border:1px solid #e2e8f0;'
            f'border-radius:10px;padding:14px 12px;text-align:center;margin:4px;">'
            f'<div style="font-size:.68rem;color:#64748b;margin-bottom:4px;">{title}</div>'
            f'<div style="font-size:1.05rem;font-weight:700;color:#1e293b;">{val}</div>'
            f'<div style="font-size:.75rem;font-weight:600;color:{gap_clr};margin-top:2px;">{gap_str}</div>'
            f'{sub_div}'
            f'</div>'
        )

    cur_str = f"{int(cur_price):,}원"
    cards_html = (
        _card("PER 적정가",  per_fair,  per_gap_str,  per_gap_clr,
              f"평균 PER {avg_per}x" if avg_per else "")
        + _card("PBR 적정가",  pbr_fair,  pbr_gap_str,  pbr_gap_clr,
                f"평균 PBR {avg_pbr}x" if avg_pbr else "")
        + _card("DCF 적정가",  dcf_fair,  dcf_gap_str,  dcf_gap_clr,
                "g=8% / TV=2% / r=10%")
        + _card("종합 적정가", consensus, cons_gap_str, cons_gap_clr, "3방식 평균")
    )
    st.markdown(
        f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;'
        f'box-shadow:0 1px 3px rgba(0,0,0,.06);padding:14px 12px 10px;margin:8px 0;">'
        f'<div style="font-size:.72rem;color:#64748b;margin-bottom:8px;">'
        f'현재가 <b style="color:#1e293b;font-size:.9rem;">{cur_str}</b> 기준 괴리율</div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{cards_html}</div>'
        f'<div style="font-size:.62rem;color:#94a3b8;margin-top:8px;text-align:right;">'
        f'DCF 기본 가정: 성장률 8% / 영구성장률 2% / WACC 10% — DCF 탭에서 가정 변경 가능</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════
#  주식 탭 진입점
# ══════════════════════════════════════════

def render_stock_tab(stock_code: str, corp_name: str,
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

    if corp_code:
        yf_data = _render_mktcap_chart(stock_code, corp_cls, corp_code)
        if yf_data and "__error__" not in yf_data:
            _render_per_pbr_chart(yf_data)
            _render_ev_ebitda_chart(corp_code, yf_data)
            _render_dcf_calculator(corp_code)
            _render_fair_value_card(corp_code, yf_data, stock_code, corp_cls)
