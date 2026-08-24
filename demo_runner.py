"""
Demo 一鍵執行腳本
資料庫現況 → 情緒分析（未分析的） → RAG 向量索引 → 查詢測試 → 評論配對

商品資料來源是 Rakuten / Olive Young / @cosme / 화해，評論來源是 PTT / Dcard，
爬蟲本身需要 API key 或手動登入瀏覽器，不適合塞進一鍵腳本，
所以這裡預設「資料已經在 MongoDB 裡」，只跑後半段的分析/索引/推薦流程。

執行方式：
  python demo_runner.py
  python demo_runner.py --with-image-test   # 額外跑 AI 圖片幻覺驗證（會呼叫 OpenAI API，花錢）
"""
import sys
import argparse

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def count_summary():
    try:
        from db.mongo_client import count_summary as _count
        return _count()
    except Exception:
        return {"products": "N/A (MongoDB 未啟動)", "reviews": "N/A"}


def print_step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f" Step {n}：{title}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-image-test", action="store_true",
                         help="額外跑 AI 圖片 URL 幻覺驗證（呼叫 OpenAI API）")
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  日韓藥妝推薦系統 Demo 驗證")
    print("=" * 50)

    # ── Step 1：資料庫現況 ────────────────────────────────
    print_step(1, "資料庫現況（Rakuten / Olive Young / @cosme / 화해 / PTT / Dcard）")
    from db.mongo_client import get_db
    db = get_db()
    print(f"  products 總數：{db.products.count_documents({})}")
    for platform in db.products.distinct("source_platform"):
        print(f"    {platform}：{db.products.count_documents({'source_platform': platform})}")
    print(f"  reviews 總數：{db.reviews.count_documents({})}")
    for source in db.reviews.distinct("source"):
        print(f"    {source}：{db.reviews.count_documents({'source': source})}")

    # ── Step 2：情緒分析（只處理尚未分析的） ──────────────
    print_step(2, "情緒分析（CPU 跑，首次需下載模型 ~400MB）")
    try:
        from nlp.sentiment import run_batch
        run_batch(limit=500)
    except Exception as e:
        print(f"  [情緒分析錯誤] {e}")

    # ── Step 3：RAG 向量化 ───────────────────────────────
    print_step(3, "RAG 向量化（首次需下載嵌入模型 ~120MB）")
    try:
        from rag.embedder import build_product_index, query_products, match_reviews_to_products

        print("\n--- 建立商品向量索引 ---")
        build_product_index()

        print("\n--- 測試使用者查詢 ---")
        test_queries = [
            "乾性肌保濕精華，預算500以內",
            "敏感肌適用防曬，不留白",
            "韓國修護精華",
        ]
        for q in test_queries:
            print(f"\n查詢：「{q}」")
            results = query_products(q, top_k=3)
            if results:
                for r in results:
                    print(f"   [{r['similarity']}] {r['name']} ({r['origin']}) {r['price']} {r['currency']}")
            else:
                print("   （無結果，可能商品數量不足）")

        print("\n--- 評論 ↔ 商品配對 ---")
        match_reviews_to_products(batch_size=200, threshold=0.5)

    except Exception as e:
        print(f"  [RAG 錯誤] {e}")
        print("  → 確認已安裝 chromadb 和 sentence-transformers")

    # ── Step 4（選用）：AI 圖片幻覺驗證 ─────────────────
    if args.with_image_test:
        print_step(4, "AI 圖片 URL 驗證（GPT-4o 能給正確圖片連結嗎？）")
        from ai_image.test_image_url import run as test_image
        test_image()

    # ── 最終摘要 ─────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Demo 執行完成！")
    print("=" * 60)
    summary = count_summary()
    print(f"  資料庫商品數：{summary['products']}")
    print(f"  資料庫評論數：{summary['reviews']}")
    print()
    print("  下一步：")
    print("  1. 確認情緒分析好評率是否合理")
    print("  2. 確認 RAG 查詢/評論配對準確度")
    print("  3. 結果 OK → 可以向老師展示這份 Demo 驗證")
    print()


if __name__ == "__main__":
    main()
