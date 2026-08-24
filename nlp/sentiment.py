"""
情緒分析模組
使用 HuggingFace 中文情緒模型（CPU 可跑）
"""
from transformers import pipeline
from db.mongo_client import get_db

# 輕量中文情緒模型（CPU friendly，約 400MB）
MODEL_NAME = "uer/roberta-base-finetuned-jd-binary-chinese"

_pipe = None

def get_pipeline():
    global _pipe
    if _pipe is None:
        print(f"[情緒分析] 載入模型 {MODEL_NAME}（首次需下載 ~400MB）...")
        _pipe = pipeline("text-classification", model=MODEL_NAME, device=-1)  # device=-1 = CPU
    return _pipe


def analyze(text: str) -> dict:
    """
    分析單則文字的情緒
    回傳：{"sentiment": "positive"|"negative"}
    只做二元分類，不使用信心分數
    """
    pipe = get_pipeline()
    text = text[:512]
    result = pipe(text)[0]
    label = result["label"].lower()
    sentiment = "positive" if "pos" in label or "正" in label else "negative"
    return {"sentiment": sentiment}


def run_batch(limit: int = 200):
    """對資料庫中尚未分析的 reviews 批次做情緒分析"""
    db = get_db()
    reviews = list(db.reviews.find({"sentiment": None}, {"_id": 1, "raw_text": 1}).limit(limit))
    print(f"[情緒分析] 待分析：{len(reviews)} 篇")

    pos = neg = 0
    for rev in reviews:
        text = rev.get("raw_text", "")
        if not text:
            continue
        result = analyze(text)
        db.reviews.update_one(
            {"_id": rev["_id"]},
            {"$set": {"sentiment": result["sentiment"]}}
        )
        if result["sentiment"] == "positive":
            pos += 1
        else:
            neg += 1

    print(f"  正面：{pos}，負面：{neg}")
    print(f"  好評率：{pos/(pos+neg)*100:.1f}%" if pos+neg > 0 else "")
    return {"positive": pos, "negative": neg}


if __name__ == "__main__":
    run_batch(limit=50)
