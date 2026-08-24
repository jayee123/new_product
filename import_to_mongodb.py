import csv
import os
import sys
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

ROOT = Path(__file__).resolve().parent
INPUT_CSV = ROOT / ".." / "combined_cleaned.csv"
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "drugstore_demo")


def normalize_product_from_row(row: Dict[str, str]) -> Dict[str, object]:
    name_zh = row.get("商品名(中)") or row.get("商品名") or row.get("title") or row.get("商品名(日)") or ""
    brand_zh = row.get("品牌(中)") or row.get("品牌") or row.get("brand") or row.get("品牌(日)") or ""
    category = row.get("大分類") or row.get("大分類(中)") or row.get("category") or row.get("分類") or ""
    price_text = row.get("價格") or row.get("KRW售價") or row.get("JPY 售價") or row.get("price") or ""
    rating_text = row.get("評分") or row.get("平均評分") or row.get("rating") or ""
    review_text = row.get("口コミ數") or row.get("評論數") or row.get("review_count") or row.get("comment_count") or ""
    url = row.get("商品連結") or row.get("商品URL") or row.get("source_url") or row.get("商品URL") or ""

    def parse_num(text: str):
        digits = "".join(ch for ch in str(text) if ch.isdigit() or ch in ".-")
        if not digits:
            return None
        try:
            return float(digits)
        except ValueError:
            return None

    def safe_int(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            if value > 2**31 - 1:
                return str(int(value))
            return int(value)
        try:
            parsed = int(float(value))
            if parsed > 2**31 - 1:
                return str(parsed)
            return parsed
        except (TypeError, ValueError):
            return None

    return {
        "source_platform": "mixed",
        "source_id": row.get("商品ID") or row.get("goods_no") or row.get("rakuten_id") or "",
        "source_url": url,
        "name_local": row.get("商品名(日)") or row.get("商品名(韓)") or row.get("商品名") or "",
        "name_zh": name_zh,
        "brand_local": row.get("品牌(日)") or row.get("品牌(韓)") or row.get("品牌") or "",
        "brand_zh": brand_zh,
        "category": category,
        "price": safe_int(parse_num(price_text)),
        "currency": "KRW" if "KRW" in str(price_text) or "KRW" in str(row) else "JPY",
        "image_url": row.get("圖片") or row.get("圖片URL") or "",
        "description": row.get("商品說明") or row.get("說明") or "",
        "ingredients": [],
        "rating_platform": parse_num(rating_text),
        "review_count_platform": safe_int(review_text),
        "capacity": row.get("容量") or "",
        "scraped_at": None,
    }


def import_csv_to_mongodb(csv_path: Path, uri: str, db_name: str) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到 CSV: {csv_path}")
    if not uri:
        raise ValueError("MONGO_URI 未設定")

    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    db = client[db_name]
    collection = db["products"]

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    inserted = 0
    for row in rows:
        product = normalize_product_from_row(row)
        if not product["name_zh"] and not product["source_url"]:
            continue
        collection.update_one(
            {"source_url": product["source_url"] or product["name_zh"]},
            {"$set": product},
            upsert=True,
        )
        inserted += 1

    print(f"Imported {inserted} documents into {db_name}.products")
    return inserted


def main() -> int:
    try:
        count = import_csv_to_mongodb(INPUT_CSV, MONGO_URI, MONGO_DB)
    except Exception as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
