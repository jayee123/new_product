"""
修正商品文字資料（對應組員「待改善.docx」第 5、8 點）：

  --backup       先把整個 products 資料表備份成 reports/backup_products_<時間>.json（改資料前一定要先跑）
  --mainland     支語 → 台灣用語（api/text_quality.MAINLAND_TERMS），改 name_zh 跟 ai_summary 文字
  --translation  用 Gemini 檢查所有商品的中文名稱翻譯（對照日韓原文），翻錯的改成正確的台灣用語翻譯
                 （例：Skin Correct 被翻成「肌膚正確」）。原本的名稱存到 name_zh_before_fix，可以還原。
  --restore FILE 從備份檔把 name_zh、ai_summary 還原回去

改完商品名稱後要重建搜尋索引（網站要先關掉）：
  python -c "from rag.embedder import build_product_index; build_product_index()"

執行：python -m scripts.fix_text_data --backup --mainland --translation
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from pymongo import UpdateOne

from api.text_quality import MAINLAND_TERMS
from db.mongo_client import get_db

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"
BATCH = 25


def backup(db) -> Path:
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"backup_products_{datetime.now():%Y%m%d_%H%M%S}.json"
    docs = list(db.products.find({}, {"_id": 0}))
    out.write_text(json.dumps(docs, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"[備份] {len(docs)} 筆商品 → {out}", flush=True)
    return out


def _replace_terms(text):
    if not isinstance(text, str):
        return text, False
    new = text
    for bad, good in MAINLAND_TERMS.items():
        new = new.replace(bad, good)
    return new, new != text


def fix_mainland(db):
    ops = []
    for p in db.products.find({}, {"source_url": 1, "name_zh": 1, "ai_summary": 1}):
        update = {}
        name, changed = _replace_terms(p.get("name_zh"))
        if changed:
            update["name_zh"] = name
        summary = p.get("ai_summary") or {}
        for field in ("summary", "suggested_for", "cons"):
            new, changed = _replace_terms(summary.get(field))
            if changed:
                update[f"ai_summary.{field}"] = new
        if update:
            ops.append(UpdateOne({"source_url": p["source_url"]}, {"$set": update}))
    if ops:
        db.products.bulk_write(ops, ordered=False)
    print(f"[支語] 修正 {len(ops)} 筆商品", flush=True)


def fix_translation(db):
    from ai.gemini import ask_json
    pool = [p for p in db.products.find({}, {"source_url": 1, "name_zh": 1, "name_local": 1, "name_zh_before_fix": 1})
            if p.get("name_local") and p.get("name_zh") and p["name_local"] != p["name_zh"]
            and "name_zh_before_fix" not in p]      # 已經修過的跳過，可以中斷重跑
    print(f"[翻譯] 待檢查 {len(pool)} 筆", flush=True)
    fixed = 0
    for i in range(0, len(pool), BATCH):
        batch = pool[i:i + BATCH]
        items = [{"i": j, "original": p["name_local"], "zh": p["name_zh"]} for j, p in enumerate(batch)]
        prompt = (
            "你是台灣美妝商品翻譯審稿員。下面每一筆是日文或韓文的商品原名，以及我們的繁體中文名稱。\n"
            "請判斷中文名稱是否「意思正確」：商品種類、品牌、系列名、關鍵功能不能翻錯（例如 Skin Correct 是遮瑕修飾，"
            "翻成『肌膚正確』就是錯；すっぽん 是鱉不是龜苓膏）。廣告詞多寡、語序、用字不同都不算錯。\n"
            "錯的話，給出修正後的完整中文名稱：使用台灣繁體中文與台灣慣用說法（洗面乳不是洗面奶），"
            "品牌與系列名用台灣通行譯名或保留原文，其他部分（含廣告詞）照原本中文名稱的內容保留，只改錯的地方。\n"
            '只回傳 JSON 陣列：[{"i": 編號, "ok": true/false, "fixed": "ok 為 false 時的修正名稱", "reason": "一句話"}]\n\n'
            + json.dumps(items, ensure_ascii=False))
        try:
            verdicts = ask_json(prompt)
        except Exception as e:
            print(f"  第 {i}~{i + len(batch)} 筆 Gemini 失敗，跳過（重跑會再試）：{e}", flush=True)
            continue
        ops = []
        for v in verdicts if isinstance(verdicts, list) else []:
            j = v.get("i")
            if not isinstance(j, int) or not (0 <= j < len(batch)) or v.get("ok") is not False:
                continue
            new = (v.get("fixed") or "").strip()
            if not new or new == batch[j]["name_zh"]:
                continue
            ops.append(UpdateOne({"source_url": batch[j]["source_url"]}, {"$set": {
                "name_zh": new, "name_zh_before_fix": batch[j]["name_zh"],
                "name_fix_reason": v.get("reason", ""), "name_fixed_at": datetime.now().isoformat(timespec="seconds"),
            }}))
        if ops:
            db.products.bulk_write(ops, ordered=False)
            fixed += len(ops)
        print(f"  {min(i + BATCH, len(pool))}/{len(pool)}，本批修正 {len(ops)}，累計 {fixed}", flush=True)
        time.sleep(1)
    print(f"[翻譯] 完成，共修正 {fixed} 筆", flush=True)


def restore(db, path):
    docs = json.loads(Path(path).read_text(encoding="utf-8"))
    ops = [UpdateOne({"source_url": d["source_url"]},
                     {"$set": {"name_zh": d.get("name_zh"), "ai_summary": d.get("ai_summary")},
                      "$unset": {"name_zh_before_fix": "", "name_fix_reason": "", "name_fixed_at": ""}})
           for d in docs if d.get("source_url")]
    db.products.bulk_write(ops, ordered=False)
    print(f"[還原] {len(ops)} 筆", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--mainland", action="store_true")
    ap.add_argument("--translation", action="store_true")
    ap.add_argument("--restore")
    a = ap.parse_args()
    db = get_db()
    if a.restore:
        restore(db, a.restore)
    else:
        if a.backup:
            backup(db)
        if a.mainland:
            fix_mainland(db)
        if a.translation:
            fix_translation(db)
