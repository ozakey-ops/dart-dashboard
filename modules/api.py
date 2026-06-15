"""
DART API + yfinance 데이터 패치 함수 모음
"""
from __future__ import annotations

import io
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import requests
import streamlit as st

try:
    import yfinance as yf
    import pandas as pd
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

from .constants import (
    ACC, BASE, DART_KEY, YEARS, _CACHE_VER, _REPRT_CANDIDATES,
    TTL_REALTIME, TTL_SHORT, TTL_MEDIUM, TTL_LONG, TTL_WEEKLY,
)


# ══════════════════════════════════════════
#  파싱 유틸리티
# ══════════════════════════════════════════

def clean(s: str) -> str:
    return (s or "").replace(" ", "")


def parse_amt(item: dict) -> int | None:
    try:
        return round(int(item.get("thstrm_amount", "").replace(",", "")) / 1e8)
    except Exception:
        return None


def find_amount(items: list[dict], keys: list[str]) -> int | None:
    """계정과목 검색: 완전일치 → 양방향 포함 검색"""
    for key in keys:
        kc = clean(key)
        for item in items:
            if clean(item.get("account_nm", "")) == kc:
                v = parse_amt(item)
                if v is not None:
                    return v
    for key in keys:
        kc = clean(key)
        for item in items:
            nm = clean(item.get("account_nm", ""))
            if kc in nm or nm in kc:
                v = parse_amt(item)
                if v is not None:
                    return v
    return None


def find_retained_earnings(bs_items: list[dict]) -> int | None:
    r = find_amount(bs_items, ACC["retainedEarnings"])
    if r is not None:
        return r
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "이익잉여금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    for item in bs_items:
        nm = clean(item.get("account_nm", ""))
        if "결손금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    return None


def find_end_cash(cf_items: list[dict]) -> int | None:
    r = find_amount(cf_items, ACC["endCash"])
    if r is not None:
        return r
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "기말" in nm and "현금" in nm:
            v = parse_amt(item)
            if v is not None:
                return v
    candidates = []
    for item in cf_items:
        nm = clean(item.get("account_nm", ""))
        if "현금및현금성자산" in nm:
            v = parse_amt(item)
            if v is not None:
                candidates.append(v)
    return candidates[-1] if candidates else None


def _get_yf_val(df_T: Any, idx: Any, keys: list[str]) -> float | None:
    for k in keys:
        if k in df_T.columns:
            v = df_T.loc[idx, k]
            if pd.notna(v):
                return float(v)
    return None


def _safe_int(v: str) -> int | None:
    s = (v or "").replace(",", "").strip()
    try:
        return int(s) if s else None
    except ValueError:
        return None


def _safe_float(v: str) -> float | None:
    try:
        return float(v or 0) or None
    except (ValueError, TypeError):
        return None


# ══════════════════════════════════════════
#  DART — 기업 목록
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_WEEKLY, show_spinner=False)
def load_corp_list() -> list[dict]:
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


def search_corps(query: str, all_corps: list[dict]) -> list[dict]:
    q  = query.strip()
    ql = q.lower()
    if q.isdigit() or (len(q) >= 2 and q[0].upper() == "A" and q[1:].isdigit()):
        stock_q = q.lstrip("Aa")
        matches = [c for c in all_corps if c["stock_code"] in (stock_q, q)]
    else:
        exact   = [c for c in all_corps if c["corp_name"].lower() == ql]
        partial = [c for c in all_corps if ql in c["corp_name"].lower()]
        matches = exact if exact else partial
    if not matches:
        return []
    matches.sort(key=lambda c: (
        c["corp_name"].lower() != ql,
        not bool(c["stock_code"]),
        -(int(c["corp_code"]) if c["corp_code"].isdigit() else 0),
        c["corp_name"],
    ))
    return matches[:20]


# ══════════════════════════════════════════
#  DART — 재무 데이터
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_year(corp_code: str, year: int, fs_div: str) -> dict | None:
    try:
        r = requests.get(
            f"{BASE}/fnlttSinglAcntAll.json",
            params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                    "bsns_year": year, "reprt_code": "11011", "fs_div": fs_div},
            timeout=15,
        )
        d = r.json()
        if d.get("status") != "000" or not d.get("list"):
            return None
        lst = d["list"]
        bs  = [x for x in lst if x.get("sj_div") == "BS"]
        isl = [x for x in lst if x.get("sj_div") == "IS"] or \
              [x for x in lst if x.get("sj_div") == "CIS"]
        cf  = [x for x in lst if x.get("sj_div") == "CF"]
        result = {
            "bs": {
                "assets":           find_amount(bs, ACC["assets"]),
                "liabilities":      find_amount(bs, ACC["liabilities"]),
                "equity":           find_amount(bs, ACC["equity"]),
                "retainedEarnings": find_retained_earnings(bs),
            },
            "is": {
                "revenue":   find_amount(isl, ACC["revenue"]),
                "opIncome":  find_amount(isl, ACC["opIncome"]),
                "netIncome": find_amount(isl, ACC["netIncome"]),
            },
            "cf": {
                "opCF":           find_amount(cf, ACC["opCF"]),
                "invCF":          find_amount(cf, ACC["invCF"]),
                "finCF":          find_amount(cf, ACC["finCF"]),
                "endCash":        find_end_cash(cf),
                "depreciationDA": find_amount(cf, ACC["depreciationDA"]),
                "amortizationIA": find_amount(cf, ACC["amortizationIA"]),
            },
        }
        has_data = any(v is not None for sec in result.values() for v in sec.values())
        return result if has_data else None
    except Exception:
        return None


@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_all_years(corp_code: str, fs_div: str, _ver: int = _CACHE_VER) -> dict:
    all_data: dict[str, dict] = {}

    def _fetch(year: int) -> tuple[int, dict | None]:
        return year, fetch_year(corp_code, year, fs_div)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch, year): year for year in YEARS}
        for future in as_completed(futures):
            year, data = future.result()
            if data:
                all_data[str(year)] = data
    return all_data


# ══════════════════════════════════════════
#  DART — 기업 개요
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def fetch_company_overview(corp_code: str, stock_code: str) -> dict:
    result = {}
    try:
        r = requests.get(f"{BASE}/company.json",
                         params={"crtfc_key": DART_KEY, "corp_code": corp_code},
                         timeout=10)
        d = r.json()
        if d.get("status") == "000":
            cls_map = {"Y": "유가증권(KOSPI)", "K": "코스닥(KOSDAQ)", "N": "코넥스", "E": "기타"}
            est = d.get("est_dt", "")
            raw_url = (d.get("hm_url") or "").strip().rstrip("/")
            result = {
                "ceo_nm":       d.get("ceo_nm", ""),
                "corp_cls":     cls_map.get(d.get("corp_cls", ""), ""),
                "corp_cls_raw": d.get("corp_cls", "Y"),
                "est_dt":       f"{est[:4]}.{est[4:6]}" if len(est) >= 6 else "",
                "acc_mt":       f"{d.get('acc_mt', '')}월" if d.get("acc_mt") else "",
                "phn_no":       d.get("phn_no", ""),
                "adres":        d.get("adres", ""),
                "hm_url":       ("https://" + raw_url)
                                if raw_url and not raw_url.startswith(("http://", "https://"))
                                else raw_url,
            }
    except Exception:
        pass
    return result


# ══════════════════════════════════════════
#  시장 데이터 (환율 + 미국채)
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_REALTIME, show_spinner=False)
def fetch_market_data() -> dict:
    if not _YF_AVAILABLE:
        return {}
    try:
        cfg = {
            "USDKRW=X": (1,   1),
            "JPYKRW=X":  (100, 1),
            "USDJPY=X":  (1,   2),
            "^TNX":      (1,   3),
        }
        raw: dict[str, dict] = {}
        for sym, (mul, nd) in cfg.items():
            hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=True)
            if hist.empty:
                continue
            hist  = hist.dropna(subset=["Close"])
            dates = sorted(hist.index)
            cur   = round(float(hist.loc[dates[-1],  "Close"]) * mul, nd)
            prev  = round(float(hist.loc[dates[-2], "Close"]) * mul, nd) if len(dates) >= 2 else None
            chg   = round(cur - prev, nd) if prev is not None else None
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


# ══════════════════════════════════════════
#  DART — 공시
# ══════════════════════════════════════════

def _parse_disc_list(items: list[dict], count: int) -> list[dict]:
    result = []
    for item in items[:count]:
        rcept_dt = item.get("rcept_dt", "")
        if len(rcept_dt) == 8:
            rcept_dt = f"{rcept_dt[:4]}-{rcept_dt[4:6]}-{rcept_dt[6:]}"
        rcept_no = item.get("rcept_no", "")
        link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
        corp_cls_map = {"Y": "유가증권", "K": "코스닥", "N": "코넥스", "E": "기타"}
        result.append({
            "report_nm": item.get("report_nm", "").strip(),
            "flr_nm":    item.get("flr_nm", "").strip(),
            "rcept_dt":  rcept_dt,
            "corp_cls":  corp_cls_map.get(item.get("corp_cls", ""), ""),
            "link":      link,
        })
    return result


@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_disclosures(corp_code: str, count: int = 15) -> tuple[list[dict], str]:
    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")
    base_params = {
        "crtfc_key":  DART_KEY,
        "corp_code":  corp_code,
        "bgn_de":     bgn_de,
        "end_de":     end_de,
        "page_count": count,
        "page_no":    1,
    }
    attempts = [("I", "거래소공시"), ("B", "주요사항보고"), ("A", "정기공시"), ("", "전체공시")]
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
    return [], last_err or "공시 조회 실패"


# ══════════════════════════════════════════
#  뉴스
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_news(company_name: str, count: int = 15) -> list[dict]:
    try:
        query = urllib.parse.quote(company_name)
        url   = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        r     = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        root  = ET.fromstring(r.content)
        news  = []
        for item in root.findall(".//item")[:count]:
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            pub   = item.findtext("pubDate", "").strip()
            src   = item.findtext("source", "").strip()
            if " - " in title:
                title, src = title.rsplit(" - ", 1)
            try:
                pub_fmt = parsedate_to_datetime(pub).strftime("%m/%d %H:%M")
            except Exception:
                pub_fmt = pub[:16] if pub else ""
            news.append({"title": title.strip(), "link": link,
                         "source": src.strip(), "date": pub_fmt})
        return news
    except Exception:
        return []


# ══════════════════════════════════════════
#  DART — 주주·임원 현황
# ══════════════════════════════════════════

@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_major_shareholders(corp_code: str, _ver: int = _CACHE_VER) -> list[dict]:
    if not corp_code:
        return []
    for bsns_year, reprt_code in _REPRT_CANDIDATES:
        try:
            r = requests.get(
                f"{BASE}/hyslrSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(bsns_year), "reprt_code": reprt_code},
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue
            rows = []
            for item in (data.get("list") or []):
                name = (item.get("nm") or "").strip()
                if name in ("계", "합계", ""):
                    continue
                try:
                    shares = int((item.get("trmend_posesn_stock_co") or "").replace(",", "").strip())
                except ValueError:
                    shares = 0
                try:
                    ratio_pct = float((item.get("trmend_posesn_stock_qota_rt") or "").replace(",", "").strip())
                except ValueError:
                    ratio_pct = None
                rows.append({
                    "name":      name,
                    "relation":  (item.get("relate") or "").strip(),
                    "shares":    shares,
                    "ratio":     ratio_pct,
                    "stock_knd": (item.get("stock_knd") or "").strip(),
                    "rm":        (item.get("rm") or "").strip(),
                    "stlm_dt":   (item.get("stlm_dt") or "").strip(),
                    "year":      bsns_year,
                    "rcode":     reprt_code,
                })
            if rows:
                return rows
        except Exception:
            continue
    return []


@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_major_shareholder_history(corp_code: str, _ver: int = _CACHE_VER) -> list[dict]:
    if not corp_code:
        return []
    for bsns_year, reprt_code in _REPRT_CANDIDATES:
        try:
            r = requests.get(
                f"{BASE}/hyslrChgSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(bsns_year), "reprt_code": reprt_code},
                timeout=10,
            )
            data = r.json()
            if data.get("status") != "000":
                continue
            rows = []
            for item in (data.get("list") or []):
                nm = (item.get("mxmm_shrholdr_nm") or "").strip()
                if nm in ("-", ""):
                    continue
                shares_s = (item.get("posesn_stock_co") or "").replace(",", "").strip()
                ratio_s  = (item.get("qota_rt") or "").strip()
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
                    "chg_on":  (item.get("change_on") or "").strip(),
                    "shares":  shares,
                    "ratio":   ratio,
                    "cause":   (item.get("change_cause") or "").strip(),
                    "rm":      (item.get("rm") or "").strip(),
                    "stlm_dt": (item.get("stlm_dt") or "").strip(),
                    "year":    bsns_year,
                    "rcode":   reprt_code,
                })
            if rows:
                return rows
        except Exception:
            continue
    return []


@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_large_holding_reports(corp_code: str, count: int = 20, _ver: int = _CACHE_VER) -> list[dict]:
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
        rows = []
        for item in sorted(data.get("list") or [], key=lambda x: x.get("rcept_dt", ""), reverse=True)[:count]:
            rows.append({
                "rcept_dt":    item.get("rcept_dt", ""),
                "rcept_no":    item.get("rcept_no", ""),
                "report_tp":   item.get("report_tp", ""),
                "repror":      item.get("repror", ""),
                "stkqy":       _safe_int(item.get("stkqy", "")),
                "stkqy_irds":  _safe_int(item.get("stkqy_irds", "")),
                "stkrt":       _safe_float(item.get("stkrt")),
                "stkrt_irds":  _safe_float(item.get("stkrt_irds")),
                "report_resn": (item.get("report_resn") or "").replace("\n", " / ").strip(),
            })
        return rows
    except Exception:
        return []


@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_executive_stock_reports(corp_code: str, count: int = 30, _ver: int = _CACHE_VER) -> list[dict]:
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
        results = []
        for item in (data.get("list") or []):
            irds_raw = (item.get("sp_stock_lmp_irds_cnt") or "0").replace(",", "")
            try:
                irds = int(irds_raw)
            except ValueError:
                irds = 0
            results.append({
                "rcept_no": item.get("rcept_no", ""),
                "rcept_dt": item.get("rcept_dt", ""),
                "repror":   (item.get("repror") or "").strip(),
                "rgist_at": (item.get("isu_exctv_rgist_at") or "").strip(),
                "ofcps":    (item.get("isu_exctv_ofcps") or "").strip(),
                "shares":   (item.get("sp_stock_lmp_cnt") or "0").replace(",", "").strip(),
                "irds":     irds,
                "irds_raw": item.get("sp_stock_lmp_irds_cnt", "0"),
            })
        results.sort(key=lambda x: x["rcept_dt"], reverse=True)
        return results[:count]
    except Exception:
        return []


# ══════════════════════════════════════════
#  DART — 직원 현황
# ══════════════════════════════════════════

def _emp_parse_int(v: str) -> int:
    s = (v or "").strip()
    if not s or s == "-":
        return 0
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return 0


def _emp_parse_float(v: str) -> float:
    s = (v or "").strip()
    if not s or s == "-":
        return 0.0
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0


def _emp_parse_salary(v: str) -> int | None:
    s = (v or "").strip().replace(",", "")
    if not s or s == "-" or not s.isdigit():
        return None
    val = int(s)
    return val if val > 0 else None


@st.cache_data(ttl=TTL_MEDIUM, show_spinner=False)
def fetch_employee_status(corp_code: str, _ver: int = _CACHE_VER) -> dict:
    if not DART_KEY:
        return {}
    fetch_years = list(range(2015, datetime.now().year))
    result: dict[str, dict] = {}
    for year in fetch_years:
        try:
            r = requests.get(
                f"{BASE}/empSttus.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": "11011"},
                timeout=10,
            )
            raw = r.json()
            if raw.get("status") != "000":
                continue
            all_items = raw.get("list") or []
            if not all_items:
                continue

            def _pick_agg(sex: str) -> dict | None:
                rows = [x for x in all_items if (x.get("sexdstn") or "").strip() == sex]
                if not rows:
                    return None
                agg = [x for x in rows if "합계" in (x.get("fo_bbm") or "")]
                return agg[0] if agg else max(rows, key=lambda x: _emp_parse_int(x.get("sm")))

            rec: dict[str, Any] = {}
            for sex, prefix in [("남", "male"), ("여", "female")]:
                item = _pick_agg(sex)
                if not item:
                    continue
                rec[prefix]                    = _emp_parse_int(item.get("rgllbr_co"))
                rec[f"{prefix}_contract"]      = _emp_parse_int(item.get("cnttk_co"))
                rec[f"{prefix}_total"]         = _emp_parse_int(item.get("sm"))
                rec[f"avg_tenure_{prefix[0]}"] = _emp_parse_float(item.get("avrg_cnwk_sdytrn"))
                rec[f"salary_{prefix[0]}"]     = _emp_parse_salary(item.get("jan_salary_am"))

            if rec:
                rec["total"] = rec.get("male_total", 0) + rec.get("female_total", 0)
                result[str(year)] = rec
        except Exception:
            continue
    return result


# ══════════════════════════════════════════
#  주가 데이터 (yfinance)
# ══════════════════════════════════════════

def _resolve_ticker(stock_code: str, corp_cls: str) -> tuple[str, str] | None:
    primary   = ".KQ" if corp_cls == "K" else ".KS"
    secondary = ".KS" if primary == ".KQ" else ".KQ"
    for suffix in (primary, secondary):
        ticker = f"{stock_code}{suffix}"
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=True)
            if not hist.empty:
                return ticker, suffix
        except Exception:
            continue
    return None


@st.cache_data(ttl=TTL_SHORT, show_spinner=False)
def fetch_stock_chart(stock_code: str, corp_cls: str = "Y",
                      timeframe: str = "6mo", _ver: int = _CACHE_VER) -> list[dict]:
    if not _YF_AVAILABLE or not stock_code:
        return []
    try:
        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            return []
        ticker, _ = resolved
        _today = datetime.now()
        cfg = {
            "6mo":   dict(period="6mo",  interval="1d"),
            "24mo":  dict(period="2y",   interval="1d"),
            "36mo":  dict(start=(_today - timedelta(days=1097)).strftime("%Y-%m-%d"),
                         end=_today.strftime("%Y-%m-%d"), interval="1d"),
            "month": dict(period="10y",  interval="1mo"),
            "year":  dict(period="max",  interval="3mo"),
        }
        df = yf.Ticker(ticker).history(**cfg.get(timeframe, cfg["6mo"]), auto_adjust=True)
        if df.empty:
            return []
        df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
        df = df[df["Volume"] > 0]
        if timeframe in ("6mo", "24mo", "36mo"):
            df = df[df.index.dayofweek < 5]
            df = df[df["High"] > df["Low"]]
        data = [
            {
                "date":   str(dt)[:10],
                "year":   str(dt)[:4],
                "open":   round(float(row["Open"]),  0),
                "high":   round(float(row["High"]),  0),
                "low":    round(float(row["Low"]),   0),
                "close":  round(float(row["Close"]), 0),
                "volume": float(row["Volume"]),
            }
            for dt, row in df.iterrows()
        ]
        if timeframe == "year" and data:
            yearly: dict[str, dict] = {}
            for d in data:
                yr = d["year"]
                if yr not in yearly:
                    yearly[yr] = {**d, "date": yr}
                else:
                    yearly[yr]["high"]    = max(yearly[yr]["high"], d["high"])
                    yearly[yr]["low"]     = min(yearly[yr]["low"],  d["low"])
                    yearly[yr]["close"]   = d["close"]
                    yearly[yr]["volume"] += d["volume"]
            data = sorted(yearly.values(), key=lambda x: x["date"])
        return data
    except Exception:
        return []


@st.cache_data(ttl=TTL_LONG, show_spinner=False)
def fetch_yf_annual_data(stock_code: str, corp_cls: str = "Y",
                         corp_code: str = "", _ver: int = _CACHE_VER) -> dict:
    if not _YF_AVAILABLE or not stock_code:
        return {"__error__": "yfinance 없음"}
    try:
        resolved = _resolve_ticker(stock_code, corp_cls)
        if resolved is None:
            return {"__error__": "주가 데이터 없음 (KS/KQ 모두 시도)"}
        actual_ticker, _ = resolved
        t = yf.Ticker(actual_ticker)

        shares: int | None = None
        try:
            shares = t.fast_info.shares
        except Exception:
            pass
        if not shares:
            shares = (t.info or {}).get("sharesOutstanding")

        today_mktcap_eok: int | None = None
        try:
            mc = t.fast_info.market_cap
            if mc:
                today_mktcap_eok = round(float(mc) / 1e8)
        except Exception:
            pass

        today_price: float | None = None
        try:
            today_price = float(t.fast_info.last_price)
        except Exception:
            pass

        hist = t.history(period="12y", interval="1mo", auto_adjust=True)
        if hist.empty:
            return {"__error__": "주가 데이터 없음"}
        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        cur_year = datetime.now().year
        year_closes: dict[int, float] = {}
        for yr in range(cur_year - 9, cur_year + 1):
            yr_data = hist[hist.index.year == yr]
            if not yr_data.empty:
                year_closes[yr] = float(yr_data["Close"].iloc[-1])

        mktcap: dict[str, int] = {}
        if shares:
            for yr, close in year_closes.items():
                if yr != cur_year:
                    mktcap[str(yr)] = round(close * shares / 1e8)
        if today_mktcap_eok:
            mktcap[str(cur_year)] = today_mktcap_eok
        elif today_price and shares:
            mktcap[str(cur_year)] = round(today_price * shares / 1e8)
        elif shares and cur_year in year_closes:
            mktcap[str(cur_year)] = round(year_closes[cur_year] * shares / 1e8)

        per_pbr: dict[str, dict] = {}
        if corp_code and shares and shares > 0:
            target_years = [yr for yr in range(cur_year - 9, cur_year) if yr in year_closes]

            def _fetch_per_pbr(yr: int) -> tuple[int, dict | None]:
                d = fetch_year(corp_code, yr, "CFS") or fetch_year(corp_code, yr, "OFS")
                if not d:
                    return yr, None
                close = year_closes[yr]
                ni = d["is"].get("netIncome")
                eq = d["bs"].get("equity")
                per = round(close / (ni * 1e8 / shares), 1) if (ni and ni > 0) else None
                pbr = round(close / (eq * 1e8 / shares), 2) if (eq and eq > 0) else None
                return yr, {"PER": per, "PBR": pbr} if (per is not None or pbr is not None) else None

            with ThreadPoolExecutor(max_workers=5) as executor:
                for yr, pp in executor.map(_fetch_per_pbr, target_years):
                    if pp:
                        per_pbr[str(yr)] = pp

        if not per_pbr:
            try:
                fin  = t.financials
                bs_f = t.balance_sheet
                if fin is not None and not fin.empty:
                    fin_T = fin.T.copy()
                    fin_T.index = pd.to_datetime(fin_T.index).tz_localize(None)
                    bs_T = pd.DataFrame()
                    if bs_f is not None and not bs_f.empty:
                        bs_T = bs_f.T.copy()
                        bs_T.index = pd.to_datetime(bs_T.index).tz_localize(None)

                    NI_KEYS = ["Net Income", "Net Income Common Stockholders"]
                    EQ_KEYS = ["Stockholders Equity", "Common Stock Equity",
                               "Total Equity Gross Minority Interest"]

                    for idx_date in fin_T.index:
                        yr    = idx_date.year
                        close = year_closes.get(yr)
                        if close is None or not shares or shares <= 0:
                            continue
                        ni = _get_yf_val(fin_T, idx_date, NI_KEYS)
                        eq = None
                        if not bs_T.empty:
                            closest = min(bs_T.index, key=lambda d: abs((d - idx_date).days))
                            eq = _get_yf_val(bs_T, closest, EQ_KEYS)
                        per = round(close / (ni / shares), 1) if (ni and ni > 0) else None
                        pbr = round(close / (eq / shares), 2) if (eq and eq > 0) else None
                        if per is not None or pbr is not None:
                            per_pbr[str(yr)] = {"PER": per, "PBR": pbr}
            except Exception:
                pass

        if today_price and shares and shares > 0:
            today_label = datetime.now().strftime("%Y-%m-%d")
            latest_yr   = cur_year - 1
            if corp_code:
                d = fetch_year(corp_code, latest_yr, "CFS") or fetch_year(corp_code, latest_yr, "OFS")
                if d:
                    ni_t = d["is"].get("netIncome")
                    eq_t = d["bs"].get("equity")
                    today_pp: dict[str, float] = {}
                    if ni_t and ni_t > 0:
                        today_pp["PER"] = round(today_price / (ni_t * 1e8 / shares), 1)
                    if eq_t and eq_t > 0:
                        today_pp["PBR"] = round(today_price / (eq_t * 1e8 / shares), 2)
                    if today_pp:
                        per_pbr[today_label] = today_pp

        return {"mktcap": mktcap, "per_pbr": per_pbr}
    except Exception as e:
        return {"__error__": str(e)}
