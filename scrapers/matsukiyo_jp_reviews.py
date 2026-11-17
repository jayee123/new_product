"""
松本清日本官網（マツキヨココカラオンライン matsukiyococokara-online.com）商品＋評論爬蟲 — 未來規劃 12-2

這個網站對一般程式連線回 403，所以用電腦上安裝的 Chrome 開「看得到的視窗」去瀏覽。
2026-11-15 使用者評估後同意這樣爬（評論值得抓），並在 .claude/settings.local.json 放行這支程式。
每頁之間停 DELAY 秒，速度放慢，避免造成對方網站負擔。

執行：
  python -m scrapers.matsukiyo_jp_reviews probe        # 先存首頁＋一個商品頁的 HTML 到 reports/，看頁面結構
"""
import argparse
import os
import random
import re
import sys
import time
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BASE = "https://www.matsukiyococokara-online.com"
START = BASE + "/store/"
PROFILE = os.path.join(ROOT, "browser_profiles", "matsukiyo_jp")
REPORTS = os.path.join(ROOT, "reports")
DELAY = (4, 7)   # 每頁之間隨機停 4～7 秒


def pause():
    time.sleep(random.uniform(*DELAY))


def open_browser(pw):
    os.makedirs(PROFILE, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=False, locale="ja-JP", timezone_id="Asia/Tokyo",
        viewport={"width": 1366, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def save(page, name):
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page.content())
    return path


def probe():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx, page = open_browser(pw)
        r = page.goto(START, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        print("首頁", r.status if r else None, page.title())
        print("存檔：", save(page, "mkjp_home.html"))
        links = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        prod = sorted({l for l in links if re.search(r"/store/(item|product|goods|detail|g/)|/store/.*\d{8,}", l)})
        print(f"連結 {len(links)} 個，像商品頁的 {len(prod)} 個：")
        for l in prod[:15]:
            print("  ", l)
        if prod:
            pause()
            r = page.goto(prod[0], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(2500)
            html = page.content()
            print("商品頁", r.status if r else None, page.title())
            print("  レビュー:", html.count("レビュー"), " 口コミ:", html.count("口コミ"),
                  " ratingValue:", html.count("ratingValue"), " reviewCount:", html.count("reviewCount"))
            print("存檔：", save(page, "mkjp_product.html"))
        ctx.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["probe"])
    a = ap.parse_args()
    if a.mode == "probe":
        probe()
