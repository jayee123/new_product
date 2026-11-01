"""
品質檢查（只讀，不改任何資料）：對應組員「待改善.docx」的 8 個問題，各算一個通過率，
用來比較改善前後。

抽樣規則：每一項都從「跟該項有關的母體」隨機抽 200 筆，母體不到 200 筆就全部檢查。
每次執行都重新隨機抽樣，結果存到 reports/quality_<時間>.json。

| # | 檢查項目 | 母體 | 通過條件 |
|---|---|---|---|
| 1 | 搜尋結果沒有重複商品 | 隨機商品，用它的名稱去搜尋 | 前 10 筆裡沒有原文名稱重複的兩筆（api/text_quality.is_duplicate） |
| 2 | 圖片能正常顯示 | 全部商品 | 圖片網址回 200 而且是圖片 |
| 3 | 不會「負評 0 卻有常見缺點」 | 有常見缺點的商品 | 負評數 > 0，或前端在負評 0 時把標題改成「好評中也有人提到」 |
| 4 | 有負評就有缺點統整 | 有負評的商品 | 有缺點摘要文字（ai_summary.cons） |
| 5 | 沒有支語 | 全部商品 | 名稱＋AI 摘要沒有 MAINLAND_TERMS 裡的詞 |
| 6 | 名稱沒有廣告詞 | 全部商品 | 顯示的名稱沒有促銷字樣（api/text_quality.has_promo） |
| 7 | 亂打字會跳警示 | 100 個亂打（含中文）＋正常查詢 | 亂打 → 警示；正常 → 不警示且有結果 |
| 8 | 名稱翻譯正確 | 有原文名稱的商品 | Gemini 判斷中文名稱是正確翻譯 |
| 9 | 沒有沒翻完的日韓文 | 全部商品（不抽樣） | 名稱、品牌、摘要、適合族群、缺點都沒有假名或韓文 |

執行：python -m scripts.quality_check [--skip-gemini] [--skip-images]
"""
import argparse
import json
import random
import re
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import urllib.request

from api.text_quality import display_name, has_promo, is_duplicate, mainland_terms_in
from db.mongo_client import get_db

SAMPLE = 200
REPORT_DIR = Path(__file__).resolve().parent.parent / "reports"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def sample(population: list) -> list:
    return population if len(population) <= SAMPLE else random.sample(population, SAMPLE)


def result(no, name, population, checked, failures):
    passed = checked - len(failures)
    rate = passed / checked if checked else None
    print(f"  #{no} {name}：母體 {population}，檢查 {checked}，通過 {passed}"
          f"（{rate:.1%}）" if rate is not None else f"  #{no} {name}：母體 0", flush=True)
    return {"no": no, "name": name, "population": population, "checked": checked,
            "passed": passed, "rate": rate, "failures_sample": failures[:15]}


def neg_pos_counts(db, urls):
    counts = {}
    for row in db.reviews.aggregate([
        {"$match": {"product_id": {"$in": urls}}},
        {"$project": {"product_id": 1, "s": {"$ifNull": ["$sentiment_roberta", "$sentiment"]},
                      "t": "$sentiment_text"}},
        {"$group": {"_id": "$product_id",
                    "pos": {"$sum": {"$cond": [{"$eq": ["$s", "positive"]}, 1, 0]}},
                    "neg": {"$sum": {"$cond": [{"$eq": ["$s", "negative"]}, 1, 0]}},
                    "mixed": {"$sum": {"$cond": [{"$eq": ["$t", "mixed"]}, 1, 0]}}}},
    ]):
        counts[row["_id"]] = row
    return counts


def check_duplicates(products):
    from api.recommend import recommend
    by_url = {p["source_url"]: p for p in products}
    picks = sample([p for p in products if p.get("name_zh")])
    failures = []
    for p in picks:
        q = display_name(p["name_zh"])[:15]
        res = recommend(q, top_k=10)
        locals_ = [(r["name"], (by_url.get(r["source_url"]) or {}).get("name_local", "")) for r in res]
        dup = next(((a[0], b[0]) for i, a in enumerate(locals_) for b in locals_[i + 1:]
                    if is_duplicate(a[1], b[1])), None)
        if dup:
            failures.append({"query": q, "dup": dup})
    return result(1, "搜尋結果沒有重複商品", len(products), len(picks), failures)


def _image_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image")
    except Exception:
        return False


def check_images(products):
    picks = sample(products)
    with ThreadPoolExecutor(16) as ex:
        oks = list(ex.map(lambda p: _image_ok(p.get("image_url") or ""), picks))
    failures = [{"name": p.get("name_zh"), "image_url": p.get("image_url")}
                for p, ok in zip(picks, oks) if not ok]
    return result(2, "圖片能正常顯示", len(products), len(picks), failures)


def check_cons(db, products):
    urls = [p["source_url"] for p in products]
    counts = neg_pos_counts(db, urls)
    has_cons = [p for p in products if ((p.get("complaint_stats") or {}).get("aspects"))]
    picks3 = sample(has_cons)
    # 前端在負評 0 時把缺點標題改成「好評中也有人提到」，就不會跟「負 0」矛盾
    shows_mixed = "好評中也有人提到" in Path("frontend/index.html").read_text(encoding="utf-8")
    f3 = []
    for p in picks3:
        c = counts.get(p["source_url"], {})
        if not (c.get("neg", 0) > 0 or shows_mixed):
            f3.append({"name": p.get("name_zh"), "neg": c.get("neg", 0), "mixed": c.get("mixed", 0)})
    r3 = result(3, "不會「負評 0 卻有常見缺點」", len(has_cons), len(picks3), f3)

    has_neg = [p for p in products if counts.get(p["source_url"], {}).get("neg", 0) > 0]
    picks4 = sample(has_neg)
    f4 = [{"name": p.get("name_zh"), "neg": counts[p["source_url"]]["neg"]} for p in picks4
          if not (p.get("ai_summary") or {}).get("cons")]
    r4 = result(4, "有負評就有缺點統整", len(has_neg), len(picks4), f4)
    return r3, r4


def check_mainland(products):
    picks = sample(products)
    failures = []
    for p in picks:
        text = (p.get("name_zh") or "") + " " + ((p.get("ai_summary") or {}).get("summary") or "")
        terms = mainland_terms_in(text)
        if terms:
            failures.append({"name": p.get("name_zh"), "terms": terms})
    return result(5, "沒有支語", len(products), len(picks), failures)


def check_promo(products):
    picks = sample(products)
    failures = [{"name": display_name(p.get("name_zh"))} for p in picks if has_promo(display_name(p.get("name_zh")))]
    return result(6, "名稱沒有廣告詞", len(products), len(picks), failures)


def check_gibberish(products):
    """亂打（英文隨機字串＋中文亂打）→ 要跳警示；正常查詢 → 不能警示而且要有結果（api/recommend.query_warning）"""
    from api.recommend import query_warning, recommend
    rnd = random.Random()
    zh_gib = ["的的的", "ㄅㄆㄇ", "啊啊啊啊", "哈哈哈", "你好", "嗯嗯", "。。。", "12345"]
    gib = zh_gib + ["".join(rnd.choice(string.ascii_lowercase) for _ in range(rnd.randint(5, 10)))
                    for _ in range(100 - len(zh_gib))]
    types = sorted({p.get("product_type") for p in products if p.get("product_type")})
    chips = ["防曬乳，怕曬黑", "敏感肌防曬不留白", "乾性肌保濕精華", "遮瑕黑眼圈", "眼影腮紅彩妝"]
    real = (types + chips + ["保濕", "美白", "控油", "抗老", "痘痘肌", "dior", "canmake", "sk-ii", "SPF50"])[:100]
    failures = []
    for q in gib:
        if not query_warning(q):
            failures.append({"query": q, "expected": "跳警示"})
    for q in real:
        if query_warning(q) or not recommend(q, top_k=5):
            failures.append({"query": q, "expected": "不警示且有結果"})
    return result(7, "亂打字會跳警示（正常查詢不警示且有結果）", len(gib) + len(real), len(gib) + len(real), failures)


_JP_KR = re.compile(r"[぀-ヺヽ-ヿㇰ-ㇿｦ-ﾟ가-힯ᄀ-ᇿ㄰-㆏]")  # 不含「・」「ー」標點


def check_untranslated(products):
    """卡片上看得到的文字（顯示名稱、品牌／店名、評論摘要、適合族群、缺點摘要）不能有日文假名或韓文。
    全部商品都檢查，不抽樣。"""
    failures = []
    for p in products:
        s = p.get("ai_summary") or {}
        fields = {"名稱": display_name(p.get("name_zh")), "品牌": p.get("brand_zh"), "摘要": s.get("summary"),
                  "適合": s.get("suggested_for"), "缺點": s.get("cons")}
        bad = [k for k, v in fields.items() if v and _JP_KR.search(v)]
        if bad:
            failures.append({"name": display_name(p.get("name_zh"))[:40], "fields": bad})
    return result(9, "沒有沒翻完的日韓文（全部檢查）", len(products), len(products), failures)


def check_translation(products):
    from ai.gemini import ask_json
    pool = [p for p in products if p.get("name_local") and p.get("name_zh") and p["name_local"] != p["name_zh"]]
    picks = sample(pool)
    failures = []
    for i in range(0, len(picks), 25):
        batch = picks[i:i + 25]
        items = [{"i": j, "original": p["name_local"], "zh": display_name(p["name_zh"])} for j, p in enumerate(batch)]
        prompt = (
            "你是台灣美妝商品翻譯審稿員。下面每一筆是日文或韓文的商品原名，以及我們的繁體中文名稱。\n"
            "請判斷中文名稱是否「意思正確」：商品種類、品牌、關鍵功能不能翻錯（例如 Skin Correct 是遮瑕修飾，"
            "翻成『肌膚正確』就是錯）。廣告詞多寡、語序、用字不同都不算錯。\n"
            '只回傳 JSON 陣列：[{"i": 編號, "ok": true/false, "reason": "錯的話用一句話說明"}]\n\n'
            + json.dumps(items, ensure_ascii=False))
        try:
            verdicts = ask_json(prompt)
        except Exception as e:
            print(f"    Gemini 失敗，這批 {len(batch)} 筆不計：{e}", flush=True)
            picks = [p for p in picks if p not in batch]
            continue
        bad = {v.get("i"): v.get("reason", "") for v in verdicts if isinstance(v, dict) and v.get("ok") is False}
        for j, p in enumerate(batch):
            if j in bad:
                failures.append({"original": p["name_local"][:80], "zh": p["name_zh"][:80], "reason": bad[j]})
        time.sleep(1)
    return result(8, "名稱翻譯正確（Gemini 判斷）", len(pool), len(picks), failures)


def main(skip_gemini=False, skip_images=False):
    db = get_db()
    products = list(db.products.find({}, {"_id": 0, "source_url": 1, "name_zh": 1, "name_local": 1,
                                          "image_url": 1, "product_type": 1, "ai_summary": 1, "brand_zh": 1,
                                          "complaint_stats": 1}))
    print(f"[品質檢查] 商品 {len(products)} 筆，每項抽 {SAMPLE} 筆（不足就全部）", flush=True)
    results = [check_duplicates(products)]
    if not skip_images:
        results.append(check_images(products))
    results.extend(check_cons(db, products))
    results.append(check_mainland(products))
    results.append(check_promo(products))
    results.append(check_gibberish(products))
    results.append(check_untranslated(products))
    if not skip_gemini:
        results.append(check_translation(products))

    rates = [r["rate"] for r in results if r["rate"] is not None]
    summary = {"time": datetime.now().isoformat(timespec="seconds"), "sample_size": SAMPLE,
               "average_rate": sum(rates) / len(rates) if rates else None, "results": results}
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / f"quality_{datetime.now():%Y%m%d_%H%M}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n平均通過率：{summary['average_rate']:.1%}　報告：{out}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-gemini", action="store_true")
    ap.add_argument("--skip-images", action="store_true")
    a = ap.parse_args()
    main(a.skip_gemini, a.skip_images)
