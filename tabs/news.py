"""
공시·뉴스 탭 렌더러
"""
from __future__ import annotations

import streamlit as st

from modules.api import fetch_disclosures, fetch_news


def render_news_tab(corp: dict) -> None:
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
