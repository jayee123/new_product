"""
把每個「有配對到評論」的商品，用 AI 生成一段評論摘要 + 建議適合族群，
存回 products.ai_summary。批次預先生成，不是每次 /recommend 都即時呼叫。

**這是一個持續性流程，不是做一次就結束**：只要有新的評論被爬進來、配對到商品
（不管是 PTT/Dcard 配對，還是樂天/Olive Young 評論爬蟲直接寫入），這支腳本都要
重新跑一次，才能讓新配對到評論的商品也有摘要可以顯示。每次爬完一批評論，
記得回來跑這支腳本補上摘要。

2026-09-22（new_product-prj 副本）：改用 ai/gemini.py 的 summarize_reviews()。Gemini
免費額度下沒有計費，BUDGET_CAP_USD 這組介面保留但實際上不會被撞到，真正的限制是
429 速率限制（ai/gemini.py 的 _call() 已處理）。

執行：python -m scripts.generate_review_summaries
可以安全重跑：已經有 ai_summary 的商品會自動跳過，不會重複呼叫。
"""
import sys
import time
from datetime import datetime, timezone

from ai.gemini import summarize_reviews, GeminiError, BudgetExceeded, get_usage_summary
from db.mongo_client import get_db


def run():
    db = get_db()
    product_ids = db.reviews.distinct("product_id", {"product_id": {"$ne": None}})
    already_done = set(db.products.distinct(
        "source_url", {"source_url": {"$in": product_ids}, "ai_summary": {"$ne": None}}
    ))
    todo = [p for p in product_ids if p not in already_done]
    print(f"有配對到評論的商品數：{len(product_ids)}，已經有摘要跳過：{len(already_done)}，這次要處理：{len(todo)}")

    done = 0
    failed = 0
    stopped_early = False
    for i, source_url in enumerate(todo, 1):
        product = db.products.find_one(
            {"source_url": source_url},
            {"_id": 0, "name_zh": 1, "name_local": 1, "brand_zh": 1, "brand_local": 1},
        )
        if not product:
            continue
        name = product.get("name_zh") or product.get("name_local") or ""
        brand = product.get("brand_zh") or product.get("brand_local") or ""

        reviews = list(db.reviews.find(
            {"product_id": source_url},
            {"_id": 0, "title": 1, "raw_text": 1, "sentiment": 1},
        ).limit(15))  # 評論很多的商品（樂天有的上千篇）只取前 15 篇就夠摘要用，不用全部塞進 prompt

        print(f"[{i}/{len(todo)}] {name[:30]}（{len(reviews)} 篇評論）...")
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
        except BudgetExceeded as e:
            print(f"  [預算上限] {e}")
            stopped_early = True
            break
        except GeminiError as e:
            print(f"    [失敗] {e}")
            failed += 1
        time.sleep(1.0)

    usage = get_usage_summary()
    print(f"\n完成：成功 {done} 筆，失敗 {failed} 筆"
          f"{'（因預算上限提前停止，剩下的下次重跑會自動接續）' if stopped_early else ''}")
    print(f"本次花費：US${usage['total_cost_usd']:.4f}")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    run()
