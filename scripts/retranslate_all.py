"""
全商品文字重新檢查翻譯（2026-10-03，OpenAI gpt-4.1）：組員回報名稱還有整段日文（ディオールショウ サンク クルール）、
英文直譯（Pure C Mask → 純C面膜）。前兩輪只檢查「意思有沒有翻錯」並放過保留原文，所以沒翻的日韓文沒被抓到。

範圍：卡片上看得到的每段文字 —— name_zh、brand_zh（樂天是店名）、ai_summary.summary / suggested_for / cons
規則（使用者 2026-10-03 確認）：
  - 日文、韓文一律翻成台灣繁體中文，一個字都不留
  - 英文的品牌、系列名保留；英文的說明文字要翻出意思（Pure C Mask → 純維他命C面膜）
  - 片假名品牌用台灣通行中文名（キュレル → 珂潤）
  - 樂天店名翻成中文（XX 公式ショップ → XX 官方商店）
  - 不加原文沒有的內容；台灣用語
只改有問題的欄位，舊內容存在 v3_before.<欄位>，可以還原；已處理過的（有 v3_at）跳過，可以中斷重跑。
最後對還有日韓文的欄位再補翻一次。

執行：python -m scripts.retranslate_all --env "C:\\path\\to\\.env"
"""
import argparse
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from dotenv import dotenv_values
from openai import OpenAI

from db.mongo_client import get_db

MODEL = "gpt-4.1"
BATCH = 8
JP_KR = re.compile(r"[\u3040-\u30fa\u30fd-\u30ff\u31f0-\u31ff\uff66-\uff9f\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
FIELDS = ("name_zh", "brand_zh", "summary", "suggested_for", "cons")
client = None
lock = threading.Lock()
done = {"n": 0, "changed": 0}

RULES = """規則：
1. 日文（平假名、片假名）和韓文一律翻成台灣繁體中文，輸出不能留下任何一個日文假名或韓文字。
2. 英文的品牌名、系列名保留英文（Dior、Yunth、SK-II）；英文的說明文字要翻出意思（例：Pure C Mask → 純維他命C面膜，C 是維他命C）。
3. 片假名品牌用台灣通行的中文品牌名（キュレル → 珂潤、ディオール → 迪奧、ファンケル → 芳珂）；不確定台灣譯名時用英文原名。
   沒有台灣中文名的品牌、系列名、店名（日文假名或韓文），改用官方英文名或羅馬拼音，絕對不能保留假名或韓文
   （例：つつむ → Tsutsumu、植物나라 → Plantnara、いいね → Iine）。「・」「ー」是標點，可以保留。
4. 店名（例：XX 公式ショップ、XX 楽天市場店）翻成中文：公式ショップ → 官方商店、楽天市場店 → 樂天市場店。
5. 只翻譯、修正，不可加入原文沒有的資訊（成分、功效、人數等）；名稱裡的廣告詞、容量、色號照原本內容保留並翻成中文。
6. 用台灣用語（洗面乳不是洗面奶），不用簡體字。
7. 名稱一定要有中文說明這是什麼商品（例：롬앤 베러 댄 치크 → rom&nd Better Than Cheek 腮紅；系列名可用官方英文，但商品種類要用中文）。
8. 英文縮寫或單字直譯造成意思不清也算錯，要修（例：Pure C Mask 翻成「純C面膜」→ 應為「純維他命C面膜」）。
9. 原本已經正確的部分一個字都不要改（例：「豆乳系列」不可改成「豆乳核心」）；只修有問題的地方。
10. 目前中文已經完全正確的欄位就不要回傳；只回傳需要修改的欄位。請逐筆仔細對照原文檢查，不要漏看。"""


def ask(prompt):
    for attempt in range(3):
        try:
            r = client.chat.completions.create(model=MODEL, temperature=0, response_format={"type": "json_object"},
                                               messages=[{"role": "user", "content": prompt}])
            return json.loads(r.choices[0].message.content)
        except Exception as e:
            if attempt == 2:
                print(f"    OpenAI 失敗：{str(e)[:100]}", flush=True)
    return {}


def current(p):
    s = p.get("ai_summary") or {}
    return {"name_zh": p.get("name_zh") or "", "brand_zh": p.get("brand_zh") or "",
            "summary": s.get("summary") or "", "suggested_for": s.get("suggested_for") or "", "cons": s.get("cons") or ""}


def apply(db, p, new):
    cur = current(p)
    update, before = {}, {}
    for f in FIELDS:
        v = new.get(f)
        if not isinstance(v, str) or not v.strip() or v.strip() == cur[f] or not cur[f]:
            continue
        key = f if f in ("name_zh", "brand_zh") else f"ai_summary.{f}"
        update[key] = v.strip()
        before[f] = cur[f]
    sets = {"v3_at": datetime.now().isoformat(timespec="seconds")}
    if update:
        sets.update(update)
        sets.update({f"v3_before.{k}": v for k, v in before.items()})
    db.products.update_one({"source_url": p["source_url"]}, {"$set": sets})
    return bool(update)


def run_batch(db, batch):
    items = [{"i": j, "原文名稱": p.get("name_local") or "", "原文品牌或店名": p.get("brand_local") or "",
              **{f: v for f, v in current(p).items() if v}} for j, p in enumerate(batch)]
    res = ask("你是台灣美妝電商的翻譯審稿員。每筆商品有原文名稱、原文品牌或店名（日文、韓文或英文），以及目前的繁體中文欄位："
              "name_zh（名稱）、brand_zh（品牌或店名）、summary（評論摘要）、suggested_for（適合族群）、cons（缺點摘要）。\n"
              "請對照原文檢查並修正每個中文欄位。\n" + RULES +
              '\n回傳 JSON：{"results": [{"i": 編號, "name_zh"?: "...", "brand_zh"?: "...", "summary"?: "...", '
              '"suggested_for"?: "...", "cons"?: "..."}]}，沒有要改的商品也要回傳 {"i": 編號}。\n\n'
              + json.dumps(items, ensure_ascii=False))
    got = {v.get("i"): v for v in res.get("results", []) if isinstance(v, dict)}
    for j, p in enumerate(batch):
        if j not in got:
            continue                     # 沒拿到結果的不標記 v3_at，重跑會再處理
        changed = apply(db, p, got[j])
        with lock:
            done["n"] += 1
            done["changed"] += changed
    with lock:
        if done["n"] % 80 < BATCH:
            print(f"  已處理 {done['n']}，修改 {done['changed']}", flush=True)


def leftover_pass(db):
    """還有日韓文的欄位，逐筆單獨再翻一次"""
    left = []
    for p in db.products.find({}, {"source_url": 1, "name_local": 1, "brand_local": 1, "name_zh": 1, "brand_zh": 1,
                                   "ai_summary": 1}):
        bad = [f for f, v in current(p).items() if JP_KR.search(v)]
        if bad:
            left.append((p, bad))
    print(f"[補翻] 還有日韓文的商品 {len(left)}", flush=True)

    def one(x):
        p, bad = x
        cur = current(p)
        res = ask("下面這些中文欄位還留有日文或韓文，請全部翻成台灣繁體中文，不能留下任何假名或韓文字。\n" + RULES +
                  '\n回傳 JSON：{"欄位名": "翻好的內容", ...}，只包含下面列出的欄位。\n\n'
                  + json.dumps({"原文名稱": p.get("name_local") or "", "原文品牌或店名": p.get("brand_local") or "",
                                **{f: cur[f] for f in bad}}, ensure_ascii=False))
        apply(db, p, {f: res.get(f) for f in bad})

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, left))


def main(env):
    global client
    client = OpenAI(api_key=dotenv_values(env)["OPENAI_API_KEY"])
    db = get_db()
    todo = list(db.products.find({"v3_at": {"$exists": False}},
                                 {"source_url": 1, "name_local": 1, "brand_local": 1, "name_zh": 1, "brand_zh": 1,
                                  "ai_summary": 1}))
    print(f"[重新翻譯] 待處理 {len(todo)} 個商品（模型 {MODEL}）", flush=True)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda b: run_batch(db, b), [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]))
    print(f"[重新翻譯] 第一遍完成：處理 {done['n']}，修改 {done['changed']}", flush=True)
    leftover_pass(db)
    left = sum(1 for p in db.products.find({}, {"name_zh": 1, "brand_zh": 1, "ai_summary": 1})
               if any(JP_KR.search(v) for v in current(p).values()))
    print(f"[重新翻譯] 完成，仍有日韓文的商品 {left}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", required=True)
    main(ap.parse_args().env)
