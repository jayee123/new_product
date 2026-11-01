"""
第二輪修正後的雙重驗證：同一批隨機樣本，Gemini 跟 OpenAI（gpt-4.1）各自獨立判斷，兩家結果都列出。

  A. 翻譯正確率：隨機抽 200 個商品，修正前名稱（備份）跟目前名稱各判斷一次
  C. 補上的缺點摘要忠實度：抽 200 個（不足全部），用產生摘要時的同一批評論當證據

只讀，不改資料。結果存 reports/verify_dual_<時間>.json
執行：python -m scripts.verify_dual --env "C:\\path\\to\\.env"
"""
import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

import scripts.openai_judge as oj
from ai.gemini import ask_json as gemini_ask
from api.text_quality import display_name
from db.mongo_client import get_db
from scripts.round2_fixes import FAITHFUL_RULE, cons_evidence

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = 200


def gemini_judge_names(pairs):
    out = [None] * len(pairs)

    def run(idx):
        items = [{"i": i, "original": pairs[i][0], "zh": pairs[i][1]} for i in idx]
        try:
            res = gemini_ask("你是嚴格的台灣美妝商品翻譯審稿員。每筆有日文或韓文原名 original 和繁體中文名稱 zh。"
                             + oj.JUDGE_RULE + '\n只回傳 JSON 陣列：[{"i": 編號, "ok": true/false}]\n\n'
                             + json.dumps(items, ensure_ascii=False))
        except Exception as e:
            print(f"    Gemini 失敗：{str(e)[:80]}", flush=True)
            return
        for v in res if isinstance(res, list) else []:
            if isinstance(v, dict) and v.get("i") in idx:
                out[v["i"]] = bool(v.get("ok"))

    with ThreadPoolExecutor(2) as ex:
        list(ex.map(run, oj.batched(list(range(len(pairs))))))
    return out


def rate(xs):
    judged = [x for x in xs if x is not None]
    return (sum(judged) / len(judged)) if judged else None, len(judged)


def part_a(db, backup):
    old = {d["source_url"]: d.get("name_zh") for d in backup}
    pool = [p for p in db.products.find({}, {"source_url": 1, "name_local": 1, "name_zh": 1})
            if p.get("name_local") and p.get("name_zh") and old.get(p["source_url"])
            and p["name_local"] != old[p["source_url"]]]
    picks = pool if len(pool) <= SAMPLE else random.sample(pool, SAMPLE)
    before = [(p["name_local"], display_name(old[p["source_url"]])) for p in picks]
    after = [(p["name_local"], display_name(p["name_zh"])) for p in picks]
    res = {"population": len(pool), "checked": len(picks)}
    for judge, fn in (("openai", oj.judge_names), ("gemini", gemini_judge_names)):
        (rb, nb), (ra, na) = rate(fn(before)), rate(fn(after))
        res[judge] = {"before": rb, "after": ra, "judged": na}
        print(f"[A] 翻譯正確率（{judge}，同一批 {len(picks)} 個商品）：改善前 {rb:.1%} → 改善後 {ra:.1%}", flush=True)
    return res


def part_c(db):
    docs = [p for p in db.products.find({"ai_summary.cons_generated_at": {"$exists": True}},
                                        {"source_url": 1, "ai_summary.cons": 1})
            if (p.get("ai_summary") or {}).get("cons")]
    picks = docs if len(docs) <= SAMPLE else random.sample(docs, SAMPLE)
    items = [(p, cons_evidence(db, p["source_url"])) for p in picks]
    prompt = lambda p, ev: ("下面是一個商品的缺點摘要，以及這個商品所有負面／褒貶並陳的評論原文（日文或韓文）。\n"
                            + FAITHFUL_RULE + '\n回傳 JSON：{"faithful": true/false, "note": "不忠實時一句話說明"}\n\n'
                            + json.dumps({"cons": p["ai_summary"]["cons"], "reviews": ev}, ensure_ascii=False))

    def by_openai(x):
        return oj.ask(prompt(*x)).get("faithful")

    def by_gemini(x):
        try:
            v = gemini_ask(prompt(*x))
            return v.get("faithful") if isinstance(v, dict) else None
        except Exception:
            return None

    res = {"population": len(docs), "checked": len(picks)}
    for judge, fn, workers in (("openai", by_openai, 4), ("gemini", by_gemini, 2)):
        with ThreadPoolExecutor(workers) as ex:
            r, n = rate([None if v is None else bool(v) for v in ex.map(fn, items)])
        res[judge] = {"rate": r, "judged": n}
        print(f"[C] 缺點摘要忠實度（{judge}）：母體 {len(docs)}，檢查 {n}，忠實 {r:.1%}", flush=True)
    return res


def main(env):
    oj.client = OpenAI(api_key=dotenv_values(env)["OPENAI_API_KEY"])
    db = get_db()
    backup_file = sorted((ROOT / "reports").glob("backup_products_*.json"))[0]   # 最早的備份＝改善前
    backup = json.loads(backup_file.read_text(encoding="utf-8"))
    print(f"[雙重驗證] OpenAI {oj.MODEL} ＋ Gemini，改善前名稱取自 {backup_file.name}", flush=True)
    out = {"A": part_a(db, backup), "C": part_c(db)}
    path = ROOT / "reports" / f"verify_dual_{datetime.now():%Y%m%d_%H%M}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"報告：{path}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    main(ap.parse_args().env)
