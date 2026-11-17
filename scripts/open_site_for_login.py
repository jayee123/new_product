"""
打開「有畫面」的瀏覽器讓組員手動註冊／登入藥妝網站（未來規劃 12-2）。

登入狀態（cookie 等）存在 browser_profiles/<網站>/，之後的爬蟲用同一個資料夾
（launch_persistent_context）就會沿用登入狀態。這個資料夾含帳號 cookie，不進 git。

執行：
  python -m scripts.open_site_for_login sundrug
  python -m scripts.open_site_for_login --list
註冊／登入完，把瀏覽器視窗整個關掉就會存檔結束。
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_DIR = os.path.join(ROOT, "browser_profiles")

# key: (顯示名稱, 網址, locale, 時區)
SITES = {
    "sundrug":   ("SUNDRUG",      "https://sundrug-online.com/",             "ja-JP", "Asia/Tokyo"),
    "chicor":    ("Chicor",       "https://chicor.com/main",                 "ko-KR", "Asia/Seoul"),
    "tonymoly":  ("TONYMOLY",     "https://tonymoly.com/",                   "ko-KR", "Asia/Seoul"),
    "innisfree": ("Innisfree",    "https://www.innisfree.com/kr/ko/",        "ko-KR", "Asia/Seoul"),
    "matsukiyo": ("松本清（台）", "https://www.matsumotokiyoshi-tw.com/",    "zh-TW", "Asia/Taipei"),
    "daikoku":   ("大國藥妝",     "https://www.dkglobal-daikokudrug.com/",   "ja-JP", "Asia/Tokyo"),
    "welcia":    ("Welcia",       "https://www.e-welcia.com/",               "ja-JP", "Asia/Tokyo"),
    "osdrug":    ("OS DRUG",      "http://www.osdrug.com/",                  "ja-JP", "Asia/Tokyo"),
}


def open_site(key: str):
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    name, url, locale, tz = SITES[key]
    profile = os.path.join(PROFILE_DIR, key)
    os.makedirs(profile, exist_ok=True)
    print(f"[{name}] 開啟 {url}\n  設定檔：{profile}\n  註冊／登入完把瀏覽器關掉就好。", flush=True)

    with sync_playwright() as pw:
        # 用電腦上安裝的 Chrome（有簽章）；Playwright 自帶的 Chromium 會被
        # Windows「智慧型應用程式控制」擋掉
        ctx = pw.chromium.launch_persistent_context(
            profile, channel="chrome", headless=False, locale=locale, timezone_id=tz,
            viewport=None, args=["--disable-blink-features=AutomationControlled",
                                 "--start-maximized"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        Stealth().apply_stealth_sync(page)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # 等使用者把所有分頁都關掉（或直接關整個瀏覽器）
        try:
            while ctx.pages:
                ctx.pages[0].wait_for_event("close", timeout=0)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print(f"[{name}] 瀏覽器已關閉，登入狀態已存好。", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("site", nargs="?", choices=list(SITES))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.site:
        for k, (n, u, *_ ) in SITES.items():
            print(f"{k:10s} {n}  {u}")
        sys.exit(0)
    open_site(a.site)
