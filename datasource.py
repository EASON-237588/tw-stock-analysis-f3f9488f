# -*- coding: utf-8 -*-
"""
datasource.py — 台股財報資料來源層

資料來源：
  1. FinMind Open API  → 損益表 / 資產負債表 / 現金流量表 / 股利（免 token）
  2. MOPS 公開資訊觀測站 → 推銷 / 管理 / 研究發展費用明細（FinMind 只有營業費用合計）
  3. TWSE / TPEx OpenAPI → 上市櫃公司代號與名稱對照（供搜尋用）

原 skill 使用的 Goodinfo.tw 目前已被 Cloudflare 擋下（requests 只會拿到
"Just a moment..." 挑戰頁），因此改用上述三個官方／開放來源。
"""

import json
import os
import time

import requests
from bs4 import BeautifulSoup

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
MOPS_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t164sb04"
TWSE_LIST = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_LIST = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


# ─── 快取 ────────────────────────────────────────────────

def _cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def cache_read(name, max_age_sec):
    p = _cache_path(name)
    if not os.path.exists(p):
        return None
    if time.time() - os.path.getmtime(p) > max_age_sec:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_write(name, obj):
    try:
        with open(_cache_path(name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


# ─── 股票清單（代號 ⇄ 名稱） ──────────────────────────────

def load_stock_list(force=False):
    """回傳 [{'id','name','full','market'}]，快取 7 天。"""
    if not force:
        cached = cache_read("stocks.json", 7 * 86400)
        if cached:
            return cached

    stocks = []
    try:
        for row in requests.get(TWSE_LIST, headers=UA, timeout=25).json():
            code = str(row.get("公司代號", "")).strip()
            if len(code) == 4 and code.isdigit():
                stocks.append({
                    "id": code,
                    "name": (row.get("公司簡稱") or "").strip(),
                    "full": (row.get("公司名稱") or "").strip(),
                    "market": "上市",
                })
    except Exception:
        pass

    try:
        for row in requests.get(TPEX_LIST, headers=UA, timeout=25).json():
            code = str(row.get("SecuritiesCompanyCode", "")).strip()
            if len(code) == 4 and code.isdigit():
                stocks.append({
                    "id": code,
                    "name": (row.get("CompanyAbbreviation") or "").strip(),
                    "full": (row.get("CompanyName") or "").strip(),
                    "market": "上櫃",
                })
    except Exception:
        pass

    if stocks:
        cache_write("stocks.json", stocks)
        return stocks

    # 全部失敗時退回舊快取（不論多舊）
    p = _cache_path("stocks.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def search_stocks(q, limit=12):
    """支援代號前綴與名稱片段（簡稱優先於全名）。"""
    q = (q or "").strip()
    if not q:
        return []
    out = []
    for s in load_stock_list():
        if q.isdigit():
            score = 0 if s["id"].startswith(q) else None
        elif s["name"] == q:
            score = 0
        elif s["name"].startswith(q):
            score = 1
        elif q in s["name"]:
            score = 2
        elif q in s["full"]:
            score = 3
        else:
            score = None
        if score is not None:
            out.append((score, s["id"], s))
    out.sort(key=lambda x: (x[0], x[1]))
    return [s for _, _, s in out[:limit]]


def resolve(q):
    """把使用者輸入（代號或名稱）解析成單一檔股票；找不到回 None。"""
    hits = search_stocks(q, limit=1)
    return hits[0] if hits else None


def stock_info(stock_id):
    for s in load_stock_list():
        if s["id"] == stock_id:
            return s
    return {"id": stock_id, "name": stock_id, "full": "", "market": "上市"}


# ─── FinMind ─────────────────────────────────────────────

def finmind(dataset, stock_id, start_date, end_date=None):
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
    if end_date:
        params["end_date"] = end_date
    r = requests.get(FINMIND_URL, params=params, headers=UA, timeout=40)
    if r.status_code == 402:
        raise RuntimeError("FinMind 免費額度已用完，請稍後再試（每小時上限）")
    r.raise_for_status()
    j = r.json()
    if j.get("status") not in (200, None) and not j.get("data"):
        raise RuntimeError(f"FinMind 回應異常：{j.get('msg')}")
    return j.get("data", [])


def pivot(rows, value_key="value"):
    """把 FinMind 長格式轉成 {date: {type: value}}。"""
    out = {}
    for x in rows:
        out.setdefault(x["date"], {})[x["type"]] = x.get(value_key)
    return out


# ─── MOPS 營業費用明細 ────────────────────────────────────

MOPS_FIELDS = {
    "sell": "推銷費用",
    "admin": "管理費用",
    "rd": "研究發展費用",
    "opex": "營業費用合計",
}


def fetch_mops_opex(stock_id, year):
    """抓取某年度綜合損益表，回傳 {西元年: {sell, admin, rd, opex}}（單位：元）。

    MOPS 同一張表會同時列出當年度與前一年度，因此一次請求可得兩年。
    """
    data = {}
    try:
        r = requests.post(MOPS_URL, headers=UA, timeout=30, data={
            "encodeURIComponent": 1, "step": 1, "firstin": 1, "off": 1,
            "queryName": "co_id", "inpuType": "co_id", "TYPEK": "all",
            "isnew": "false", "co_id": stock_id,
            "year": str(year - 1911), "season": "04",
        })
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return data

    table = None
    for t in soup.find_all("table"):
        if "營業收入" in t.get_text():
            table = t
            break
    if table is None:
        return data

    col_years = []      # [(欄位index, 西元年)]
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue

        if not col_years:
            found = []
            for i, c in enumerate(cells):
                if c.endswith("年度") and c[:-2].isdigit():
                    found.append((i, int(c[:-2]) + 1911))
            if found:
                # 表頭「會計項目 / 114年度 / 113年度」，資料列為
                # 「項目 / 金額 / % / 金額 / %」→ 第 n 個年度對應第 2n-1 欄
                col_years = [(1 + 2 * k, yr) for k, (_, yr) in enumerate(found)]
            continue

        name = cells[0]
        key = next((k for k, label in MOPS_FIELDS.items() if name == label), None)
        if key is None:
            continue
        for idx, yr in col_years:
            if idx < len(cells):
                raw = cells[idx].replace(",", "").replace("(", "-").replace(")", "")
                try:
                    # MOPS 單位為仟元
                    data.setdefault(yr, {})[key] = float(raw) * 1000
                except ValueError:
                    pass
    return data


def fetch_opex_breakdown(stock_id, years):
    """years 為西元年列表（遞增）。每次請求涵蓋兩年，故隔年送出即可。"""
    out = {}
    todo = sorted(set(years), reverse=True)
    fetched = set()
    for yr in todo:
        if yr in out:
            continue
        if yr in fetched:
            continue
        got = fetch_mops_opex(stock_id, yr)
        fetched.add(yr)
        for k, v in got.items():
            out.setdefault(k, {}).update(v)
        time.sleep(0.4)
    return out
