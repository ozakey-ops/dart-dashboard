"""
주주 현황 탭 렌더러
"""
from __future__ import annotations

import streamlit as st

from modules.api import (
    fetch_major_shareholders,
    fetch_major_shareholder_history,
    fetch_large_holding_reports,
    fetch_executive_stock_reports,
)
from modules.constants import _CACHE_VER
from modules.utils import _html_table, _section_header


def _render_major_shareholders(corp_code: str) -> None:
    """최대주주·임원 소유현황 테이블."""
    rcode_label = {"11011": "사업보고서", "11012": "반기보고서",
                   "11013": "1분기보고서", "11014": "3분기보고서"}
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


def _render_shareholder_history(corp_code: str) -> None:
    """최대주주 변동현황 테이블."""
    rcode_label = {"11011": "사업보고서", "11012": "반기보고서",
                   "11013": "1분기보고서", "11014": "3분기보고서"}
    with st.spinner("최대주주 변동현황 조회 중..."):
        sh_history = fetch_major_shareholder_history(corp_code)

    if sh_history:
        ref_h   = sh_history[0]
        h_label = f"{ref_h['year']}년 {rcode_label.get(ref_h['rcode'], ref_h['rcode'])}"
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
    """대량보유상황보고 테이블."""
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
    """임원·주요주주 소유보고 테이블."""
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


def render_shareholders_tab(corp_code: str) -> None:
    """주주 현황 탭 진입점."""
    if not corp_code:
        st.caption("corp_code를 확인할 수 없습니다.")
        return
    _render_major_shareholders(corp_code)
    st.divider()
    _render_shareholder_history(corp_code)
    st.divider()
    _render_large_holdings(corp_code)
    st.divider()
    _render_executive_reports(corp_code)
