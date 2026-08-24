"""
Hwahae 商品匯入腳本。

執行：
  python -m scrapers.hwahae_scraper --csv ../hwahae_scraper/hwahae_20260605_152727.csv
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scrapers.product_schema import normalize_hwahae


def run_from_csv(csv_path: str, limit: int = None) -> list[dict]:
    from db.mongo_client import save_product

    items = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            item = normalize_hwahae(row)
            if not item["source_url"]:
                continue
            save_product(item)
            items.append(item)

    print(f"[Hwahae] 從 CSV 匯入 {len(items)} 筆商品：{csv_path}")
    return items


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=str, required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    run_from_csv(args.csv, limit=args.limit)
