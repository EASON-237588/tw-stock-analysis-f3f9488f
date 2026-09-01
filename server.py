# -*- coding: utf-8 -*-
"""
server.py — 台股財報分析 本機伺服器

啟動：  python server.py            （預設 http://localhost:8899）
手機看：同一個 Wi-Fi 下用手機開 http://<電腦區網IP>:8899

為什麼需要伺服器：財報資料來自 FinMind 與 MOPS，兩者都沒有開放 CORS，
瀏覽器無法直接抓取，必須由本機這支程式代為請求並轉成 JSON。
"""

import json
import os
import socket
import sys
import threading
import time
import traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import analyzer                                    # noqa: E402
import datasource as ds                            # noqa: E402

WEB = os.path.join(BASE, "web")
PORT = int(os.environ.get("PORT", "8899"))
CACHE_TTL = 12 * 3600                              # 分析結果快取 12 小時
_locks = {}
_locks_guard = threading.Lock()

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".json": "application/json; charset=utf-8"}


def get_analysis(stock_id):
    """帶快取的分析（同一檔股票同時只跑一次）。"""
    name = f"analysis_{stock_id}.json"
    cached = ds.cache_read(name, CACHE_TTL)
    if cached:
        cached["cached"] = True
        return cached

    with _locks_guard:
        lock = _locks.setdefault(stock_id, threading.Lock())
    with lock:
        cached = ds.cache_read(name, CACHE_TTL)
        if cached:
            cached["cached"] = True
            return cached
        result = analyzer.analyze(stock_id)
        ds.cache_write(name, result)
        result["cached"] = False
        return result


def build_standalone(data):
    """把分析結果嵌進 HTML，產生可離線保存／分享的單檔報告。"""
    def read(p):
        with open(os.path.join(WEB, p), "r", encoding="utf-8") as f:
            return f.read()

    html = read("index.html")
    html = html.replace('<link rel="stylesheet" href="/static/style.css">',
                        "<style>\n" + read("style.css") + "\n</style>")
    payload = json.dumps(data, ensure_ascii=False)
    html = html.replace('<script src="/static/app.js"></script>',
                        "<script>window.__PRELOAD__ = " + payload + ";</script>\n"
                        "<script>\n" + read("app.js") + "\n</script>")
    return html


class Handler(BaseHTTPRequestHandler):
    server_version = "TWStock/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # ── 回應工具 ──
    def send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, code=200):
        self.send(code, json.dumps(obj, ensure_ascii=False),
                  "application/json; charset=utf-8")

    def send_file(self, path):
        full = os.path.join(WEB, path)
        if not os.path.isfile(full):
            return self.send(404, "not found")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            self.send(200, f.read(), MIME.get(ext, "application/octet-stream"))

    # ── 路由 ──
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path

        try:
            if path in ("/", "/index.html"):
                return self.send_file("index.html")
            if path.startswith("/static/"):
                return self.send_file(path[len("/static/"):])

            if path == "/api/search":
                return self.send_json({"results": ds.search_stocks(q.get("q", [""])[0])})

            if path in ("/api/analyze", "/api/export"):
                key = (q.get("q", [""])[0] or q.get("id", [""])[0]).strip()
                if not key:
                    return self.send_json({"error": "請輸入股票名稱或代號"}, 400)

                hit = ds.resolve(key)
                if hit is None:
                    if key.isdigit() and len(key) == 4:
                        hit = {"id": key}
                    else:
                        return self.send_json(
                            {"error": f"找不到「{key}」，請確認是上市／上櫃公司的名稱或 4 位數代號"}, 404)

                t0 = time.time()
                data = get_analysis(hit["id"])
                data["elapsed"] = round(time.time() - t0, 1)

                if path == "/api/analyze":
                    return self.send_json(data)

                fname = f"{data['name']}_{data['stock_id']}_analysis.html"
                return self.send(200, build_standalone(data),
                                 "text/html; charset=utf-8",
                                 {"Content-Disposition":
                                  "attachment; filename*=UTF-8''" + quote(fname)})

            return self.send(404, "not found")

        except RuntimeError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:
            traceback.print_exc()
            self.send_json({"error": f"分析失敗：{e}"}, 500)


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    print("─" * 52)
    print(" 台股財報分析　伺服器啟動中…")
    print(f"   電腦：http://localhost:{PORT}")
    print(f"   手機：http://{lan_ip()}:{PORT}   （需與電腦同一個 Wi-Fi）")
    print("   按 Ctrl+C 結束")
    print("─" * 52)
    threading.Thread(target=ds.load_stock_list, daemon=True).start()
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
