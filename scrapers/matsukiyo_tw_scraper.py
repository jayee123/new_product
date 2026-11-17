"""
台灣松本清官網（matsumotokiyoshi-tw.com，Wix 商店）商品爬蟲 — 未來規劃 12-2

- 商品清單：store-products-sitemap.xml（robots.txt 允許，Allow: /）
- 商品資料：每個商品頁裡的 JSON-LD（schema.org Product：品名、品牌、台幣售價、圖片、說明）
- 評論：網站沒有評論功能，只抓商品

每頁之間停 DELAY 秒，避免造成對方網站負擔。

執行：
  python -m scrapers.matsukiyo_tw_scraper --limit 5 --dry-run   # 先試 5 筆，不寫資料庫
  python -m scrapers.matsukiyo_tw_scraper                        # 全部爬完寫進 MongoDB
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import unquote

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.product_schema import PRODUCT_FIELDS, normalize_matsukiyo

BASE = "https://www.matsumotokiyoshi-tw.com"
SITEMAP = BASE + "/store-products-sitemap.xml"
DELAY = 1.5
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
LD_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def product_urls(session: requests.Session) -> list[str]:
    xml = session.get(SITEMAP, timeout=30).text
    return [unquote(u) for u in re.findall(r"<loc>([^<]+/product-page/[^<]+)</loc>", xml)]


def parse_product(html: str) -> dict | None:
    for block in LD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item
    return None


def run(limit: int = None, dry_run: bool = False, csv_path: str = None) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)
    urls = product_urls(session)
    if limit:
        urls = urls[:limit]
    print(f"[松本清台灣] sitemap 共 {len(urls)} 個商品頁", flush=True)

    save_product = None
    if not dry_run:
        from db.mongo_client import save_product

    items, failed = [], []
    for i, url in enumerate(urls, 1):
        try:
            r = session.get(url, timeout=40)
            r.raise_for_status()
            ld = parse_product(r.text)
            if not ld:
                failed.append((url, "no JSON-LD"))
                continue
            item = normalize_matsukiyo(ld, url)
            if save_product:
                save_product(item)
            items.append(item)
            if i % 25 == 0 or i == len(urls):
                print(f"  {i}/{len(urls)}  {item['name_zh'][:30]}  NT${item['price']}", flush=True)
        except Exception as e:  # 單頁失敗不影響其他頁
            failed.append((url, str(e)[:100]))
        time.sleep(DELAY)

    if csv_path:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=PRODUCT_FIELDS, extrasaction="ignore")
            w.writeheader()
            for it in items:
                w.writerow({**it, "ingredients": ",".join(it["ingredients"])})
        print(f"已輸出 CSV：{csv_path}")

    print(f"[松本清台灣] 成功 {len(items)} 筆、失敗 {len(failed)} 筆"
          f"{'（dry-run，沒寫資料庫）' if dry_run else '，已寫入 MongoDB products'}")
    for url, err in failed[:10]:
        print("  失敗：", url, err)
    return items


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--csv")
    a = ap.parse_args()
    run(limit=a.limit, dry_run=a.dry_run, csv_path=a.csv)
