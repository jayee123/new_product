"""
用多語言 XLM-RoBERTa（nlp/sentiment.py 的 analyze_batch_multilingual）讀每則評論原文判斷正/負評，寫回 reviews：
  sentiment_roberta_raw：模型原始三分類 positive / neutral / negative
  sentiment_roberta：    二元結果，neutral 算負評（見 nlp/sentiment.py 的 to_binary）
/recommend 的好評率、綜合推薦用的是 sentiment_roberta。

只跑日韓文來源（樂天、OliveYoung）。PTT/Dcard 是中文長篇文章，這個模型（用短推文訓練）
實測幾乎全判成中立，所以 PTT/Dcard 沿用原本中文 RoBERTa（uer/roberta-base-finetuned-jd-binary-chinese）
算好的 sentiment，直接複製到 sentiment_roberta（sentiment_roberta_raw 記成 "zh_model"）。

原本的 sentiment 欄位（樂天/OliveYoung 是用星等 ≥4 換算）不覆蓋，要比對或換回來都可以。
想改中立的算法不用重跑模型，直接用 sentiment_roberta_raw 重算 sentiment_roberta 就好。

**可以安全中斷、重跑**：已經有 sentiment_roberta_raw 的評論會跳過。
CPU 約每秒 25 則，全部 4.7 萬則約 30 分鐘。

執行：python -m scripts.run_roberta_sentiment [--limit N]
"""
import argparse
import time

from pymongo import UpdateOne

from db.mongo_client import get_db
from nlp.sentiment import analyze_batch_multilingual, get_multilingual_pipeline

CHUNK = 256
MULTILINGUAL_SOURCES = ["rakuten", "oliveyoung"]
ZH_SOURCES = ["ptt", "dcard"]


def main(limit: int = None):
    db = get_db()

    # PTT/Dcard：沿用中文模型結果（包含之前試跑時被多語言模型蓋掉的也一併改回來）
    zh = list(db.reviews.find({"source": {"$in": ZH_SOURCES}}, {"_id": 1, "sentiment": 1}))
    if zh:
        db.reviews.bulk_write([
            UpdateOne({"_id": d["_id"]}, {"$set": {
                "sentiment_roberta_raw": "zh_model",
                "sentiment_roberta": d.get("sentiment"),
            }})
            for d in zh
        ], ordered=False)
        print(f"[RoBERTa] PTT/Dcard {len(zh)} 則沿用中文模型結果", flush=True)

    todo_filter = {"source": {"$in": MULTILINGUAL_SOURCES}, "sentiment_roberta_raw": {"$exists": False}}
    total = db.reviews.count_documents(todo_filter)
    if limit:
        total = min(total, limit)
    print(f"[RoBERTa] 待分析 {total} 則", flush=True)

    get_multilingual_pipeline()  # 先載入模型，速度統計才不會把載入時間算進去
    done = 0
    start = time.time()
    while done < total:
        n = min(CHUNK, total - done)
        docs = list(db.reviews.find(todo_filter, {"_id": 1, "raw_text": 1}).limit(n))
        if not docs:
            break
        results = analyze_batch_multilingual([d.get("raw_text", "") for d in docs])
        db.reviews.bulk_write([
            UpdateOne({"_id": d["_id"]}, {"$set": {
                "sentiment_roberta_raw": r["label"],
                "sentiment_roberta": r["sentiment"],
            }})
            for d, r in zip(docs, results)
        ], ordered=False)
        done += len(docs)
        rate = done / (time.time() - start)
        print(f"  {done}/{total}（{rate:.0f} 則/秒，剩約 {(total - done) / rate / 60:.0f} 分鐘）", flush=True)

    counts = {row["_id"]: row["n"] for row in db.reviews.aggregate(
        [{"$group": {"_id": "$sentiment_roberta_raw", "n": {"$sum": 1}}}])}
    print(f"[RoBERTa] 完成。全部評論三分類統計：{counts}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    main(ap.parse_args().limit)
