"""
공통 유틸리티 — 포매팅, HTML 빌더, 섹션 헤더
"""
import streamlit as st


def fmt(n: int | float | None) -> str:
    return f"{int(n):,}" if n is not None else "-"


def pct(a: int | None, b: int | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(a / b * 100, 1)


def _html_table(headers: list[str], rows_html: str,
                align: list[str] | None = None) -> str:
    if align is None:
        align = ["left"] * len(headers)
    th_cells = "".join(
        f'<th style="padding:6px 8px;font-size:.72rem;color:#64748b;'
        f'text-align:{a};font-weight:600;">{h}</th>'
        for h, a in zip(headers, align)
    )
    return (
        f'<div style="overflow-x:auto;border:1px solid #e2e8f0;'
        f'border-radius:10px;margin-bottom:8px;">'
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


def _is_year_key(k: str) -> bool:
    return len(k) == 4 and k.isdigit()


def _sal_fmt(v: int | None) -> str:
    return f'{round((v or 0) / 10_000):,}만원' if v else "-"


def _to_man(v: int | None) -> int:
    return round((v or 0) / 10_000)


def _stock_info_cell(lbl: str, val: str, color: str = "#475569") -> str:
    return (
        f'<span style="margin-right:12px;white-space:nowrap;">'
        f'<span style="font-size:.65rem;color:#94a3b8;">{lbl} </span>'
        f'<span style="font-size:.82rem;font-weight:600;color:{color};">{val}</span>'
        f'</span>'
    )


def _fx_card_html(label: str, value: float | None,
                  chg: float | None, unit: str = "", num_fmt: str = ".1f") -> str:
    """환율·금리 카드 셀 HTML."""
    if value is None:
        return ""
    if chg is not None and chg != 0:
        sym   = "▲" if chg > 0 else "▼"
        color = "#dc2626" if chg > 0 else "#2563eb"
        chg_html = (f'<span style="font-size:.62rem;color:{color};margin-left:3px;">'
                    f'{sym}{abs(chg):{num_fmt}}</span>')
    else:
        chg_html = ""
    val_str = (f"{value:,.3f}" if num_fmt == ".3f" else
               f"{value:,.2f}" if num_fmt == ".2f" else f"{value:,.1f}")
    unit_html = (f'<span style="font-size:.65rem;font-weight:400;'
                 f'color:#94a3b8;margin-left:2px;">{unit}</span>' if unit else "")
    return (
        f'<div style="flex:1;min-width:45%;text-align:center;padding:8px 6px;">'
        f'<div style="font-size:.65rem;color:#64748b;margin-bottom:2px;white-space:nowrap;">{label}</div>'
        f'<div style="font-size:.95rem;font-weight:700;color:#1e293b;white-space:nowrap;">'
        f'{val_str}{chg_html}{unit_html}</div>'
        f'</div>'
    )
