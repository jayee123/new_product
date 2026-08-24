"""
Olive Young 商品爬蟲 — 接上 MongoDB（Data: products）

實際的 Playwright 爬蟲邏輯在頂層 olive_young_scraper/scraper.py（獨立 CSV 版本，
含詳細頁評分/評論數/成分表擷取），這裡只負責：呼叫它 或 讀它輸出的 CSV，
轉成統一欄位（product_schema.py）後寫進 Mongo。

執行：
  python -m scrapers.oliveyoung_scraper --csv ../olive_young_scraper/olive_young_20260605_111948.csv
  python -m scrapers.oliveyoung_scraper --live --pages 1
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.product_schema import normalize_oliveyoung


def run_from_csv(csv_path: str, limit: int = None) -> list[dict]:
    """讀取既有的 Olive Young CSV，轉成統一欄位後寫入 products collection"""
    from db.mongo_client import save_product

    items = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            item = normalize_oliveyoung(row)
            if not item["source_url"]:
                continue
            save_product(item)
            items.append(item)

    print(f"[Olive Young] 從 CSV 匯入 {len(items)} 筆商品：{csv_path}")
    return items


def run_from_scrape(pages_per_cat: int = 1, headless: bool = True,
                     fetch_detail: bool = True, detail_limit: int = None,
                     limit: int = None) -> list[dict]:
    """即時跑 Playwright 爬蟲（含詳細頁），轉成統一欄位後寫入 products collection"""
    from db.mongo_client import save_product
    from olive_young_scraper import scraper as oy_raw
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    all_rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            locale="ko-KR", timezone_id="Asia/Seoul",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        page = ctx.new_page()
        Stealth().apply_stealth_sync(page)

        page.goto("https://www.oliveyoung.co.kr/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
        for sel in ["button.btn-close", ".layer-popup .ico-close", ".pop-close", "button.close"]:
            try:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        for cat_no, cat_ko, cat_zh in oy_raw.CATEGORIES:
            rows = oy_raw.scrape_category(page, cat_no, cat_ko, cat_zh, pages=pages_per_cat)
            all_rows.extend(rows)
            if limit and len(all_rows) >= limit:
                all_rows = all_rows[:limit]
                break

        if fetch_detail:
            oy_raw.enrich_with_detail(page, all_rows, limit=detail_limit)

        browser.close()

    items = []
    for row in all_rows:
        item = normalize_oliveyoung(row)
        if not item["source_url"]:
            continue
        save_product(item)
        items.append(item)

    print(f"[Olive Young] 即時抓取並寫入 {len(items)} 筆商品")
    return items


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=str, help="讀取既有 CSV 匯入（不重新爬）")
    p.add_argument("--live", action="store_true", help="即時跑 Playwright 爬蟲")
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--no-detail", action="store_true", help="即時模式下跳過詳細頁")
    p.add_argument("--show", action="store_true", help="有視窗模式（headless 容易被 Cloudflare 擋）")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    if args.csv:
        run_from_csv(args.csv, limit=args.limit)
    elif args.live:
        run_from_scrape(pages_per_cat=args.pages, headless=not args.show,
                         fetch_detail=not args.no_detail, limit=args.limit)
    else:
        print("請指定 --csv <path> 或 --live")
