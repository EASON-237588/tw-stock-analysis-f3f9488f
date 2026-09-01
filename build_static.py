# -*- coding: utf-8 -*-
"""
build_static.py — 產生「可分享的單檔純前端版」

把 static/template.html 的樣式與上市櫃公司清單內嵌，輸出一個獨立 HTML：
    dist/台股財報分析.html

這個檔案不需要伺服器：財報直接由瀏覽器向 FinMind 取得（該 API 有開 CORS），
所有指標與文案在使用者裝置上即時計算。可放靜態主機、也可直接傳檔給別人開。

用法：python build_static.py
"""

import io
import json
import os

import datasource as ds

BASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE, "dist")
OUT_FILE = os.path.join(OUT_DIR, "台股財報分析.html")


def build():
    with io.open(os.path.join(BASE, "static", "template.html"), encoding="utf-8") as f:
        html = f.read()
    with io.open(os.path.join(BASE, "web", "style.css"), encoding="utf-8") as f:
        css = f.read()

    stocks = ds.load_stock_list()
    seen = {}
    for s in stocks:
        if s["id"] not in seen and s["name"]:
            seen[s["id"]] = [s["id"], s["name"], "O" if s["market"] == "上櫃" else "L"]
    arr = sorted(seen.values())
    if len(arr) < 500:
        raise RuntimeError("股票清單抓取異常，只取得 %d 筆" % len(arr))

    html = html.replace("__STYLE__", css)
    html = html.replace("__STOCKS__", json.dumps(arr, ensure_ascii=False,
                                                 separators=(",", ":")))

    os.makedirs(OUT_DIR, exist_ok=True)
    with io.open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    # 靜態主機用的 index.html（同一份內容）
    with io.open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    # GitHub Pages 的發布來源：main 分支 /docs
    docs = os.path.join(BASE, "docs")
    os.makedirs(docs, exist_ok=True)
    with io.open(os.path.join(docs, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    size = os.path.getsize(OUT_FILE) / 1024
    print(f"完成：{OUT_FILE}")
    print(f"      收錄 {len(arr):,} 家公司，檔案 {size:.0f} KB")
    print(f"      同內容另存 dist/index.html 與 docs/index.html（GitHub Pages 用）")


if __name__ == "__main__":
    build()
