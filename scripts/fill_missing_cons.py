"""
補缺點統整（對應組員「待改善.docx」第 4 點「有負評但沒有統整」）：

原本的「常見缺點」要同一個缺點被 ≥2 位評論者提到才列（scripts/build_cons_summaries.py 的 MIN_MENTIONS），
所以「有負評、但每個缺點都只有 1 人提到」的商品完全沒有缺點摘要。這支只補這種商品，已經有缺點摘要的不動：

  1. 有負評（sentiment_roberta）但沒有 ai_summary.cons 的商品
  2. 該商品還沒抽過抱怨面向的評論先抽（extract_review_aspects）
  3. 用「1 人提到也算」重新統計（complaint_stats.min_mentions = 1），有面向就請 AI 寫缺點摘要
     （同一套 make_cons：AI 寫 → 程式檢查有沒有幻覺 → 兩次沒過用固定句型）
  4. 還是統計不出具體面向（例如抱怨被歸在「其他」）→ 請 AI 直接讀那幾則負評寫一句缺點（cons_source="neg_reviews"）

前端標題：最多只有 1 人提到的缺點顯示「少數使用者提到」，不會誇大成「常見缺點」。

可以中斷重跑（已經有 cons 的會跳過）。執行：python -m scripts.fill_missing_cons [--limit N]
"""
import json
import sys
import time
from datetime import datetime, timezone

from pymongo import UpdateOne

import scripts.build_cons_summaries as bcs
from ai.gemini import ask_json, extract_review_aspects
from db.mongo_client import get_db


def products_to_fill(db) -> list:
    neg = {r["_id"] for r in db.reviews.aggregate([
        {"$match": {"product_id": {"$ne": None}}},
        {"$project": {"product_id": 1, "s": {"$ifNull": ["$sentiment_roberta", "$sentiment"]}}},
        {"$match": {"s": "negative"}},
        {"$group": {"_id": "$product_id"}},
    ])}
    have = {p["source_url"] for p in db.products.find(
        {"ai_summary.cons": {"$nin": [None, ""]}}, {"source_url": 1})}
    return sorted(neg - have)


def cons_from_negative_reviews(name: str, texts: list) -> str:
    prompt = (
        f"以下是商品「{name}」的幾則負面評論原文（可能是日文或韓文）。\n"
        "請用台灣繁體中文寫 1 句缺點摘要（30 字內），只根據評論內容，不要加評論沒提到的東西。"
        "如果這些評論其實沒有具體說出缺點（例如只是給低分、或在講物流以外的無關事情），cons 回傳空字串。\n"
        '只回傳 JSON：{"cons": "..."}\n\n' + json.dumps(texts, ensure_ascii=False))
    out = ask_json(prompt)
    return (out.get("cons") or "").strip() if isinstance(out, dict) else ""


def fill_one(db, url: str) -> str:
    p = db.products.find_one({"source_url": url}, {"name_zh": 1, "name_local": 1, "brand_zh": 1,
                                                   "brand_local": 1, "ai_summary": 1})
    if not p:
        return "no_product"
    name = p.get("name_zh") or p.get("name_local") or ""
    brand = p.get("brand_zh") or p.get("brand_local") or ""
    reviews = list(db.reviews.find(
        {"product_id": url, "raw_text": {"$nin": [None, ""]}},
        {"raw_text": 1, "title": 1, "helpful_count": 1, "source": 1, "rating": 1,
         "sentiment_text": 1, "complaints": 1, "sentiment_roberta": 1, "sentiment": 1}))
    reviews.sort(key=lambda r: -(r.get("helpful_count") or 0))
    negatives = [r for r in reviews if (r.get("sentiment_roberta") or r.get("sentiment")) == "negative"]
    # 負評一定要納入（原本只取最有幫助的 60 則，負評可能剛好被排除）
    pool = reviews[:bcs.MAX_REVIEWS_PER_PRODUCT]
    pool += [r for r in negatives if r not in pool]

    todo = [r for r in pool if not r.get("sentiment_text")]
    for i in range(0, len(todo), bcs.BATCH):
        chunk = todo[i:i + bcs.BATCH]
        results = extract_review_aspects([r["raw_text"] for r in chunk])
        ops = []
        for r, res in zip(chunk, results):
            if res is None:
                continue
            r["sentiment_text"], r["complaints"] = res["sentiment"], res["complaints"]
            ops.append(UpdateOne({"_id": r["_id"]}, {"$set": {"sentiment_text": res["sentiment"],
                                                              "complaints": res["complaints"]}}))
        if ops:
            db.reviews.bulk_write(ops, ordered=False)

    bcs.MIN_MENTIONS = 1
    stats = bcs.aggregate(pool)
    if stats["aspects"]:
        cons, source = bcs.make_cons(name, brand, stats)
    else:
        texts = [r["raw_text"][:300] for r in negatives[:5]]
        cons, source = (cons_from_negative_reviews(name, texts), "neg_reviews") if texts else ("", None)
    if not cons:
        return "no_cons"

    now = datetime.now(timezone.utc).isoformat()
    summary = p.get("ai_summary") or {}
    db.products.update_one({"source_url": url}, {"$set": {
        "complaint_stats": {**stats, "min_mentions": 1, "generated_at": now},
        "ai_summary": {**summary, "cons": cons, "cons_source": source, "cons_generated_at": now},
    }})
    return source


def main(limit=None):
    db = get_db()
    urls = products_to_fill(db)
    if limit:
        urls = urls[:limit]
    print(f"[補缺點] 有負評但沒有缺點摘要：{len(urls)} 個商品", flush=True)
    counts = {}
    for i, url in enumerate(urls, 1):
        try:
            r = fill_one(db, url)
        except Exception as e:
            r = "failed"
            print(f"  失敗：{str(e)[:120]}", flush=True)
        counts[r] = counts.get(r, 0) + 1
        if i % 10 == 0 or i == len(urls):
            print(f"  {i}/{len(urls)} {counts}", flush=True)
        time.sleep(0.5)
    print(f"[補缺點] 完成 {counts}", flush=True)


if __name__ == "__main__":
    lim = next((int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")), None)
    main(lim)
