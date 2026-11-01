"""
第二輪修正（依 OpenAI gpt-4.1 獨立檢查的結果，見 scripts/openai_judge.py、README 12 節）：

  --revert    ① OpenAI 判定「修正前比較好」的翻譯 → 還原成修正前名稱（name_fix_reverted=True）
  --strip     ② OpenAI 判定「修正後加了原文沒有的內容」的翻譯 → 用 gpt-4.1 拿掉多加的內容
              （修正前名稱仍保留在 name_zh_before_fix；第一輪修正結果存 name_zh_round1）
  --cons      ③ scripts/fill_missing_cons.py 補的缺點摘要：先用完整評論逐一檢查忠實度，
              不忠實的用 gpt-4.1 依嚴格規則重寫（不寫人數、只寫評論裡明確有的缺點），舊的存 cons_round1

判斷依據讀自人工審核對照表（Downloads\\商品名稱翻譯修正對照表.csv，openai_judge.py 寫的欄位）。
金鑰從 --env 指定的 .env 讀。

執行：python -m scripts.round2_fixes --env "C:\\path\\to\\.env" --revert --strip --cons
"""
import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from dotenv import dotenv_values
from openai import OpenAI

from db.mongo_client import get_db

MODEL = "gpt-4.1"
CSV_PATH = r"C:\Users\jay20\Downloads\商品名稱翻譯修正對照表.csv"
client = None


def ask(prompt: str) -> dict:
    for attempt in range(3):
        try:
            r = client.chat.completions.create(
                model=MODEL, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}])
            return json.loads(r.choices[0].message.content)
        except Exception as e:
            if attempt == 2:
                print(f"    OpenAI 失敗：{str(e)[:100]}", flush=True)
                return {}


def read_csv():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def revert(db):
    rows = [r for r in read_csv() if r.get("OpenAI：哪個比較好") == "修正前"]
    n = 0
    for r in rows:
        p = db.products.find_one({"source_url": r["商品網址"]}, {"name_zh_before_fix": 1, "name_zh": 1})
        if p and p.get("name_zh_before_fix"):
            db.products.update_one({"source_url": r["商品網址"]}, {"$set": {
                "name_zh": p["name_zh_before_fix"], "name_zh_round1": p["name_zh"], "name_fix_reverted": True,
                "name_round2_at": datetime.now().isoformat(timespec="seconds")}})
            n += 1
    print(f"[①還原] {n} 筆還原成修正前名稱", flush=True)


def strip_added(db):
    rows = [r for r in read_csv() if r.get("OpenAI：加了原文沒有的內容？") == "是"
            and r.get("OpenAI：哪個比較好") != "修正前"]
    docs = [d for d in (db.products.find_one({"source_url": r["商品網址"]},
                                             {"source_url": 1, "name_local": 1, "name_zh": 1, "name_zh_before_fix": 1,
                                              "name_fix_reverted": 1}) for r in rows)
            if d and not d.get("name_fix_reverted")]
    fixed = 0

    def run(batch):
        nonlocal fixed
        items = [{"i": j, "original": d["name_local"], "current": d["name_zh"]} for j, d in enumerate(batch)]
        res = ask(
            "你是嚴格的台灣美妝商品翻譯審稿員。每筆有日文或韓文原名 original，以及目前的繁體中文名稱 current。"
            "current 有些地方加了 original 沒有的資訊（例如原文沒寫的成分、功效、系列說明）。"
            "請改寫成忠實的台灣繁體中文名稱：原文有的都要翻到，原文沒有的資訊全部拿掉；"
            "品牌與系列名用台灣通行譯名或保留原文；用台灣慣用說法。不要加任何說明文字。\n"
            '回傳 JSON：{"results": [{"i": 編號, "name": "改寫後名稱"}]}\n\n' + json.dumps(items, ensure_ascii=False))
        for v in res.get("results", []):
            j, name = v.get("i"), (v.get("name") or "").strip()
            if isinstance(j, int) and 0 <= j < len(batch) and name and name != batch[j]["name_zh"]:
                db.products.update_one({"source_url": batch[j]["source_url"]}, {"$set": {
                    "name_zh": name, "name_zh_round1": batch[j]["name_zh"], "name_fix_stripped": True,
                    "name_round2_at": datetime.now().isoformat(timespec="seconds")}})
                fixed += 1

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run, [docs[i:i + 20] for i in range(0, len(docs), 20)]))
    print(f"[②拿掉多加內容] 候選 {len(docs)}，改寫 {fixed} 筆", flush=True)


def cons_evidence(db, url):
    """跟產生缺點摘要時用的同一批評論：最有幫助的 60 則＋所有負評（scripts/fill_missing_cons.py）"""
    revs = list(db.reviews.find({"product_id": url, "raw_text": {"$nin": [None, ""]}},
                                {"raw_text": 1, "helpful_count": 1, "sentiment_roberta": 1, "sentiment": 1,
                                 "sentiment_text": 1, "complaints": 1}))
    revs.sort(key=lambda r: -(r.get("helpful_count") or 0))
    pool = revs[:60] + [r for r in revs[60:] if (r.get("sentiment_roberta") or r.get("sentiment")) == "negative"]
    return [r["raw_text"][:250] for r in pool
            if (r.get("sentiment_roberta") or r.get("sentiment")) == "negative"
            or r.get("sentiment_text") in ("negative", "mixed") or r.get("complaints")]


FAITHFUL_RULE = ("摘要提到的每個缺點都要能在評論中找到明確根據；不能誇大（例如只有一人提到卻說多人、寫出評論沒有的人數）；"
                 "不能把評論的正面描述當成缺點；不能誤解原文（例如「停用後」寫成「使用後」）。")


def fix_cons(db):
    docs = list(db.products.find({"ai_summary.cons_generated_at": {"$exists": True}},
                                 {"source_url": 1, "name_zh": 1, "ai_summary": 1}))
    stats = {"checked": 0, "faithful": 0, "rewritten": 0, "removed": 0}

    def run(p):
        ev = cons_evidence(db, p["source_url"])
        cons = p["ai_summary"].get("cons") or ""
        v = ask("下面是一個商品的缺點摘要，以及這個商品所有負面／褒貶並陳的評論原文（日文或韓文）。\n"
                + FAITHFUL_RULE + '\n回傳 JSON：{"faithful": true/false, "note": "不忠實時一句話說明"}\n\n'
                + json.dumps({"cons": cons, "reviews": ev}, ensure_ascii=False))
        stats["checked"] += 1
        if v.get("faithful", True):
            stats["faithful"] += 1
            return
        new = ask("根據下面的評論原文（日文或韓文），用台灣繁體中文寫這個商品的缺點摘要，1～2 句、50 字內。規則：\n"
                  "1. 只寫評論裡明確說出的缺點，每個都要有根據\n2. 不寫人數或數字，用「有使用者提到」「少數使用者覺得」\n"
                  "3. 正面描述不能寫成缺點；看不出明確缺點就回傳空字串\n"
                  '回傳 JSON：{"cons": "..."}\n\n' + json.dumps(ev, ensure_ascii=False)).get("cons", "").strip()
        update = {"ai_summary.cons_round1": cons, "ai_summary.cons_round2_at": datetime.now().isoformat(timespec="seconds"),
                  "ai_summary.cons_round1_issue": v.get("note", "")}
        if new:
            update.update({"ai_summary.cons": new, "ai_summary.cons_source": "openai_rewrite"})
            stats["rewritten"] += 1
        else:
            update.update({"ai_summary.cons": None, "ai_summary.cons_source": "removed_no_evidence"})
            stats["removed"] += 1
        db.products.update_one({"source_url": p["source_url"]}, {"$set": update})

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run, docs))
    print(f"[③缺點摘要] 檢查 {stats['checked']}，忠實 {stats['faithful']}，重寫 {stats['rewritten']}，"
          f"沒有明確缺點而移除 {stats['removed']}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--strip", action="store_true")
    ap.add_argument("--cons", action="store_true")
    a = ap.parse_args()
    client = OpenAI(api_key=dotenv_values(a.env)["OPENAI_API_KEY"])
    db = get_db()
    if a.revert:
        revert(db)
    if a.strip:
        strip_added(db)
    if a.cons:
        fix_cons(db)
