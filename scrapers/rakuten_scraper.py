"""
Rakuten Ichiba 商品爬蟲 — 接上 MongoDB（Data: products）

實際的 API 呼叫邏輯在頂層 rakuten_scraper/scraper.py（獨立 CSV 版本），
這裡只負責：呼叫它 或 讀它輸出的 CSV，轉成統一欄位（product_schema.py）後寫進 Mongo。

執行：
  python -m scrapers.rakuten_scraper --csv ../rakuten_scraper/rakuten_20260605_155639.csv
  python -m scrapers.rakuten_scraper --live
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.product_schema import normalize_rakuten

TOP_LEVEL_SCRAPER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "rakuten_scraper",
)


def run_from_csv(csv_path: str, limit: int = None) -> list[dict]:
    """讀取既有的 Rakuten CSV，轉成統一欄位後寫入 products collection"""
    from db.mongo_client import save_product

    items = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            item = normalize_rakuten(row)
            if not item["source_url"]:
                continue
            save_product(item)
            items.append(item)

    print(f"[Rakuten] 從 CSV 匯入 {len(items)} 筆商品：{csv_path}")
    return items


def run_from_api(hits: int = 30, pages: int = 1, keywords: list[str] = None,
                  limit: int = None) -> list[dict]:
    """直接呼叫 Rakuten API 即時抓取，轉成統一欄位後寫入 products collection"""
    from db.mongo_client import save_product
    from rakuten_scraper import scraper as rakuten_raw

    if not rakuten_raw.APP_ID or not rakuten_raw.ACCESS_KEY:
        print("[Rakuten] 找不到 RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY，"
              f"請在 {TOP_LEVEL_SCRAPER_DIR} 的上層放 .env（見 rakuten_scraper/scraper.py 開頭說明）")
        return []

    items = []
    for kw in (keywords or rakuten_raw.KEYWORDS):
        raw_rows = rakuten_raw.fetch_items(kw, hits=hits, pages=pages)
        for row in raw_rows:
            if limit and len(items) >= limit:
                break
            item = normalize_rakuten(row)
            if not item["source_url"]:
                continue
            save_product(item)
            items.append(item)
        if limit and len(items) >= limit:
            break

    print(f"[Rakuten] 即時抓取並寫入 {len(items)} 筆商品")
    return items


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=str, help="讀取既有 CSV 匯入（不重新爬）")
    p.add_argument("--live", action="store_true", help="即時呼叫 Rakuten API")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    if args.csv:
        run_from_csv(args.csv, limit=args.limit)
    elif args.live:
        run_from_api(limit=args.limit)
    else:
        print("請指定 --csv <path> 或 --live")
