"""
「常見缺點」功能一條龍（設計與決定見 README 10-8）：以「商品」為單位，一個一個完整做完，評論多的商品優先：

  1. 逐則評論用 LLM 抽出「情緒（看文字）＋抱怨面向（固定 10 類）＋一句話抱怨」，存回 reviews
     （新欄位 sentiment_text / complaints，**不覆蓋**現有用星等換算的 sentiment）
  2. 商品層**程式計數**：每則評論每個面向只算一票，被 ≥2 位不同評論者提到才算「常見缺點」
     （極端個案與行銷刷讚都過不了門檻）；證據原文用平台票數（helpful_count）挑最高的那則
  3. 重新生成 AI 摘要（優點／適合族群，取樣改成「負面、褒貶並陳最多 5 則 ＋ 最有幫助的正面 10 則」），
     缺點摘要（cons）**只根據第 2 步的統計**寫，AI 沒有看原文自由發揮的空間
  4. 寫回 products：complaint_stats（統計＋證據）、ai_summary.cons

為什麼以商品為單位而不是「先全部抽取、再全部寫摘要」：預算暫停時，做完的商品都是完整可用的。

**改用 Gemini（2026-09-22）**：這份是 new_product-prj 的副本，OpenAI 相關呼叫全部換成
ai/gemini.py。Gemini 免費額度下沒有計費，所以 BUDGET_CAP_USD／已花金額這組機制實際上不會
被撞到（真正的限制是 429 速率限制，ai/gemini.py 的 _call() 裡已經處理），保留這組介面只是
不想動下面的流程邏輯。已花金額一樣記在 MongoDB 的 ai_budget 集合（_id="cons_feature"）。

**可以安全中斷、重跑**：已經有 complaint_stats 的商品會跳過；沒做完的商品，已抽取完的評論不會重抽。

執行：python -m scripts.build_cons_summaries [--limit N]
"""
import io
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from pymongo import UpdateOne
from pymongo.errors import PyMongoError

from ai.gemini import (
    BudgetExceeded, GeminiError, configure_budget, extract_review_aspects,
    get_usage_summary, summarize_reviews, write_cons_summary,
)
from db.mongo_client import get_db

BUDGET_CAP_USD = 2.6
LEDGER_ID = "cons_feature"
WORKERS = 4
BATCH = 20
MAX_REVIEWS_PER_PRODUCT = 60
MIN_MENTIONS = 2
SAMPLE_NEG_MIXED = 5
SAMPLE_TOTAL = 15

stop_event = threading.Event()
print_lock = threading.Lock()


def log(msg: str) -> None:
    with print_lock:
        print(msg, flush=True)


def retry_db(fn, attempts: int = 4):
    """MongoDB Atlas 偶爾斷線（AutoReconnect），斷了等幾秒重試；寫入都是 $set/upsert，重試安全"""
    for i in range(1, attempts + 1):
        try:
            return fn()
        except PyMongoError as e:
            log(f"    [資料庫連線問題，第 {i}/{attempts} 次重試] {str(e)[:80]}")
            time.sleep(3 * i)
    raise PyMongoError("資料庫連續重試失敗")


def aggregate(reviews: list) -> dict:
    """商品層統計：每則評論每個面向只算一票；被 ≥MIN_MENTIONS 位不同評論者提到才算常見缺點"""
    analyzed = [r for r in reviews if r.get("sentiment_text")]
    n = len(analyzed)
    sent = Counter(r["sentiment_text"] for r in analyzed)
    by_aspect = defaultdict(list)
    for r in analyzed:
        seen = set()
        for c in r.get("complaints") or []:
            a = c["aspect"]
            if a == "其他" or a in seen:  # 「其他」太雜、沒有資訊量，不列入；同一則評論同一面向只算一票
                continue
            seen.add(a)
            by_aspect[a].append((r, c["detail"]))
    aspects = []
    for a, items in by_aspect.items():
        if len(items) < MIN_MENTIONS:
            continue
        details = [d for d, _ in Counter(d for _, d in items if d).most_common(3)]  # 空字串＝模型沒翻成中文，不顯示
        best = max(items, key=lambda it: (it[0].get("helpful_count") or 0))[0]  # 證據：平台票數最高的那則
        aspects.append({
            "aspect": a,
            "count": len(items),
            "share": round(len(items) / n, 3),
            "details": details,
            "evidence": {
                "text": (best.get("raw_text") or "")[:200],
                "source": best.get("source"),
                "rating": best.get("rating"),
                "helpful_count": best.get("helpful_count") or 0,
            },
        })
    aspects.sort(key=lambda x: -x["count"])
    return {
        "n_analyzed": n,
        "positive": sent.get("positive", 0),
        "mixed": sent.get("mixed", 0),
        "negative": sent.get("negative", 0),
        "aspects": aspects,
    }


def choose_sample(reviews: list) -> list:
    """摘要取樣：負面／褒貶並陳最多 5 則（負面優先）＋最有幫助的正面補到 15 則。
    不全放負面，否則摘要會被帶得太負面；不全放正面，缺點根本進不了輸入。"""
    def helpful(r):
        return -(r.get("helpful_count") or 0)
    bad = sorted([r for r in reviews if r.get("sentiment_text") in ("negative", "mixed")],
                 key=lambda r: (r["sentiment_text"] != "negative", helpful(r)))[:SAMPLE_NEG_MIXED]
    good = sorted([r for r in reviews if r.get("sentiment_text") not in ("negative", "mixed")], key=helpful)
    picked = bad + good[: SAMPLE_TOTAL - len(bad)]
    if len(picked) < SAMPLE_TOTAL:  # 正面不夠就用剩下的負面補
        rest = [r for r in reviews if r not in picked]
        picked += rest[: SAMPLE_TOTAL - len(picked)]
    return picked


# ── 缺點摘要的程式檢查（使用者 2026-09-21 同意加）──────────────────────────────
# 這是「用程式單向比對」，不是再叫 AI 檢查 AI，摘要也不會回頭當任何步驟的輸入：
# 缺點摘要提到的面向（用關鍵字判斷）和數字，都必須存在於程式算好的統計裡，否則視為幻覺。
ASPECT_KEYWORDS = {
    "質地": ["質地", "黏膩", "厚重", "乾澀"],
    "顏色／色號": ["顏色", "色號", "色差", "顯色"],
    "包裝": ["包裝", "瓶口", "幫浦"],
    "容量": ["容量", "份量"],
    "氣味": ["氣味", "香味", "味道", "異味"],
    "刺激過敏": ["刺激", "過敏", "刺痛", "泛紅", "長痘"],
    "保濕／效果": ["保濕"],  # 不放「效果」：太泛用，「持妝效果不佳」會被誤判成保濕／效果面向
    "持妝": ["持妝", "脫妝"],
    "價格": ["價格", "太貴"],
    "物流": ["物流", "出貨", "配送"],
}


def validate_cons(cons: str, stats: dict) -> bool:
    """回傳 True＝通過。不通過的情況：提到統計裡沒有的缺點面向、或出現統計裡沒有的數字。
    例外：那個關鍵字如果本來就出現在統計裡某個抱怨的描述文字中，視為合法引用
    （例如「使用後容易長痘」被模型歸在保濕／效果，缺點摘要照實引用這句就不算幻覺）"""
    allowed_aspects = {a["aspect"] for a in stats["aspects"]}
    detail_text = "".join(d for a in stats["aspects"] for d in a["details"])
    for aspect, keywords in ASPECT_KEYWORDS.items():
        if aspect in allowed_aspects:
            continue
        if any(k in cons and k not in detail_text for k in keywords):
            return False
    allowed_numbers = {str(a["count"]) for a in stats["aspects"]} | {str(stats["n_analyzed"])}
    return all(n in allowed_numbers for n in re.findall(r"\d+", cons))


def template_cons(stats: dict) -> str:
    """AI 兩次都沒通過檢查時的保底：完全由統計拼出來的固定句型，不可能有幻覺"""
    parts = []
    for a in stats["aspects"]:
        s = f"{a['aspect']}（{a['count']} 則提到"
        if a["details"]:
            s += f"，例如{'、'.join(a['details'][:2])}"
        parts.append(s + "）")
    return "評論中較常被提到的缺點有：" + "、".join(parts) + "。"


def make_cons(name: str, brand: str, stats: dict) -> tuple:
    """回傳 (缺點摘要文字, 來源)；來源 "ai"＝AI 寫的且通過檢查，"template"＝AI 兩次沒通過，改用固定句型"""
    for _ in range(2):
        cons = write_cons_summary(name, brand, stats["aspects"], stats["n_analyzed"])
        if validate_cons(cons, stats):
            return cons, "ai"
    return template_cons(stats), "template"


def process_product(db, source_url: str) -> str:
    if stop_event.is_set():
        return "skipped"
    product = db.products.find_one({"source_url": source_url},
                                   {"_id": 0, "name_zh": 1, "name_local": 1, "brand_zh": 1, "brand_local": 1})
    if not product:
        return "no_product"
    name = product.get("name_zh") or product.get("name_local") or ""
    brand = product.get("brand_zh") or product.get("brand_local") or ""

    try:
        reviews = retry_db(lambda: list(db.reviews.find(
            {"product_id": source_url, "raw_text": {"$nin": [None, ""]}},
            {"_id": 1, "raw_text": 1, "title": 1, "sentiment": 1, "helpful_count": 1, "source": 1,
             "rating": 1, "sentiment_text": 1, "complaints": 1})))
        reviews.sort(key=lambda r: -(r.get("helpful_count") or 0))
        reviews = reviews[:MAX_REVIEWS_PER_PRODUCT]
        todo = [r for r in reviews if not r.get("sentiment_text")]

        for i in range(0, len(todo), BATCH):
            if stop_event.is_set():
                return "stopped"
            chunk = todo[i:i + BATCH]
            results = extract_review_aspects([r["raw_text"] for r in chunk])
            ops = []
            for r, res in zip(chunk, results):
                if res is None:
                    continue
                r["sentiment_text"], r["complaints"] = res["sentiment"], res["complaints"]
                ops.append(UpdateOne({"_id": r["_id"]},
                                     {"$set": {"sentiment_text": res["sentiment"], "complaints": res["complaints"]}}))
            if ops:
                retry_db(lambda: db.reviews.bulk_write(ops, ordered=False))

        stats = aggregate(reviews)
        if stats["n_analyzed"] == 0:
            return "no_result"

        sample = choose_sample([r for r in reviews if r.get("sentiment_text")])
        summary = summarize_reviews(
            name, brand,
            [{"title": r.get("title", ""), "raw_text": r["raw_text"], "sentiment": r.get("sentiment")} for r in sample])
        cons, cons_source = make_cons(name, brand, stats) if stats["aspects"] else (None, None)

        now = datetime.now(timezone.utc).isoformat()
        retry_db(lambda: db.products.update_one(
            {"source_url": source_url},
            {"$set": {
                "complaint_stats": {**stats, "generated_at": now},
                "ai_summary": {"summary": summary["summary"], "suggested_for": summary["suggested_for"],
                               "cons": cons, "cons_source": cons_source, "generated_at": now},
            }}))
        return "ok" if cons else "ok_no_cons"
    except BudgetExceeded:
        stop_event.set()
        return "budget"
    except (GeminiError, PyMongoError) as e:
        log(f"    [失敗] {name[:20]}：{str(e)[:100]}")
        return "failed"


def read_spent(db) -> float:
    doc = retry_db(lambda: db.ai_budget.find_one({"_id": LEDGER_ID}))
    return float(doc["spent_usd"]) if doc else 0.0


def write_spent(db, spent: float) -> None:
    retry_db(lambda: db.ai_budget.update_one(
        {"_id": LEDGER_ID},
        {"$set": {"spent_usd": round(spent, 6), "cap_usd": BUDGET_CAP_USD,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True))


def recheck(db) -> None:
    """回頭檢查已經做完的缺點摘要（含舊版程式沒有檢查就存進去的）。**不呼叫 AI、不花錢**：
    通過檢查的標記 cons_source="ai"，沒通過的換成程式拼的固定句型（cons_source="template"）。"""
    docs = retry_db(lambda: list(db.products.find(
        {"complaint_stats.aspects.0": {"$exists": True}, "ai_summary.cons": {"$ne": None}},
        {"_id": 0, "source_url": 1, "name_zh": 1, "complaint_stats": 1, "ai_summary.cons": 1, "ai_summary.cons_source": 1})))
    ok = replaced = regenerated = 0
    for d in docs:
        stats, cons = d["complaint_stats"], d["ai_summary"]["cons"]
        if d["ai_summary"].get("cons_source") == "template":
            if "--regen-template" not in sys.argv:
                continue
            # 之前（檢查太嚴時）被換成固定句型的，用修正後的檢查讓 AI 重寫一次（少量呼叫，約 US$0.0004/個）
            cons, source = make_cons(d.get("name_zh") or "", "", stats)
            retry_db(lambda: db.products.update_one(
                {"source_url": d["source_url"]},
                {"$set": {"ai_summary.cons": cons, "ai_summary.cons_source": source}}))
            log(f"  [重寫 {source}] {(d.get('name_zh') or '')[:24]}：{cons}")
            regenerated += 1
            continue
        if validate_cons(cons, stats):
            source, new_cons = "ai", cons
            ok += 1
        else:
            source, new_cons = "template", template_cons(stats)
            replaced += 1
            log(f"  [沒通過檢查，改用固定句型] {(d.get('name_zh') or '')[:24]}\n      原本：{cons}\n      改成：{new_cons}")
        retry_db(lambda: db.products.update_one(
            {"source_url": d["source_url"]},
            {"$set": {"ai_summary.cons": new_cons, "ai_summary.cons_source": source}}))
    log(f"\n回頭檢查完成：共 {len(docs)} 個商品有缺點摘要，通過 {ok} 個，換成固定句型 {replaced} 個，"
        f"AI 重寫 {regenerated} 個")


def main(limit: int = None):
    db = get_db()
    if "--recheck" in sys.argv:
        recheck(db)
        return
    spent = read_spent(db)
    configure_budget(BUDGET_CAP_USD, spent)
    log(f"預算上限 US${BUDGET_CAP_USD}（累計），這個功能已花 US${spent:.4f}")
    if spent >= BUDGET_CAP_USD:
        log("已達預算上限，不執行。要繼續請調高 BUDGET_CAP_USD。")
        return

    order = [d["_id"] for d in retry_db(lambda: list(db.reviews.aggregate([
        {"$match": {"product_id": {"$ne": None}, "raw_text": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$product_id", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ])))]
    done = set(retry_db(lambda: db.products.distinct("source_url", {"complaint_stats.generated_at": {"$exists": True}})))
    todo = [u for u in order if u not in done]
    log(f"有評論的商品 {len(order)} 個，已完成 {len(done)} 個，這次要處理 {len(todo)} 個（評論多的優先），{WORKERS} 條同時跑")
    if limit:
        todo = todo[:limit]

    t0 = time.time()
    counts = Counter()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(process_product, db, u): u for u in todo}
        for k, fut in enumerate(as_completed(futures), 1):
            status = fut.result()
            counts[status] += 1
            if status not in ("skipped", "stopped"):
                u = get_usage_summary()["total_cost_usd"]
                log(f"[{k}/{len(todo)}] {status:<10} 累計花費 US${u:.4f}  已用 {(time.time() - t0) / 60:.1f} 分鐘")
            if k % 10 == 0:
                write_spent(db, get_usage_summary()["total_cost_usd"])

    total = get_usage_summary()["total_cost_usd"]
    write_spent(db, total)
    remaining = len(todo) - counts["ok"] - counts["ok_no_cons"]
    log("\n=== 結束 ===")
    log(f"完成 {counts['ok'] + counts['ok_no_cons']} 個商品"
        f"（其中 {counts['ok_no_cons']} 個沒有「≥2 人提到」的常見缺點，所以沒有缺點摘要），失敗 {counts['failed']} 個")
    log(f"累計花費 US${total:.4f} / 上限 US${BUDGET_CAP_USD}，用時 {(time.time() - t0) / 60:.1f} 分鐘")
    if stop_event.is_set():
        log(f"⏸ 因為預算達到上限而暫停。這次還有約 {remaining} 個商品沒做，調高上限再重跑就會自動接續。")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    limit_arg = None
    for idx, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--limit"):
            limit_arg = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[idx + 1])
    main(limit=limit_arg)
