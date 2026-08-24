"""
把每個「有配對到評論」的商品，用 Gemini 生成一段評論摘要 + 建議適合族群，
存回 products.ai_summary。批次預先生成，不是每次 /recommend 都即時呼叫。

執行：python -m scripts.generate_review_summaries
"""
import sys
import time
from datetime import datetime, timezone

from ai.gemini import summarize_reviews, GeminiError
from db.mongo_client import get_db


def run():
    db = get_db()
    product_ids = db.reviews.distinct("product_id", {"product_id": {"$ne": None}})
    print(f"有配對到評論的商品數：{len(product_ids)}")

    done = 0
    failed = 0
    for i, source_url in enumerate(product_ids, 1):
        product = db.products.find_one({"source_url": source_url}, {"_id": 0, "name_zh": 1, "name_local": 1, "brand_zh": 1, "brand_local": 1})
        if not product:
            continue
        name = product.get("name_zh") or product.get("name_local") or ""
        brand = product.get("brand_zh") or product.get("brand_local") or ""

        reviews = list(db.reviews.find(
            {"product_id": source_url},
            {"_id": 0, "title": 1, "raw_text": 1, "sentiment": 1},
        ))

        print(f"[{i}/{len(product_ids)}] {name[:30]}（{len(reviews)} 篇評論）...")
        try:
            result = summarize_reviews(name, brand, reviews)
            db.products.update_one(
                {"source_url": source_url},
                {"$set": {"ai_summary": {
                    "summary": result["summary"],
                    "suggested_for": result["suggested_for"],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }}},
            )
            done += 1
        except GeminiError as e:
            print(f"    [失敗] {e}")
            failed += 1
        time.sleep(1.0)

    print(f"\n完成：成功 {done} 筆，失敗 {failed} 筆")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    run()
