"""
情緒分析模組（CPU 可跑）
- 中文（PTT/Dcard）：uer/roberta-base-finetuned-jd-binary-chinese，run_batch 用這個
- 日文/韓文（樂天/OliveYoung 原文，沒有翻譯）：多語言 XLM-RoBERTa，analyze_batch_multilingual 用這個。
  中文模型套在日文上實測會把好評判成負評；多語言模型則是套在 PTT 長篇文章上幾乎全判中立，
  所以兩個模型依來源分開用。
  多語言模型輸出 positive / neutral / negative 三類，**neutral 一律算負評**（團隊 2026-09-24 決定）。
  需要 sentencepiece 套件（XLM-R tokenizer）。
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


# 多語言 XLM-RoBERTa 情緒模型（約 1.1GB）
MULTILINGUAL_MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment"

_multi_pipe = None

def get_multilingual_pipeline():
    global _multi_pipe
    if _multi_pipe is None:
        print(f"[情緒分析] 載入模型 {MULTILINGUAL_MODEL_NAME}（首次需下載 ~1.1GB）...")
        _multi_pipe = pipeline("text-classification", model=MULTILINGUAL_MODEL_NAME, device=-1,
                               truncation=True, max_length=512)
    return _multi_pipe


def to_binary(label: str) -> str:
    """多語言模型三分類 → 正/負二元：只有 positive 算正評，neutral 跟 negative 都算負評"""
    return "positive" if label == "positive" else "negative"


def analyze_batch_multilingual(texts: list[str], batch_size: int = 16) -> list[dict]:
    """
    用多語言模型批次分析
    回傳：[{"label": "positive"|"neutral"|"negative", "sentiment": "positive"|"negative"}, ...]
    """
    results = get_multilingual_pipeline()([(t or "")[:1000] for t in texts], batch_size=batch_size)
    return [{"label": r["label"].lower(), "sentiment": to_binary(r["label"].lower())} for r in results]


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
            {"$set": {"sentiment": result["sentiment"],
                      # /recommend 好評率讀 sentiment_roberta（見 scripts/run_roberta_sentiment.py）
                      "sentiment_roberta": result["sentiment"],
                      "sentiment_roberta_raw": "zh_model"}}
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
