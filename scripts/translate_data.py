"""
用 Gemini 重新翻譯：
1. Olive Young 的 name_zh / brand_zh（原本完全沒翻譯，_zh 欄位是複製韓文原文）
2. cosme / 화해 的 brand_zh（原本翻譯品質不穩定，品牌專有名詞常被誤譯成一般詞彙）

執行：python -m scripts.translate_data
"""
import sys
import time

from ai.gemini import translate_batch, GeminiError
from db.mongo_client import get_db

BATCH_SIZE = 25
# gemini-3.6-flash 的免費額度極低（實測 limit=20 且長時間不恢復，疑似每日額度而非每分鐘），
# 改用 gemini-3.1-flash-lite（見 ai/gemini.py），額度正常很多，這裡維持保守間隔就好。
SLEEP_BETWEEN_BATCHES = 2.5


def retranslate_brand(source_platform: str, note: str, only_untranslated: bool = False):
    """
    重新翻譯某平台的 brand_local -> brand_zh，寫回所有該品牌的商品。
    **每一批翻完就立刻寫入資料庫**，不要累積到最後才寫——
    這樣就算中途因為 API 逾時/限流/網路問題整支腳本掛掉，前面已經翻好的批次也不會白做。

    only_untranslated=True 時只翻 brand_zh 目前還等於 brand_local 的（=完全沒翻過），
    重跑腳本時可以跳過已經翻好的、節省 Gemini 免費額度。這個選項只適合 Olive Young——
    因為它「沒翻過」的訊號很乾淨（brand_zh 原本就是複製 brand_local）；cosme/화해 本來就
    有翻譯（只是部分品牌名翻錯），brand_zh 一開始就跟 brand_local 不同，這個過濾條件
    對它們沒有意義，要重新翻就一定要全部重翻，不能用這個選項跳過。
    """
    db = get_db()
    match = {"source_platform": source_platform, "brand_local": {"$ne": ""}}
    if only_untranslated:
        match["$expr"] = {"$eq": ["$brand_zh", "$brand_local"]}
    brands = db.products.distinct("brand_local", match)
    print(f"\n=== {source_platform} 品牌翻譯：{len(brands)} 個不重複品牌{'（跳過已翻譯過的）' if only_untranslated else ''} ===")

    translated_count = 0
    updated_count = 0
    for i in range(0, len(brands), BATCH_SIZE):
        chunk = brands[i:i + BATCH_SIZE]
        print(f"  翻譯第 {i + 1}-{i + len(chunk)} 筆（共 {len(brands)} 筆）...")
        try:
            translated = translate_batch(chunk, note=note)
        except GeminiError as e:
            print(f"    [這批失敗，跳過，之後可以重跑腳本補上] {e}")
            continue

        for orig, zh in zip(chunk, translated):
            result = db.products.update_many(
                {"source_platform": source_platform, "brand_local": orig},
                {"$set": {"brand_zh": zh}},
            )
            updated_count += result.modified_count
            translated_count += 1
        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"  完成，翻譯了 {translated_count}/{len(brands)} 個品牌，更新 {updated_count} 筆商品的 brand_zh")


def retranslate_oliveyoung_names():
    """
    Olive Young 的商品名稱是逐一不同的，沒辦法像品牌那樣去重，要一筆一筆翻。
    用 $expr 只挑 name_zh 還跟 name_local 一樣（=沒翻譯過）的商品，
    這樣重跑腳本時不會浪費額度重翻已經翻過的。
    """
    db = get_db()
    products = list(db.products.find(
        {"source_platform": "oliveyoung",
         "$expr": {"$eq": ["$name_zh", "$name_local"]}},
        {"_id": 0, "source_url": 1, "name_local": 1},
    ))
    print(f"\n=== oliveyoung 商品名稱翻譯：{len(products)} 筆（跳過已翻譯過的） ===")

    updated = 0
    for i in range(0, len(products), BATCH_SIZE):
        chunk = products[i:i + BATCH_SIZE]
        names = [p["name_local"] for p in chunk]
        print(f"  翻譯第 {i + 1}-{i + len(chunk)} 筆（共 {len(products)} 筆）...")
        try:
            translated = translate_batch(names, note="韓國藥妝商品名稱")
        except GeminiError as e:
            print(f"    [失敗，跳過這批] {e}")
            continue
        for p, zh in zip(chunk, translated):
            db.products.update_one({"source_url": p["source_url"]}, {"$set": {"name_zh": zh}})
            updated += 1
        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"  完成，更新 {updated} 筆商品的 name_zh")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    retranslate_brand("oliveyoung", "韓國藥妝品牌名稱", only_untranslated=True)
    retranslate_oliveyoung_names()
    retranslate_brand("cosme", "日本美妝品牌名稱")
    retranslate_brand("hwahae", "韓國藥妝品牌名稱")

    print("\n全部翻譯完成")
