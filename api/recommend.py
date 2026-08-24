"""
推薦邏輯：語意搜尋（RAG）+ 硬性條件篩選（預算/國家/分類）+ 評論好評率
"""
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


def recommend(query: str, budget: int = None, country: str = None,
               category: str = None, top_k: int = 10, sort_by: str = "relevance") -> list[dict]:
    """
    query:    使用者需求描述（自然語言），例如「乾性肌保濕精華，預算500元台幣以內」
    budget:   預算上限，**單位是新台幣**（會用即時匯率把 JPY/KRW 換算成 TWD 再比較，
              不是拿 500 直接去比日圓或韓元原始金額）
    country:  "JP" 或 "KR"，不填代表兩邊都找
    category: 分類關鍵字（子字串比對，例如「防曬」「精華」）
    top_k:    回傳幾筆
    sort_by:  "relevance"（預設，語意相關度）/ "rating"（好評率高→低）/
              "price_low"（價格低→高，依台幣）/ "price_high"（價格高→低，依台幣）
    """
    candidates = query_products(query, top_k=top_k * OVERFETCH_MULTIPLIER)

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
        if category:
            if category not in (c.get("category") or ""):
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
        review_count = c.get("review_count_platform", 0)
        # 好評率＝正評數÷總評論數（企劃書定義的客觀好評率，跟平台自己的星等評分 rating_platform 是兩回事）
        sentiment_pos_rate = round(pos / (pos + neg), 4) if (pos + neg) > 0 else None

        results.append({
            "name": c.get("name", ""),
            "brand": c.get("brand", ""),
            "category": c.get("category", ""),
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
        # 沒有評論資料的（None）排最後，不要讓沒資料的因為 "沒負評" 而排到最前面
        results.sort(key=lambda r: r["sentiment_pos_rate"] if r["sentiment_pos_rate"] is not None else -1,
                     reverse=True)
    elif sort_by == "price_low":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else float("inf"))
    elif sort_by == "price_high":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else -1, reverse=True)
    # sort_by == "relevance"（預設）：維持 ChromaDB 依相似度回傳的順序，不用再排一次

    return results
