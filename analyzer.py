# -*- coding: utf-8 -*-
"""
analyzer.py — 三維財務分析引擎

輸入股票代號，輸出儀表板所需的完整 JSON：
  年度序列 → 衍生指標 → KPI 卡文案 → Insight 觀察 → 資料表趨勢評估 → 合理性檢查
金額單位一律為「億元」。
"""

import time

import datasource as ds

E = 1e8  # 元 → 億元


# ─── 小工具 ───────────────────────────────────────────────

def div(a, b, scale=100.0):
    if a is None or not b:
        return None
    return a / b * scale


def pick(d, *keys):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def fmt(v, digits=1, unit=""):
    if v is None:
        return "—"
    if abs(v) >= 10000:
        return f"{v:,.0f}{unit}"
    return f"{v:,.{digits}f}{unit}"


def yoy(series):
    """最新一年相對前一年的成長率 %。"""
    vals = [v for v in series if v is not None]
    if len(vals) < 2 or not vals[-2]:
        return None
    return (vals[-1] - vals[-2]) / abs(vals[-2]) * 100


def cagr(series):
    vals = [v for v in series if v is not None]
    if len(vals) < 2 or vals[0] <= 0 or vals[-1] <= 0:
        return None
    n = len(vals) - 1
    return ((vals[-1] / vals[0]) ** (1.0 / n) - 1) * 100


def last(series):
    for v in reversed(series):
        if v is not None:
            return v
    return None


def delta(series):
    """最新一年 － 前一年（絕對差，適用於百分比類指標）。"""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return None
    return vals[-1] - vals[-2]


def seq(series, digits=1, unit=""):
    """把序列排成「a → b → c」字串。"""
    return " → ".join(fmt(v, digits) for v in series) + unit


# ─── 主流程 ───────────────────────────────────────────────

def analyze(stock_id, n_years=5):
    info = ds.stock_info(stock_id)
    start = f"{time.localtime().tm_year - n_years - 1}-01-01"

    is_rows = ds.finmind("TaiwanStockFinancialStatements", stock_id, start)
    if not is_rows:
        raise RuntimeError(f"查無 {stock_id} 的財報資料，請確認代號是否為上市櫃公司")
    bs_rows = ds.finmind("TaiwanStockBalanceSheet", stock_id, start)
    cf_rows = ds.finmind("TaiwanStockCashFlowsStatement", stock_id, start)
    try:
        dv_rows = ds.finmind("TaiwanStockDividend", stock_id, start)
    except Exception:
        dv_rows = []

    IS, BS, CF = ds.pivot(is_rows), ds.pivot(bs_rows), ds.pivot(cf_rows)

    # 完整年度＝該年 4 季損益表齊全，且有 12/31 的資產負債表
    def is_quarters(y):
        return [d for d in IS if d.startswith(str(y))]

    all_years = sorted({int(d[:4]) for d in IS})
    years = [y for y in all_years
             if len(is_quarters(y)) == 4 and f"{y}-12-31" in BS]
    years = years[-n_years:]
    if not years:
        raise RuntimeError(f"{stock_id} 尚無完整年度財報可供分析")

    opex_detail = ds.fetch_opex_breakdown(stock_id, years)

    # 現金股利：依「盈餘所屬年度」歸戶（FinMind year 欄位為民國年）
    dps = {}
    for row in dv_rows:
        label = str(row.get("year", ""))
        roc = "".join(ch for ch in label.split("年")[0] if ch.isdigit())
        if not roc:
            continue
        y = int(roc) + 1911
        dps[y] = dps.get(y, 0.0) + (row.get("CashEarningsDistribution") or 0.0)

    S = {}   # 金額序列（億元）
    def put(key, values):
        S[key] = values

    def is_sum(y, *keys):
        total = None
        for d in sorted(is_quarters(y)):
            v = pick(IS[d], *keys)
            if v is not None:
                total = (total or 0) + v
        return total

    put("revenue",      [div(is_sum(y, "Revenue"), E, 1) for y in years])
    put("cogs",         [div(is_sum(y, "CostOfGoodsSold"), E, 1) for y in years])
    put("gross_profit", [div(is_sum(y, "GrossProfit"), E, 1) for y in years])
    put("op_expense",   [div(is_sum(y, "OperatingExpenses"), E, 1) for y in years])
    put("op_income",    [div(is_sum(y, "OperatingIncome"), E, 1) for y in years])
    put("pretax",       [div(is_sum(y, "PreTaxIncome"), E, 1) for y in years])
    put("net_income",   [div(is_sum(y, "IncomeAfterTaxes",
                                    "TotalConsolidatedProfitForThePeriod"), E, 1)
                         for y in years])
    put("eps",          [is_sum(y, "EPS") for y in years])

    for k in ("sell", "admin", "rd"):
        put(k, [div(opex_detail.get(y, {}).get(k), E, 1) for y in years])

    def bs_get(y, *keys):
        return div(pick(BS.get(f"{y}-12-31", {}), *keys), E, 1)

    put("cash",         [bs_get(y, "CashAndCashEquivalents") for y in years])
    put("receivable",   [bs_get(y, "AccountsReceivableNet") for y in years])
    put("inventory",    [bs_get(y, "Inventories") for y in years])
    put("cur_assets",   [bs_get(y, "CurrentAssets") for y in years])
    put("cur_liab",     [bs_get(y, "CurrentLiabilities") for y in years])
    put("liabilities",  [bs_get(y, "Liabilities") for y in years])
    put("assets",       [bs_get(y, "TotalAssets") for y in years])
    put("equity",       [bs_get(y, "EquityAttributableToOwnersOfParent", "Equity")
                         for y in years])

    def cf_get(y, *keys):
        return div(pick(CF.get(f"{y}-12-31", {}), *keys), E, 1)

    put("ocf",      [cf_get(y, "CashFlowsFromOperatingActivities",
                            "NetCashInflowFromOperatingActivities") for y in years])
    put("icf",      [cf_get(y, "CashProvidedByInvestingActivities") for y in years])
    put("fcf_fin",  [cf_get(y, "CashFlowsProvidedFromFinancingActivities") for y in years])
    put("capex",    [cf_get(y, "PropertyAndPlantAndEquipment") for y in years])
    put("cash_end", [cf_get(y, "CashBalancesEndOfPeriod") for y in years])
    put("dps",      [dps.get(y) for y in years])

    # ─── 衍生指標 ───
    M = {}
    n = len(years)
    def ratio(name, num, den, scale=100.0):
        M[name] = [div(S[num][i], S[den][i], scale) for i in range(n)]

    ratio("gross_margin", "gross_profit", "revenue")
    ratio("op_margin", "op_income", "revenue")
    ratio("net_margin", "net_income", "revenue")
    ratio("opex_ratio", "op_expense", "revenue")
    ratio("sell_ratio", "sell", "revenue")
    ratio("admin_ratio", "admin", "revenue")
    ratio("rd_ratio", "rd", "revenue")
    ratio("current_ratio", "cur_assets", "cur_liab")
    ratio("debt_ratio", "liabilities", "assets")
    ratio("roe", "net_income", "equity")
    ratio("roa", "net_income", "assets")
    ratio("inv_ratio", "inventory", "cur_assets")

    M["fcf"] = [(S["ocf"][i] + S["capex"][i])
                if S["ocf"][i] is not None and S["capex"][i] is not None else None
                for i in range(n)]
    M["ocf_to_ni"] = [div(S["ocf"][i], S["net_income"][i], 1.0) for i in range(n)]
    M["payout"] = [div(S["dps"][i], S["eps"][i]) for i in range(n)]

    result = {
        "stock_id": stock_id,
        "name": info.get("name") or stock_id,
        "full_name": info.get("full", ""),
        "market": info.get("market", ""),
        "years": years,
        "series": S,
        "metrics": M,
        "kpis": build_kpis(years, S, M),
        "insights": build_insights(years, S, M),
        "tables": build_tables(years, S, M),
        "metadata": {
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sources": ["FinMind Open API（財報三表・股利）",
                        "MOPS 公開資訊觀測站（管銷研發明細）"],
            "mops_url": ("https://mopsov.twse.com.tw/mops/web/t05st01?step=1"
                         f"&co_id={stock_id}&TYPEK="
                         + ("otc" if info.get("market") == "上櫃" else "sii")),
            "finmind_url": ("https://api.finmindtrade.com/api/v4/data?dataset="
                            f"TaiwanStockFinancialStatements&data_id={stock_id}"),
            "currency": "TWD 億元",
            "years_covered": years,
        },
    }
    result["verification"] = verify(years, S, M)
    return result


# ─── 合理性檢查 ───────────────────────────────────────────

def verify(years, S, M):
    warns = []
    for i, y in enumerate(years):
        gm = M["gross_margin"][i]
        if gm is not None:
            if gm > 100:
                warns.append({"level": "error", "field": f"{y} 毛利率",
                              "msg": f"{gm:.1f}% 超過 100%，數據可能有誤"})
            elif gm < -50:
                warns.append({"level": "error", "field": f"{y} 毛利率",
                              "msg": f"{gm:.1f}% 低於 -50%，請確認是否為特殊損失年度"})
        cr = M["current_ratio"][i]
        if cr is not None and cr < 0:
            warns.append({"level": "error", "field": f"{y} 流動比率",
                          "msg": f"{cr:.1f}% 為負值，請檢查資產負債表數據"})
        dr = M["debt_ratio"][i]
        if dr is not None and dr > 100:
            warns.append({"level": "warn", "field": f"{y} 負債比率",
                          "msg": f"{dr:.1f}% 超過 100%，若非金融業則為警示訊號"})
        roe = M["roe"][i]
        if roe is not None and roe > 100:
            warns.append({"level": "warn", "field": f"{y} ROE",
                          "msg": f"{roe:.1f}% 超過 100%，可能為高槓桿，請確認股東權益是否偏低"})

    for i in range(1, len(years)):
        a, b = M["net_margin"][i - 1], M["net_margin"][i]
        if a is not None and b is not None and abs(b - a) > 30:
            warns.append({"level": "warn",
                          "field": f"{years[i-1]}→{years[i]} 淨利率",
                          "msg": f"波動 {b - a:+.1f} 個百分點，建議確認是否有一次性損益"})

    if all(v is None for v in M["gross_margin"]):
        warns.append({"level": "warn", "field": "行業別",
                      "msg": "本公司財報無「營業毛利」與「流動／非流動」分類（金融、保險、"
                             "證券等特殊行業），毛利率、營業利益率、流動比率不適用，"
                             "負債比率偏高亦屬行業常態"})

    missing = [k for k in ("sell", "admin", "rd")
               if all(v is None for v in S[k])]
    if missing:
        warns.append({"level": "warn", "field": "營業費用明細",
                      "msg": "MOPS 未提供推銷／管理／研發拆分（常見於金融、營建等特殊行業），"
                             "費用分析改以營業費用合計呈現"})

    return {"sanity": warns,
            "sanity_pass": all(w["level"] != "error" for w in warns)}


# ─── KPI 卡 ──────────────────────────────────────────────

def kpi(label, value, sub, tone):
    return {"label": label, "value": value, "sub": sub, "tone": tone}


def tone_by(v, good, warn, reverse=False):
    """v 大於 good 為佳（reverse=True 時反過來）。"""
    if v is None:
        return "blue"
    if reverse:
        if v <= good:
            return "green"
        return "orange" if v <= warn else "red"
    if v >= good:
        return "green"
    return "orange" if v >= warn else "red"


def arrow(v, invert=False):
    if v is None:
        return "■"
    if abs(v) < 0.5:
        return "■"
    up = v > 0
    if invert:
        up = not up
    return "▲" if up else "▼"


def dir_tone(v, invert=False):
    if v is None or abs(v) < 0.5:
        return "blue"
    good = (v > 0) if not invert else (v < 0)
    return "green" if good else "orange"


def build_kpis(years, S, M):
    yl = [str(y) for y in years]
    special = all(v is None for v in M["gross_margin"])   # 金融等特殊行業
    rev_yoy, rev_cagr = yoy(S["revenue"]), cagr(S["revenue"])
    ni_yoy = yoy(S["net_income"])
    eps_yoy = yoy(S["eps"])

    ops = [
        kpi("年度營收", fmt(last(S["revenue"]), 0), "億元　" + (
            f"{arrow(rev_yoy)} {rev_yoy:+.1f}% YoY（{yl[-1]}年）；"
            f"{len(years)}年 CAGR {rev_cagr:+.1f}%" if rev_yoy is not None else "—"),
            dir_tone(rev_yoy)),
        kpi("毛利率", fmt(last(M["gross_margin"]), 1) + "%",
            f"{arrow(delta(M['gross_margin']))} {seq(M['gross_margin'][-3:])}%"
            f"（{'/'.join(yl[-3:])}）", dir_tone(delta(M["gross_margin"]))),
        kpi("營業利益率", fmt(last(M["op_margin"]), 1) + "%",
            f"{arrow(delta(M['op_margin']))} 較前一年 {fmt(delta(M['op_margin']), 1)} 個百分點；"
            f"營業利益 {fmt(last(S['op_income']), 0)} 億",
            dir_tone(delta(M["op_margin"]))),
        kpi("營業費用率", fmt(last(M["opex_ratio"]), 1) + "%",
            f"{arrow(delta(M['opex_ratio']))} 營業費用 "
            f"{fmt(last(S['op_expense']), 0)} 億；{seq(M['opex_ratio'][-3:])}%",
            dir_tone(delta(M["opex_ratio"]), invert=True)),
    ]
    if last(S["rd"]) is not None:
        ops.append(kpi("研發費用率", fmt(last(M["rd_ratio"]), 1) + "%",
                       f"{arrow(delta(M['rd_ratio']))} 研發 {fmt(last(S['rd']), 0)} 億；"
                       f"推銷 {fmt(last(M['sell_ratio']), 1)}%／管理 "
                       f"{fmt(last(M['admin_ratio']), 1)}%", "blue"))
    else:
        ops.append(kpi("營業利益", fmt(last(S["op_income"]), 0),
                       f"億元　{arrow(yoy(S['op_income']))} "
                       f"{fmt(yoy(S['op_income']), 1)}% YoY",
                       dir_tone(yoy(S["op_income"]))))

    profit = [
        kpi("稅後淨利", fmt(last(S["net_income"]), 0), "億元　" + (
            f"{arrow(ni_yoy)} {ni_yoy:+.1f}% YoY；淨利率 "
            f"{fmt(last(M['net_margin']), 1)}%" if ni_yoy is not None else "—"),
            dir_tone(ni_yoy)),
        kpi("EPS", fmt(last(S["eps"]), 2), "元　" + (
            f"{arrow(eps_yoy)} {eps_yoy:+.1f}% YoY；{seq(S['eps'][-3:], 2)} 元"
            if eps_yoy is not None else "—"), dir_tone(eps_yoy)),
        kpi("ROE", fmt(last(M["roe"]), 1) + "%",
            f"{arrow(delta(M['roe']))} {seq(M['roe'][-3:])}%；"
            f"{'高於' if (last(M['roe']) or 0) >= 15 else '低於'} 15% 標竿",
            tone_by(last(M["roe"]), 15, 8)),
        kpi("ROA", fmt(last(M["roa"]), 1) + "%",
            f"{arrow(delta(M['roa']))} 總資產 {fmt(last(S['assets']), 0)} 億；"
            f"較前一年 {fmt(delta(M['roa']), 1)} 個百分點",
            tone_by(last(M["roa"]), 8, 3)),
        kpi("三層利潤率", f"{fmt(last(M['gross_margin']), 1)}/"
                       f"{fmt(last(M['op_margin']), 1)}/"
                       f"{fmt(last(M['net_margin']), 1)}"
            if last(M["op_margin"]) is not None else fmt(last(M["net_margin"]), 1) + "%",
            (f"毛利／營益／淨利（%）；{yl[-1]} 年淨利率較前一年 "
             f"{fmt(delta(M['net_margin']), 1)} 個百分點"
             if last(M["op_margin"]) is not None else
             f"本公司財報無毛利／營業利益分類（金融等特殊行業），僅列淨利率；"
             f"較前一年 {fmt(delta(M['net_margin']), 1)} 個百分點"),
            dir_tone(delta(M["net_margin"]))),
    ]

    cr, dr = last(M["current_ratio"]), last(M["debt_ratio"])
    health = [
        kpi("流動比率", fmt(cr, 0) + "%",
            f"{arrow(delta(M['current_ratio']))} {seq(M['current_ratio'][-3:], 0)}%；"
            + ("財報未分流動／非流動（金融等特殊行業），此指標不適用" if cr is None else
               "高於 200% 優異" if cr >= 200 else
               "高於 150% 健康" if cr >= 150 else "低於 150% 警戒線"),
            tone_by(cr, 150, 100)),
        kpi("負債比率", fmt(dr, 1) + "%",
            f"{arrow(delta(M['debt_ratio']))} {seq(M['debt_ratio'][-3:])}%；"
            + ("金融業以存款與負債經營，高負債比為行業常態" if special else
               "已逾 60% 需關注" if (dr or 0) >= 60 else "維持 60% 以下"),
            tone_by(dr, 50, 65, reverse=True)),
        kpi("現金部位", fmt(last(S["cash"]), 0),
            f"億元　{arrow(yoy(S['cash']))} {fmt(yoy(S['cash']), 1)}% YoY；"
            f"占總資產 {fmt(div(last(S['cash']), last(S['assets'])), 1)}%",
            dir_tone(yoy(S["cash"]))),
        kpi("營業現金流", fmt(last(S["ocf"]), 0),
            f"億元　營業CF／淨利 = {fmt(last(M['ocf_to_ni']), 2)} 倍"
            + ("（> 1 佳）" if (last(M["ocf_to_ni"]) or 0) >= 1 else "（< 1 需留意）"),
            tone_by(last(M["ocf_to_ni"]), 1.0, 0.7)),
        kpi("自由現金流", fmt(last(M["fcf"]), 0),
            f"億元　營業CF {fmt(last(S['ocf']), 0)} － 資本支出 "
            f"{fmt(abs(last(S['capex']) or 0), 0)} 億",
            "green" if (last(M["fcf"]) or 0) > 0 else "orange"),
    ]
    def usable(cards):
        return [c for c in cards if not str(c["value"]).startswith("—")]

    return {"ops": usable(ops), "profit": usable(profit),
            "health": usable(health)}


# ─── Insight ─────────────────────────────────────────────

def build_insights(years, S, M):
    yl = [str(y) for y in years]
    ops, profit, health = [], [], []

    rc, ry = cagr(S["revenue"]), yoy(S["revenue"])
    if ry is not None:
        ops.append(f"{len(years)} 年營收 {seq(S['revenue'], 0)} 億元，CAGR {rc:+.1f}%，"
                   f"{yl[-1]} 年{'加速成長' if (rc or 0) < ry else '成長趨緩'} {ry:+.1f}%。")
    gd = delta(M["gross_margin"])
    if gd is not None:
        ops.append(f"毛利率 {seq(M['gross_margin'][-3:])}%，{yl[-1]} 年較前一年 "
                   f"{gd:+.1f} 個百分點，"
                   + ("反映產品組合／成本控制改善。" if gd > 0.5 else
                      "成本端壓力上升，需觀察售價轉嫁能力。" if gd < -0.5 else
                      "維持高檔震盪，結構穩定。"))
    od = delta(M["opex_ratio"])
    if od is not None:
        ops.append(f"營業費用率 {seq(M['opex_ratio'][-3:])}%，"
                   + (f"隨營收規模擴大而下降 {abs(od):.1f} 個百分點，規模效益浮現。"
                      if od < -0.2 else
                      f"上升 {od:.1f} 個百分點，費用成長快於營收。" if od > 0.2 else
                      "大致持平，費用管控穩定。"))
    if last(S["rd"]) is not None:
        ops.append(f"{yl[-1]} 年研發 {fmt(last(S['rd']), 0)} 億（占營收 "
                   f"{fmt(last(M['rd_ratio']), 1)}%）、管理 {fmt(last(S['admin']), 0)} 億、"
                   f"推銷 {fmt(last(S['sell']), 0)} 億，研發為費用結構主體。"
                   if (last(M["rd_ratio"]) or 0) >= (last(M["admin_ratio"]) or 0)
                   else f"{yl[-1]} 年推銷 {fmt(last(S['sell']), 0)} 億、管理 "
                        f"{fmt(last(S['admin']), 0)} 億、研發 {fmt(last(S['rd']), 0)} 億，"
                        f"銷管為費用結構主體。")
    omd = delta(M["op_margin"])
    if omd is not None:
        ops.append(f"營業利益 {fmt(last(S['op_income']), 0)} 億，利益率 "
                   f"{seq(M['op_margin'][-3:])}%，"
                   + ("毛利提升與費用攤薄同時發生，本業獲利力增強。" if omd > 0.5 else
                      "本業獲利力較前一年收斂。" if omd < -0.5 else "本業獲利力維持穩定。"))

    ey = yoy(S["eps"])
    if ey is not None:
        peak = max((v for v in S["eps"] if v is not None), default=None)
        profit.append(f"EPS {seq(S['eps'], 2)} 元，{yl[-1]} 年 {ey:+.1f}% YoY，"
                      + ("創期間新高。" if peak is not None and
                         abs((last(S['eps']) or 0) - peak) < 1e-9 else "尚未回到期間高點。"))
    ny, rry = yoy(S["net_income"]), yoy(S["revenue"])
    if ny is not None and rry is not None:
        cmp_ = ("高於營收成長" if ny > rry else
                "衰退幅度大於營收" if (ny < 0 and rry < 0) else "低於營收成長")
        profit.append(f"稅後淨利 {fmt(last(S['net_income']), 0)} 億（{ny:+.1f}%）{cmp_}"
                      f"（{rry:+.1f}%），"
                      f"淨利率{'擴張' if ny > rry else '收斂'}至 "
                      f"{fmt(last(M['net_margin']), 1)}%。")
    rd_ = delta(M["roe"])
    if rd_ is not None:
        profit.append(f"ROE {seq(M['roe'][-3:])}%，{yl[-1]} 年 {rd_:+.1f} 個百分點，"
                      + ("獲利成長快於股東權益累積。" if rd_ > 0 else
                         "權益累積速度快於獲利成長，資本效率下滑。"))
    if last(M["op_margin"]) is not None:
        profit.append(f"三層利潤率 {yl[-1]} 年為毛利 {fmt(last(M['gross_margin']), 1)}%／"
                      f"營益 {fmt(last(M['op_margin']), 1)}%／淨利 "
                      f"{fmt(last(M['net_margin']), 1)}%，營益到淨利差距 "
                      f"{fmt(last(M['net_margin']) - last(M['op_margin']), 1)} "
                      f"個百分點（業外與稅負影響）。")
    if last(S["dps"]) is not None:
        profit.append(f"現金股利 {seq(S['dps'][-3:], 2)} 元／股，"
                      f"{yl[-1]} 年配息率約 {fmt(last(M['payout']), 0)}%。")

    cr = last(M["current_ratio"])
    if cr is not None:
        health.append(f"流動比率 {seq(M['current_ratio'][-3:], 0)}%，"
                      + ("維持 200% 以上，短期償債能力優異。" if cr >= 200 else
                         "高於 150% 健康水準。" if cr >= 150 else
                         "低於 150% 警戒線，短期流動性需留意。"))
    dr = last(M["debt_ratio"])
    if dr is not None:
        dd = delta(M["debt_ratio"])
        health.append(f"負債比率 {seq(M['debt_ratio'][-3:])}%，{yl[-1]} 年 "
                      f"{(dd or 0):+.1f} 個百分點，"
                      + ("已超過 60%，槓桿偏高需持續追蹤。" if dr >= 60 else
                         "維持 60% 以下的安全區間。"))
    cy = yoy(S["cash"])
    if cy is not None:
        health.append(f"現金及約當現金 {fmt(last(S['cash']), 0)} 億（{cy:+.1f}% YoY），"
                      f"占總資產 {fmt(div(last(S['cash']), last(S['assets'])), 1)}%，"
                      f"當年資本支出 {fmt(abs(last(S['capex']) or 0), 0)} 億、"
                      f"融資活動淨額 {fmt(last(S['fcf_fin']), 0)} 億。")
    ratio_ = last(M["ocf_to_ni"])
    if ratio_ is not None:
        health.append(f"營業現金流 {fmt(last(S['ocf']), 0)} 億為稅後淨利的 "
                      f"{ratio_:.2f} 倍，"
                      + ("獲利品質良好（現金實現度 > 1）。" if ratio_ >= 1 else
                         "低於 1 倍，需檢視應收與存貨的資金占用。"))
    f_ = last(M["fcf"])
    if f_ is not None:
        health.append(f"自由現金流 {fmt(f_, 0)} 億（營業CF {fmt(last(S['ocf']), 0)} － 資本支出 "
                      f"{fmt(abs(last(S['capex']) or 0), 0)}），"
                      + ("足以支應股利與再投資。" if f_ > 0 else
                         "為負數，擴張期資本支出大於營運現金產出。"))

    return {"ops": ops, "profit": profit, "health": health}


# ─── 資料表 ──────────────────────────────────────────────

def trend(series, invert=False, pct=False, threshold=1.0):
    """回傳 (符號+文字, tone)。"""
    vals = [v for v in series if v is not None]
    if len(vals) < 2:
        return ("— 資料不足", "neutral")
    a, b = vals[-2], vals[-1]
    d = b - a
    rel = (d / abs(a) * 100) if a else None
    peak = max(vals)
    trough = min(vals)

    if pct:
        moved = abs(d) >= threshold
        txt_amt = f"{d:+.1f}pp"
    else:
        moved = rel is not None and abs(rel) >= threshold
        txt_amt = f"{rel:+.1f}%" if rel is not None else f"{d:+.1f}"

    if not moved:
        return ("■ 大致持平", "neutral")
    up = d > 0
    good = (not up) if invert else up
    if invert:
        # 成本、費用、負債類：只陳述增減，不用「創新高」這種帶褒貶的說法
        txt = ("▲ 增 " if up else "▼ 減 ") + txt_amt.lstrip("+-")
    elif up and abs(b - peak) < 1e-9:
        txt = f"▲ 創新高 {txt_amt}"
    elif (not up) and abs(b - trough) < 1e-9:
        txt = f"▼ 探新低 {txt_amt}"
    else:
        txt = ("▲ " if up else "▼ ") + txt_amt
    return (txt, "up" if good else "down")


def row(name, series, digits=1, invert=False, pct=False, threshold=1.0):
    t, tone = trend(series, invert=invert, pct=pct, threshold=threshold)
    return {"name": name,
            "values": [fmt(v, digits) if v is not None else "—" for v in series],
            "trend": t, "tone": tone}


def build_tables(years, S, M):
    k = 3
    cols = [str(y) for y in years[-k:]]
    def s(key, src=S):
        return src[key][-k:]

    ops = {"title": "損益表明細（億元）", "cols": cols, "rows": [
        row("營業收入", s("revenue"), 0),
        row("營業成本", s("cogs"), 0, invert=True),
        row("營業毛利", s("gross_profit"), 0),
        row("毛利率 %", s("gross_margin", M), 1, pct=True),
        row("營業費用", s("op_expense"), 0, invert=True),
        row("費用率 %", s("opex_ratio", M), 1, pct=True, invert=True),
        row("推銷費用", s("sell"), 0, invert=True),
        row("管理費用", s("admin"), 0, invert=True),
        row("研發費用", s("rd"), 0),
        row("營業利益", s("op_income"), 0),
        row("營業利益率 %", s("op_margin", M), 1, pct=True),
    ]}

    profit = {"title": "獲利能力彙總", "cols": cols, "rows": [
        row("稅前淨利（億）", s("pretax"), 0),
        row("稅後淨利（億）", s("net_income"), 0),
        row("EPS（元）", s("eps"), 2),
        row("毛利率 %", s("gross_margin", M), 1, pct=True),
        row("營業利益率 %", s("op_margin", M), 1, pct=True),
        row("淨利率 %", s("net_margin", M), 1, pct=True),
        row("ROE %", s("roe", M), 1, pct=True),
        row("ROA %", s("roa", M), 1, pct=True),
        row("現金股利（元）", s("dps"), 2),
        row("配息率 %", s("payout", M), 0, pct=True, threshold=3),
    ]}

    health = {"title": "資產負債與現金流（億元）", "cols": cols, "rows": [
        row("現金及約當現金", s("cash"), 0),
        row("應收帳款", s("receivable"), 0),
        row("存貨", s("inventory"), 0, invert=True),
        row("流動資產", s("cur_assets"), 0),
        row("流動負債", s("cur_liab"), 0, invert=True),
        row("負債總額", s("liabilities"), 0, invert=True),
        row("股東權益", s("equity"), 0),
        row("資產總額", s("assets"), 0),
        row("流動比率 %", s("current_ratio", M), 0, pct=True, threshold=5),
        row("負債比率 %", s("debt_ratio", M), 1, pct=True, invert=True),
        row("營業活動現金流", s("ocf"), 0),
        row("投資活動現金流", s("icf"), 0),
        row("融資活動現金流", s("fcf_fin"), 0),
        row("資本支出", s("capex"), 0),
        row("自由現金流", s("fcf", M), 0),
    ]}
    return {"ops": ops, "profit": profit, "health": health}


if __name__ == "__main__":
    import json
    import sys
    sid = sys.argv[1] if len(sys.argv) > 1 else "2330"
    print(json.dumps(analyze(sid), ensure_ascii=False, indent=1))
