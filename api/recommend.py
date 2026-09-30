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

SORT_OPTIONS = ("recommended", "price_low", "price_high")

# ── 綜合推薦（sort_by="recommended"）：硬排序，不用權重（2026-09-29 改，數值還在跟團隊討論）──
# 依序比較，前一個條件一樣才比下一個：
#   1. 有沒有社群評論（有的在前，沒有的一律排最後）
#   2. 好評率等級（A > B > C，見 POS_RATE_GRADES）
#   3. 平台星等（高→低）
#   4. 相關度（高→低）
# 好評率跟相關度都是連續小數幾乎不會同分，直接拿來硬排序等於只有第一個條件有作用，
# 所以好評率先分級，同一級裡面才輪到比星等。
POS_RATE_GRADES = (0.90, 0.80)   # ≥90% A 級、80~90% B 級、<80% C 級
MIN_REVIEWS_FOR_TOP_GRADE = 5    # 評論數不到這個數不能進 A 級（避免「1 則好評＝100%」衝到最前面）
# 綜合推薦要在比 top_k 更大的候選池裡重排，不然只是把最相關的 10 筆換個順序
RERANK_POOL_MULTIPLIER = 3


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
            "_exact":                True,
        })
    return output


def _pos_rate_grade(r: dict) -> int:
    """好評率等級：A=2、B=1、C=0；評論數太少的最高只到 B"""
    rate = r["sentiment_pos_rate"]
    grade = sum(rate >= cut for cut in POS_RATE_GRADES)
    if r["sentiment_positive"] + r["sentiment_negative"] < MIN_REVIEWS_FOR_TOP_GRADE:
        grade = min(grade, len(POS_RATE_GRADES) - 1)
    return grade


def _recommended_sort_key(r: dict) -> tuple:
    has_reviews = r["sentiment_pos_rate"] is not None
    return (
        has_reviews,
        _pos_rate_grade(r) if has_reviews else -1,
        r["rating_platform"] if r["rating_platform"] is not None else -1,
        r["similarity"] if r["similarity"] is not None else -1,
    )


def _rank_recommended(results: list[dict]) -> list[dict]:
    """
    綜合推薦：硬排序（條件順序見檔案開頭 POS_RATE_GRADES 上方的說明）。
    精確命中商品名稱的排在語意搜尋結果前面（使用者就是在找那個商品），
    但一般詞（例如「防曬乳」）也會命中一大堆商品，所以精確命中的這批內部一樣照硬排序排。
    """
    exact = sorted((r for r in results if r["_exact"]), key=_recommended_sort_key, reverse=True)
    rest = sorted((r for r in results if not r["_exact"]), key=_recommended_sort_key, reverse=True)
    return exact + rest


def recommend(query: str, budget: int = None, country: str = None,
               product_type: str = None, top_k: int = 10, sort_by: str = "recommended") -> list[dict]:
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
    sort_by:      "recommended"（預設，綜合推薦：有無評論→好評率等級→星等→相關度 硬排序）/
                  "price_low"（價格低→高，依台幣）/ "price_high"（價格高→低，依台幣）
    """
    pool_size = top_k * RERANK_POOL_MULTIPLIER if sort_by == "recommended" else top_k
    fetch_limit = pool_size * OVERFETCH_MULTIPLIER
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
        if len(filtered) >= pool_size:
            break

    # 所有候選商品的好評/負評數、AI 摘要各用「一次」查詢拿回來，不要每個商品各查一次
    # （候選池是 top_k×3，逐筆查的話雲端 MongoDB 來回次數會很多，搜尋明顯變慢）
    db = get_db()
    urls = [c["source_url"] for c in filtered]
    sentiment_counts = {}
    # 正/負評用 RoBERTa 讀評論文字的結果 sentiment_roberta（scripts/run_roberta_sentiment.py），
    # 還沒跑過模型的評論（例如新爬的）先退回舊的 sentiment（樂天/OliveYoung 是星等 ≥4 換算）
    for row in db.reviews.aggregate([
        {"$match": {"product_id": {"$in": urls}}},
        {"$project": {"product_id": 1, "s": {"$ifNull": ["$sentiment_roberta", "$sentiment"]}}},
        {"$match": {"s": {"$in": ["positive", "negative"]}}},
        {"$group": {"_id": {"p": "$product_id", "s": "$s"}, "n": {"$sum": 1}}},
    ]):
        sentiment_counts[(row["_id"]["p"], row["_id"]["s"])] = row["n"]
    product_docs = {
        d["source_url"]: d
        for d in db.products.find(
            {"source_url": {"$in": urls}},
            {"_id": 0, "source_url": 1, "ai_summary": 1, "complaint_stats": 1},
        )
    }

    results = []
    for c in filtered:
        source_url = c["source_url"]
        pos = sentiment_counts.get((source_url, "positive"), 0)
        neg = sentiment_counts.get((source_url, "negative"), 0)
        product_doc = product_docs.get(source_url, {})
        ai_summary = product_doc.get("ai_summary")
        complaint_stats = product_doc.get("complaint_stats")

        price = c.get("price", -1)
        price = price if price is not None and price >= 0 else None
        price_twd = c.get("_price_twd")
        rating = c.get("rating_platform", -1)
        # @cosme 平台是 7 分制（實測 rating_platform 最高到 6.6），其他三個平台都是 5 分制，
        # 統一換算成 5 分制才不會在前端顯示成「5.5 顆星」這種超過 5 顆的怪畫面
        if rating is not None and rating >= 0 and c.get("source_platform") == "cosme":
            rating = round(rating / 7 * 5, 2)
        review_count = c.get("review_count_platform", 0)
        # 好評率＝正評數÷總評論數（正/負由 RoBERTa 讀評論文字判斷，中立算負評；跟平台星等 rating_platform 是兩回事）
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
            "ai_summary": ai_summary,
            "complaint_stats": complaint_stats,
            "_exact": c.get("_exact", False),
        })

    if sort_by == "recommended":
        results = _rank_recommended(results)[:top_k]
    elif sort_by == "price_low":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else float("inf"))
    elif sort_by == "price_high":
        results.sort(key=lambda r: r["price_twd"] if r["price_twd"] is not None else -1, reverse=True)

    for r in results:
        r.pop("_exact", None)
    return results
