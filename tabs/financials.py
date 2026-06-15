"""
재무제표 탭 렌더러
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from modules.api import fetch_all_years
from modules.constants import _CACHE_VER, COLORS, PLOTLY_LAYOUT, YEARS
from modules.utils import fmt, pct, _section_header


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
#  재무제표 탭
# ══════════════════════════════════════════

def render_fs_tab(corp: dict) -> None:
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
