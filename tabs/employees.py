"""
직원 현황 탭 렌더러
"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from modules.api import fetch_employee_status
from modules.constants import _CACHE_VER, COLORS, PLOTLY_LAYOUT
from modules.utils import _sal_fmt, _to_man


def render_employee_tab(corp: dict) -> None:
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
    for sex, color in [("m", COLORS["blue"]), ("f", "#ec4899")]:
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
        for sex, color, label in [("m", COLORS["blue"], "남"), ("f", "#ec4899", "여")]:
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
