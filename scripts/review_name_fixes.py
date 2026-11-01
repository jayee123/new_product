"""
翻譯修正的二次審查：scripts/fix_text_data.py --translation 用 Gemini 改了一批商品名稱，
實測偶爾會加油添醋（例：原文只有 ダイブイン マスク，被改成「Dive-In 低分子玻尿酸補水面膜」）。
這支逐筆對照日韓原文，標出「新名稱加了原文沒有的內容」或「新名稱可能改錯」的，
輸出成人工審核用的對照表，讓人只需要看被標記的那些。

不改任何資料，只產生：C:\\Users\\jay20\\Downloads\\商品名稱翻譯修正對照表.csv（覆寫）

執行：python -m scripts.review_name_fixes
"""
import csv
import json
import time

from ai.gemini import ask_json
from db.mongo_client import get_db

OUT = r"C:\Users\jay20\Downloads\商品名稱翻譯修正對照表.csv"
BATCH = 20


def main():
    db = get_db()
    docs = list(db.products.find({"name_zh_before_fix": {"$exists": True}},
                                 {"_id": 0, "source_url": 1, "source_platform": 1, "name_local": 1,
                                  "name_zh_before_fix": 1, "name_zh": 1, "name_fix_reason": 1}))
    print(f"[二次審查] {len(docs)} 筆", flush=True)
    verdict = {}
    for i in range(0, len(docs), BATCH):
        batch = docs[i:i + BATCH]
        items = [{"i": j, "original": d.get("name_local", ""), "before": d.get("name_zh_before_fix", ""),
                  "after": d.get("name_zh", "")} for j, d in enumerate(batch)]
        prompt = (
            "你是嚴格的台灣美妝商品翻譯審稿員。每一筆有：日文或韓文原名 original、舊中文翻譯 before、"
            "AI 修正後的中文 after。請只檢查 after：\n"
            "1. added：after 是否加了 original 裡沒有的資訊（例如原文沒有的成分、功效、品牌名、系列名）？"
            "把原文的品牌音譯成台灣通行品牌譯名不算加料。\n"
            "2. wrong：after 是否有翻錯的地方，或比 before 更差？\n"
            "不確定就標 true（寧可多標讓人確認）。\n"
            '只回傳 JSON 陣列：[{"i": 編號, "added": true/false, "wrong": true/false, "note": "有問題時一句話說明"}]\n\n'
            + json.dumps(items, ensure_ascii=False))
        for attempt in range(3):
            try:
                out = ask_json(prompt)
                break
            except Exception as e:
                out = None
                print(f"  第 {i} 批失敗（{attempt + 1}/3）：{str(e)[:80]}", flush=True)
                time.sleep(5)
        for v in out if isinstance(out, list) else []:
            j = v.get("i")
            if isinstance(j, int) and 0 <= j < len(batch):
                verdict[batch[j]["source_url"]] = v
        print(f"  {min(i + BATCH, len(docs))}/{len(docs)}", flush=True)
        time.sleep(1)

    def flag(d):
        v = verdict.get(d["source_url"])
        if v is None:
            return "未審查（請人工確認）", ""
        issues = [t for t, k in (("可能加了原文沒有的內容", "added"), ("可能翻錯", "wrong")) if v.get(k)]
        return ("⚠ " + "、".join(issues), v.get("note", "")) if issues else ("看起來OK", "")

    rows = [(d, *flag(d)) for d in docs]
    rows.sort(key=lambda r: (r[1] == "看起來OK", r[1]))       # 要人工確認的排在最前面
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["編號", "AI 二次檢查", "二次檢查說明", "日韓原文", "修正前中文", "修正後中文",
                    "第一次修正理由", "審核結果（請填：OK／改錯了／其他意見）", "平台", "商品網址"])
        for n, (d, f1, note) in enumerate(rows, 1):
            w.writerow([n, f1, note, d.get("name_local", ""), d.get("name_zh_before_fix", ""), d.get("name_zh", ""),
                        d.get("name_fix_reason", ""), "", d.get("source_platform", ""), d.get("source_url", "")])
    need = sum(1 for r in rows if r[1] != "看起來OK")
    print(f"[二次審查] 完成：需要人工確認 {need} 筆，看起來OK {len(rows) - need} 筆 → {OUT}", flush=True)


if __name__ == "__main__":
    main()
