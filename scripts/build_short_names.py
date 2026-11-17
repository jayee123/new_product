"""
商品短名稱 name_short：卡片上顯示用，2026-11-14 使用者要求。

規則
- 寬度 ≤ 26：中日韓文字、全形符號算 2，英數、半形符號、空白算 1（name_width）
- 格式：「品牌 品項 品名重點 容量」，例：Kiehl's 精華 亮白 30/50mL、hugm 防曬 天然UV噴霧 50g
  容量一定要放（2026-11-14 使用者：不放容量，使用者看不懂同款為什麼價格不同）；
  同一頁有多種容量可選的寫成 30/50mL
- 拿掉 SPF/PA 數值、廣告詞、店名、重複關鍵字；保留色號
- 改寫完如果還是撞名，才在後面補容量
- 原本的 name_zh / name_local 不動，搜尋照樣比對完整名稱

用 OpenAI gpt-4.1（跟 scripts/retranslate_all.py 同一把 key），一次 20 筆；
超過寬度退回重寫，最多 2 次，還是超過就在詞的邊界截斷。

執行：
  python -m scripts.build_short_names --sample 30 --html 預覽.html   # 只預覽，不寫資料庫
  python -m scripts.build_short_names                                # 補還沒有 name_short 的商品
  python -m scripts.build_short_names --all                          # 全部重做
"""
import argparse
import html as htmllib
import json
import os
import random
import re
import sys
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from dotenv import dotenv_values
from openai import OpenAI

from db.mongo_client import get_db

MAX_WIDTH = 26
MODEL = "gpt-4.1"
BATCH = 20
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_client = None

_CAPACITY = re.compile(r"\d+(?:\.\d+)?\s*(?:ml|mL|ML|g|G|kg|L|枚|片|粒|錠|包|入|回分|日分|天份|個)")


def name_width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s or "")


def fit_width(s: str, limit: int = MAX_WIDTH) -> str:
    """超過寬度：從後面一個詞一個詞拿掉；只剩一個詞還太長就逐字截"""
    s = re.sub(r"\s+", " ", (s or "").strip())
    words = s.split(" ")
    while len(words) > 1 and name_width(" ".join(words)) > limit:
        words.pop()
    s = " ".join(words)
    while name_width(s) > limit:
        s = s[:-1]
    return s.strip()


def capacity_of(p: dict) -> str:
    cap = (p.get("capacity") or "").strip()
    if cap and name_width(cap) <= 10:
        return cap
    m = _CAPACITY.search(p.get("name_local") or "") or _CAPACITY.search(p.get("name_zh") or "")
    return m.group(0).replace(" ", "") if m else ""


PROMPT = f"""把每個美妝商品改寫成卡片上顯示的「短名稱」，台灣繁體中文。

格式：品牌 品項 品名重點 容量（用半形空白分開）。例：Kiehl's 精華 亮白 30/50mL、hugm 防曬 天然UV噴霧 50g、Curel 面霜 潤浸保濕 40g、rom&nd 唇釉 果汁 #06
寬度限制：中文/日文/韓文/全形字算 2，英文/數字/半形符號/空白算 1，總寬度最多 {MAX_WIDTH}。
- 品牌：用常見寫法（英文品牌用英文，有台灣通用中文名的可用中文，取較短者）。樂天的「店名」欄位是賣家，不是品牌，品牌要從商品名稱判斷；看不出品牌就省略。
- 品項：最短的中文商品種類（化妝水、乳液、精華、面霜、防曬、洗面乳、卸妝、面膜、粉底、眼影、唇膏、保健…）。
- 品名重點：系列名或主要特色，越短越好。
- 容量：原文有寫容量就一定要放在最後（例 50mL、30g、60粒、10片）；同一個商品有多種容量可選（例「30mL 50ml セット」）寫成 30/50mL；單位用 mL、g、粒、片；原文沒寫容量就不要放。
  容量會佔掉寬度，品名重點要跟著縮短，總寬度仍然不能超過上限。
- 拿掉：SPF/PA 數值、廣告詞、店名、得獎、贈品說明、重複的關鍵字。
- 保留：色號（例 #06、OC20），不然同款不同色會分不出來。色號和容量都要保留，寬度不夠時縮短或拿掉品名重點，不能拿掉色號或容量。
- 數量只有 1（1支、1個、1本）的不用寫。
- 不可加入原文沒有的資訊。
回傳 JSON：{{"results": [{{"i": 編號, "short": "短名稱"}}]}}
"""


def _ask(items: list[dict]) -> dict:
    for attempt in range(3):
        try:
            r = _client.chat.completions.create(
                model=MODEL, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": PROMPT + "\n" + json.dumps(items, ensure_ascii=False)}])
            return {x["i"]: (x.get("short") or "").strip() for x in json.loads(r.choices[0].message.content)["results"]}
        except Exception as e:
            if attempt == 2:
                print(f"  OpenAI 失敗：{str(e)[:100]}", flush=True)
    return {}


def shorten_batch(products: list[dict]) -> list[str]:
    items = [{"i": i, "原文名稱": p.get("name_local") or "", "中文名稱": p.get("name_zh") or "",
              ("店名" if p.get("source_platform") == "rakuten" else "品牌"):
                  p.get("brand_zh") or p.get("brand_local") or ""}
             for i, p in enumerate(products)]
    out = _ask(items)
    for _ in range(2):  # 超過寬度的退回重寫
        too_long = [it for it in items if name_width(out.get(it["i"], "")) > MAX_WIDTH or not out.get(it["i"])]
        if not too_long:
            break
        for it in too_long:
            it["上次太長"] = out.get(it["i"], "")
        out.update(_ask(too_long))
    return [fit_width(out.get(i) or products[i].get("name_zh") or products[i].get("name_local") or "")
            for i in range(len(products))]


def add_capacity_on_collision(products: list[dict], shorts: list[str]) -> list[str]:
    """短名稱撞名（通常是同款不同容量）的，後面補容量；補完超過寬度就先縮短品名"""
    groups = defaultdict(list)
    for i, s in enumerate(shorts):
        groups[s].append(i)
    for s, idx in groups.items():
        if len(idx) < 2:
            continue
        for i in idx:
            cap = capacity_of(products[i])
            if cap and not _CAPACITY.search(shorts[i]):
                shorts[i] = fit_width(s, MAX_WIDTH - name_width(cap) - 1) + " " + cap
    return shorts


def run(products: list[dict]) -> list[str]:
    global _client
    _client = OpenAI(api_key=dotenv_values(os.path.join(ROOT, ".env"))["OPENAI_API_KEY"])
    batches = [products[i:i + BATCH] for i in range(0, len(products), BATCH)]
    shorts = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n, res in enumerate(ex.map(shorten_batch, batches), 1):
            shorts.extend(res)
            if n % 10 == 0 or n == len(batches):
                print(f"  {min(n * BATCH, len(products))}/{len(products)}", flush=True)
    return add_capacity_on_collision(products, shorts)


def write_preview(products, shorts, path):
    from api.text_quality import display_name
    rows = []
    for p, s in zip(products, shorts):
        cur = display_name(p.get("name_zh") or p.get("name_local") or "")
        rows.append(f"<tr><td>{p.get('source_platform')}</td>"
                    f"<td class=raw>{htmllib.escape(p.get('name_local') or '')}</td>"
                    f"<td>{htmllib.escape(cur)}<span>寬度 {name_width(cur)}</span></td>"
                    f"<td class=ai>{htmllib.escape(s)}<span>寬度 {name_width(s)}</span></td></tr>")
    widths = [name_width(s) for s in shorts]
    doc = f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8><title>短名稱預覽</title>
<style>body{{font-family:system-ui,'Microsoft JhengHei';margin:24px;background:#fafafa;color:#222}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:14px}}th,td{{border:1px solid #ddd;padding:8px;vertical-align:top}}
th{{background:#333;color:#fff}}td span{{display:block;color:#999;font-size:12px;margin-top:4px}}
.raw{{color:#777;font-size:12px;max-width:320px}}.ai{{background:#eef8ee;font-weight:600;font-size:16px}}</style></head><body>
<h2>商品短名稱預覽（{len(shorts)} 筆，寬度上限 {MAX_WIDTH}，中文算 2）</h2>
<p>平均寬度 {sum(widths) / len(widths):.1f}，最寬 {max(widths)}</p>
<table><tr><th>平台</th><th>原文名稱</th><th>現在顯示</th><th>短名稱 name_short</th></tr>{''.join(rows)}</table></body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, help="隨機抽 N 筆預覽，不寫資料庫")
    ap.add_argument("--html", help="預覽輸出的 HTML 路徑")
    ap.add_argument("--all", action="store_true", help="全部重做（預設只補還沒有 name_short 的）")
    a = ap.parse_args()

    db = get_db()
    fields = {"source_url": 1, "name_zh": 1, "name_local": 1, "brand_zh": 1, "brand_local": 1,
              "source_platform": 1, "capacity": 1}
    if a.sample:
        allp = list(db.products.find({}, fields))
        random.seed(11)
        products = random.sample(allp, a.sample)
    else:
        q = {} if a.all else {"$or": [{"name_short": {"$exists": False}}, {"name_short": ""}]}
        products = list(db.products.find(q, fields))
    print(f"要處理 {len(products)} 筆商品", flush=True)
    if not products:
        return
    shorts = run(products)

    if a.sample:
        if a.html:
            write_preview(products, shorts, a.html)
            print("預覽：", a.html)
        for p, s in zip(products, shorts):
            print(f"  [{name_width(s):2d}] {s}")
        return

    for p, s in zip(products, shorts):
        db.products.update_one({"source_url": p["source_url"]}, {"$set": {"name_short": s}})
    print(f"已寫入 {len(products)} 筆 name_short；最寬 {max(name_width(s) for s in shorts)}")


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
