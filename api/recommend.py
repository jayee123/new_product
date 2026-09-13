"""
推薦邏輯：語意搜尋（RAG）+ 硬性條件篩選（預算/國家/分類）+ 評論好評率
"""
import re

import currency
from db.mongo_client import get_db
from rag.embedder import query_products


def _price_twd(price, curr):
    """把原幣別價格換算成台幣，匯率 API 打不通時回傳 None 而不是讓整個請求掛掉"""
    if price is None or price < 0:
        return None
    try:
        return currency.to_twd(price, curr)
    except Exception:
        return None


# 語意搜尋先撈比較多筆，篩選條件（預算/國家/分類）會刷掉一些，才不會篩到不夠 top_k
OVERFETCH_MULTIPLIER = 6

SORT_OPTIONS = ("relevance", "rating", "price_low", "price_high")


def _exact_name_matches(query: str, limit: int, product_type: str = None) -> list[dict]:
    """
    商品名稱子字串比對（不分大小寫，中/日/韓文都比對 name_zh 跟 name_local）。
    語意搜尋（向量相似度）不保證使用者輸入的完整/部分商品名稱一定會排到前面甚至找得到，
    這裡另外做一次直接比對，確保「打商品名稱就一定找得到那個商品」，結果會排在語意搜尋結果之前。
    """
    query = query.strip()
    if not query:
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    mongo_filter = {"$or": [{"name_zh": pattern}, {"name_local": pattern}]}
    if product_type:
        mongo_filter = {"$and": [mongo_filter, {"product_type": product_type}]}
    db = get_db()
    docs = list(db.products.find(mongo_filter).limit(limit))

    output = []
    for p in docs:
        output.append({
            "source_url":            p.get("source_url", ""),
            "name":                  p.get("name_zh") or p.get("name_local", ""),
            "brand":                 p.get("brand_zh") or p.get("brand_local", ""),
            "origin":                "JP" if p.get("currency") == "JPY" else "KR",
            "image_url":             p.get("image_url", ""),
            "price":                 p.get("price") if p.get("price") is not None else -1,
            "currency":              p.get("currency", ""),
            "category":              p.get("category", ""),
            "product_type":          p.get("product_type", ""),
            "source_platform":       p.get("source_platform", ""),
            "rating_platform":       p.get("rating_platform") if p.get("rating_platform") is not None else -1.0,
            "review_count_platform": p.get("review_count_platform") if p.get("review_count_platform") is not None else 0,
            "similarity":            1.0,  # 精確命中，相關度視為滿分，排序會排在語意搜尋結果前面
        })
    return output


def recommend(query: str, budget: int = None, country: str = None,
               product_type: str = None, top_k: int = 10, sort_by: str = "relevance") -> list[dict]:
    """
    query:        使用者需求描述（自然語言），例如「乾性肌保濕精華，預算500元台幣以內」
    budget:       預算上限，**單位是新台幣**（會用即時匯率把 JPY/KRW 換算成 TWD 再比較，
                  不是拿 500 直接去比日圓或韓元原始金額）
    country:      "JP" 或 "KR"，不填代表兩邊都找
    product_type: 統一產品類型（精確比對，例如「精華液」「氣墊」），值來自 GET /product-types。
                  取代舊版「分類關鍵字」子字串比對——舊版直接拿使用者打的字去比對四平台原始、
                  粒度不一致的 category 欄位，很不可靠；product_type 是另外跑分類腳本
                  （scripts/classify_product_types.py）產生的乾淨欄位，前端改成下拉選單，
                  使用者只能選這裡面已經存在的值，不會有比對不到的問題。
    top_k:        回傳幾筆
    sort_by:      "relevance"（預設，語意相關度）/ "rating"（好評率高→低）/
                  "price_low"（價格低→高，依台幣）/ "price_high"（價格高→低，依台幣）
    """
    fetch_limit = top_k * OVERFETCH_MULTIPLIER
    exact_matches = _exact_name_matches(query, limit=fetch_limit, product_type=product_type)
    semantic_matches = query_products(query, top_k=fetch_limit, product_type=product_type)

    seen_urls = {c["source_url"] for c in exact_matches}
    candidates = exact_matches + [c for c in semantic_matches if c["source_url"] not in seen_urls]

    filtered = []
    for c in candidates:
        if country and c.get("origin") != country:
            continue
        price = c.get("price", -1)
        price = price if price is not None and price >= 0 else None
        price_twd = _price_twd(price, c.get("currency"))
        if budget is not None:
            if price_twd is None or price_twd > budget:
                continue
        if product_type:
            if c.get("product_type") != product_type:
                continue
        c["_price_twd"] = price_twd
        filtered.append(c)
        if len(filtered) >= top_k:
            break

    db = get_db()
    results = []
    for c in filtered:
        source_url = c["source_url"]
        pos = db.reviews.count_documents({"product_id": source_url, "sentiment": "positive"})
        neg = db.reviews.count_documents({"product_id": source_url, "sentiment": "negative"})
        sample_reviews = list(db.reviews.find(
            {"product_id": source_url},
            {"_id": 0, "title": 1, "sentiment": 1, "source": 1, "source_url": 1},
        ).limit(3))
        product_doc = db.products.find_one({"source_url": source_url}, {"_id": 0, "ai_summary": 1})
        ai_summary = (product_doc or {}).get("ai_summary")

        price = c.get("price", -1)
        price = price if price is not None and price >= 0 else None
        price_twd = c.get("_price_twd")
        rating = c.get("rating_platform", -1)
        # @cosme 平台是 7 分制（實測 rating_platform 最高到 6.6），其他三個平台都是 5 分制，
        # 統一換算成 5 分制才不會在前端顯示成「5.5 顆星」這種超過 5 顆的怪畫面
        if rating is not None and rating >= 0 and c.get("source_platform") == "cosme":
            rating = round(rating / 7 * 5, 2)
        review_count = c.get("review_count_platform", 0)
        # 好評率＝正評數÷總評論數（企劃書定義的客觀好評率，跟平台自己的星等評分 rating_platform 是兩回事）
        sentiment_pos_rate = round(pos / (pos + neg), 4) if (pos + neg) > 0 else None

        results.append({
            "name": c.get("name", ""),
            "brand": c.get("brand", ""),
            "category": c.get("category", ""),
            "product_type": c.get("product_type", ""),
            "origin": c.get("origin", ""),
            "source_platform": c.get("source_platform", ""),
            "price_twd": price_twd,
            "price_original": price,
            "currency_original": c.get("currency", ""),
            "image_url": c.get("image_url", ""),
            "source_url": source_url,
            "similarity": c.get("similarity"),
            "rating_platform": rating if rating is not None and rating >= 0 else None,
            "review_count_platform": review_count or None,
            "matched_review_count": pos + neg,
            "sentiment_positive": pos,
            "sentiment_negative": neg,
            "sentiment_pos_rate": sentiment_pos_rate,
            "sample_reviews": sample_reviews,
            "ai_summary": ai_summary,
        })

    if sort_by == "rating":
        # 2026-09-13 修正：sentiment_pos_rate（社群評論好評率）是 None 的商品，舊版全部併成同一個
        # sentinel（-1），排序對這批完全沒作用，會維持語意相關度的原始順序——如果使用者搜到的一批
        # 商品剛好全部都沒配對到社群評論（樂天很常見），畫面上看起來就會像「排序是亂的」（例如
        # ★2.4 排在 ★4.6 前面），使用者搞不清楚是排序壞了。
        # 修法：分兩層排序。有 sentiment_pos_rate 的一律排在沒有的前面（社群評論是比較可信的依據），
        # 同一層內部再依「好評率高→低」或「平台星等高→低」排，沒資料時至少不會顯得雜亂無章。
        results.sort(
            key=lambda r: (
                r["sentiment_pos_rate"] is not None,
                r["sentiment_pos_rate"] if r["sentiment_pos_rate"] is not None else 0,
                r["rating_platform"] if r["rating_platform"] is not None else 0,
            ),
            reverse=True,
        )
    elif sort_by == "price_low":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else float("inf"))
    elif sort_by == "price_high":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else -1, reverse=True)
    # sort_by == "relevance"（預設）：維持 ChromaDB 依相似度回傳的順序，不用再排一次

    return results
