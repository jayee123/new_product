"""
用 OpenAI（gpt-4.1，跟產生內容的 Gemini 不同家）獨立檢查 AI 產生的內容，避免「Gemini 改、Gemini 檢查」：

  A. 翻譯正確率改善前 vs 後：隨機抽 200 個商品（同一批），舊名稱（備份）跟新名稱都判斷一次
  B. 776 筆翻譯修正逐筆：新舊哪個正確、有沒有加原文沒有的內容 → 寫進人工審核對照表
  C. scripts/fill_missing_cons.py 補的缺點摘要：抽 200 個（不足全部），對照負評原文檢查是否忠實

抽樣規則同 quality_check：每項隨機抽 200，不足就全部。只讀，不改資料庫。
金鑰從 --env 指定的 .env 讀（不寫進專案）。

執行：python -m scripts.openai_judge --env "C:\\path\\to\\.env"
"""
import argparse
import csv
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

from api.text_quality import display_name
from db.mongo_client import get_db

MODEL = "gpt-4.1"
SAMPLE = 200
BATCH = 20
ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = Path(r"C:\Users\jay20\Downloads\商品名稱翻譯修正對照表.csv")
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


def sample(xs):
    return xs if len(xs) <= SAMPLE else random.sample(xs, SAMPLE)


def batched(xs, n=BATCH):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


JUDGE_RULE = (
    "判斷中文名稱是否「意思正確」：商品種類、品牌、系列名、關鍵功能不能翻錯"
    "（例如 Skin Correct 是遮瑕修飾，翻成「肌膚正確」就是錯；すっぽん 是鱉不是龜苓膏），"
    "也不能加入原文沒有的資訊（成分、功效等）。廣告詞多寡、語序、用字風格不同不算錯。")


def judge_names(pairs):
    """pairs: [(original, zh)] → [True/False/None]"""
    out = [None] * len(pairs)

    def run(idx_batch):
        items = [{"i": i, "original": pairs[i][0], "zh": pairs[i][1]} for i in idx_batch]
        res = ask("你是嚴格的台灣美妝商品翻譯審稿員。每筆有日文或韓文原名 original 和繁體中文名稱 zh。"
                  + JUDGE_RULE + '\n回傳 JSON：{"results": [{"i": 編號, "ok": true/false}]}\n\n'
                  + json.dumps(items, ensure_ascii=False))
        for v in res.get("results", []):
            if isinstance(v.get("i"), int) and v["i"] in idx_batch:
                out[v["i"]] = bool(v.get("ok"))

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run, batched(list(range(len(pairs))))))
    return out


def part_a(db, backup):
    old_name = {d["source_url"]: d.get("name_zh") for d in backup}
    pool = [p for p in db.products.find({}, {"source_url": 1, "name_local": 1, "name_zh": 1})
            if p.get("name_local") and p.get("name_zh") and old_name.get(p["source_url"])
            and p["name_local"] != old_name[p["source_url"]]]
    picks = sample(pool)
    before = judge_names([(p["name_local"], display_name(old_name[p["source_url"]])) for p in picks])
    after = judge_names([(p["name_local"], display_name(p["name_zh"])) for p in picks])
    rate = lambda xs: sum(1 for x in xs if x) / max(1, sum(1 for x in xs if x is not None))
    res = {"population": len(pool), "checked": len(picks), "before_rate": rate(before), "after_rate": rate(after),
           "judged": sum(1 for x in after if x is not None)}
    print(f"[A] 翻譯正確率（OpenAI 判斷，同一批 {len(picks)} 個商品）：改善前 {res['before_rate']:.1%} → 改善後 {res['after_rate']:.1%}", flush=True)
    return res


def part_b(db):
    docs = list(db.products.find({"name_zh_before_fix": {"$exists": True}},
                                 {"source_url": 1, "name_local": 1, "name_zh_before_fix": 1, "name_zh": 1}))
    verdict = {}

    def run(batch):
        items = [{"i": j, "original": d["name_local"], "A": d["name_zh_before_fix"], "B": d["name_zh"]}
                 for j, d in enumerate(batch)]
        res = ask("你是嚴格的台灣美妝商品翻譯審稿員。每筆有日文或韓文原名 original，以及兩個中文翻譯 A（修正前）、B（修正後）。"
                  + JUDGE_RULE + "\n請分別判斷 A、B 是否正確，B 是否加了 original 沒有的資訊，並選出哪個比較好"
                  "（better：A／B／same）。\n"
                  '回傳 JSON：{"results": [{"i": 編號, "A_ok": true/false, "B_ok": true/false, "B_added": true/false, '
                  '"better": "A"/"B"/"same", "note": "B 有問題時一句話說明"}]}\n\n' + json.dumps(items, ensure_ascii=False))
        for v in res.get("results", []):
            j = v.get("i")
            if isinstance(j, int) and 0 <= j < len(batch):
                verdict[batch[j]["source_url"]] = v

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run, batched(docs)))
    n = len(verdict)
    stats = {
        "total": len(docs), "judged": n,
        "B_better": sum(v.get("better") == "B" for v in verdict.values()),
        "A_better": sum(v.get("better") == "A" for v in verdict.values()),
        "same": sum(v.get("better") == "same" for v in verdict.values()),
        "A_ok_rate": sum(bool(v.get("A_ok")) for v in verdict.values()) / max(1, n),
        "B_ok_rate": sum(bool(v.get("B_ok")) for v in verdict.values()) / max(1, n),
        "B_added": sum(bool(v.get("B_added")) for v in verdict.values()),
    }
    print(f"[B] 776 筆修正逐筆比較：修正後較好 {stats['B_better']}、修正前較好 {stats['A_better']}、差不多 {stats['same']}；"
          f"修正前正確率 {stats['A_ok_rate']:.1%} → 修正後 {stats['B_ok_rate']:.1%}；修正後加了原文沒有的內容 {stats['B_added']}", flush=True)
    return stats, verdict


def part_c(db):
    docs = list(db.products.find({"ai_summary.cons_generated_at": {"$exists": True}},
                                 {"source_url": 1, "name_zh": 1, "ai_summary.cons": 1}))
    picks = sample(docs)
    results = []

    def run(p):
        revs = list(db.reviews.find({"product_id": p["source_url"], "raw_text": {"$nin": [None, ""]}},
                                    {"raw_text": 1, "sentiment_roberta": 1, "sentiment_text": 1, "complaints": 1}))
        evidence = [r["raw_text"][:300] for r in revs
                    if r.get("sentiment_roberta") == "negative" or r.get("sentiment_text") in ("negative", "mixed")
                    or r.get("complaints")][:12]
        res = ask("下面是一個商品的缺點摘要，以及這個商品的負面／褒貶都有的評論原文（日文或韓文）。"
                  "請判斷缺點摘要是否忠實：摘要提到的每個缺點都要能在評論中找到根據，不能誇大（例如只有一人提到卻說很多人）。\n"
                  '回傳 JSON：{"faithful": true/false, "note": "不忠實時一句話說明"}\n\n'
                  + json.dumps({"cons": p["ai_summary"]["cons"], "reviews": evidence}, ensure_ascii=False))
        results.append({"name": p.get("name_zh"), "cons": p["ai_summary"]["cons"], **res})

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(run, picks))
    judged = [r for r in results if "faithful" in r]
    rate = sum(bool(r["faithful"]) for r in judged) / max(1, len(judged))
    print(f"[C] 補上的缺點摘要忠實度：母體 {len(docs)}，檢查 {len(judged)}，忠實 {rate:.1%}", flush=True)
    return {"population": len(docs), "checked": len(judged), "rate": rate,
            "unfaithful": [r for r in judged if not r["faithful"]][:20]}


def update_csv(verdict, db):
    if not CSV_PATH.exists():
        return
    url_by_row = {}
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    url_col = header.index("商品網址")
    new_header = header[:3] + ["OpenAI：修正後正確？", "OpenAI：哪個比較好", "OpenAI：加了原文沒有的內容？", "OpenAI 說明"] + header[3:]
    out = []
    for r in body:
        v = verdict.get(r[url_col], {})
        out.append(r[:3] + [
            "是" if v.get("B_ok") else ("否" if v else "未判斷"),
            {"A": "修正前", "B": "修正後", "same": "差不多"}.get(v.get("better"), "未判斷"),
            "是" if v.get("B_added") else ("否" if v else "未判斷"),
            v.get("note", "")] + r[3:])
    # 兩家 AI 都說沒問題的排後面；任一家有疑慮的排前面
    def risk(r):
        gem_flag = r[1] != "看起來OK"
        oa_flag = r[3] != "是" or r[4] == "修正前" or r[5] == "是"
        return 0 if (gem_flag and oa_flag) else (1 if (gem_flag or oa_flag) else 2)
    out.sort(key=risk)
    for i, r in enumerate(out, 1):
        r[0] = i
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(new_header)
        w.writerows(out)
    both = sum(1 for r in out if risk(r) == 0)
    either = sum(1 for r in out if risk(r) == 1)
    print(f"[對照表] 兩家 AI 都有疑慮 {both} 筆、其中一家有疑慮 {either} 筆、都說沒問題 {len(out) - both - either} 筆 → {CSV_PATH}", flush=True)
    return {"both_flag": both, "one_flag": either, "none_flag": len(out) - both - either}


def main(env_path):
    global client
    client = OpenAI(api_key=dotenv_values(env_path)["OPENAI_API_KEY"])
    db = get_db()
    backup_file = sorted((ROOT / "reports").glob("backup_products_*.json"))[0]
    backup = json.loads(backup_file.read_text(encoding="utf-8"))
    print(f"[OpenAI 獨立檢查] 模型 {MODEL}，改善前名稱取自 {backup_file.name}", flush=True)
    a = part_a(db, backup)
    b_stats, verdict = part_b(db)
    c = part_c(db)
    csv_stats = update_csv(verdict, db)
    out = ROOT / "reports" / f"openai_judge_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps({"model": MODEL, "A": a, "B": b_stats, "C": c, "csv": csv_stats},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"報告：{out}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    main(ap.parse_args().env)
