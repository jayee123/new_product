"""
品牌別名對照表 + 跨平台商品去重
對應企劃書第二階段「資料清洗與跨語言商品配對」。

限制：Rakuten 的 brand_zh 目前幾乎是空的（品牌翻譯還沒接 Gemini，見
PROJECT_STATUS.md 第 8 節），所以這一版的品牌聚類主要涵蓋 cosme/
oliveyoung/hwahae 三個平台。等 Gemini 翻譯把 Rakuten 的 brand_zh 補齊後，
要重跑這支腳本才會把 Rakuten 也涵蓋進來。

執行：python -m scripts.brand_dedup
"""
import sys
from itertools import combinations

from rapidfuzz import fuzz

from db.mongo_client import get_db

BRAND_SIMILARITY_THRESHOLD = 85    # 品牌名稱聚類門檻（0-100，rapidfuzz.ratio）
PRODUCT_SIMILARITY_THRESHOLD = 80  # 同品牌底下商品名稱比對門檻（token_sort_ratio）


def build_brand_aliases():
    """把各平台的 brand_zh 依字串相似度聚類成「別名群組」，寫進 brand_aliases collection，
    並把每個商品標上 brand_canonical（統一品牌名）"""
    db = get_db()
    pipeline = [
        {"$match": {"brand_zh": {"$ne": ""}}},
        {"$group": {
            "_id": "$brand_zh",
            "platforms": {"$addToSet": "$source_platform"},
            "count": {"$sum": 1},
        }},
    ]
    brands = list(db.products.aggregate(pipeline))
    brands.sort(key=lambda b: -b["count"])  # 商品數多的當群組代表名稱

    assigned = {}   # brand_zh -> canonical brand_zh
    groups = []

    for b in brands:
        name = b["_id"]
        if name in assigned:
            continue
        group = {"canonical": name, "aliases": [name],
                  "platforms": set(b["platforms"]), "product_count": b["count"]}
        assigned[name] = name
        for other in brands:
            other_name = other["_id"]
            if other_name in assigned:
                continue
            if fuzz.ratio(name, other_name) >= BRAND_SIMILARITY_THRESHOLD:
                group["aliases"].append(other_name)
                group["platforms"].update(other["platforms"])
                group["product_count"] += other["count"]
                assigned[other_name] = name
        groups.append(group)

    db.brand_aliases.delete_many({})
    docs = [{
        "canonical_brand": g["canonical"],
        "aliases": sorted(set(g["aliases"])),
        "platforms": sorted(g["platforms"]),
        "product_count": g["product_count"],
    } for g in groups]
    if docs:
        db.brand_aliases.insert_many(docs)

    updated = 0
    for name, canonical in assigned.items():
        result = db.products.update_many({"brand_zh": name}, {"$set": {"brand_canonical": canonical}})
        updated += result.modified_count

    multi_alias_groups = [g for g in groups if len(set(g["aliases"])) > 1]
    print(f"[品牌聚類] 共 {len(brands)} 個不重複品牌名稱，聚成 {len(groups)} 組")
    print(f"[品牌聚類] 其中 {len(multi_alias_groups)} 組有 2 個以上別名（代表抓到跨平台/跨譯名的同一品牌）")
    print(f"[品牌聚類] 已更新 {updated} 筆商品的 brand_canonical 欄位")
    for g in multi_alias_groups[:20]:
        print(f"  {g['canonical']}  <-  {sorted(set(g['aliases']))}  (平台: {sorted(g['platforms'])})")

    return groups


def find_cross_platform_duplicates():
    """在同一個 canonical brand 底下，跨平台比對商品名稱，找出可能是同一款商品的組合"""
    db = get_db()
    canonical_brands = db.products.distinct("brand_canonical", {"brand_canonical": {"$ne": None}})

    dup_pairs = []
    for brand in canonical_brands:
        products = list(db.products.find(
            {"brand_canonical": brand},
            {"_id": 0, "source_url": 1, "name_zh": 1, "name_local": 1,
             "source_platform": 1, "price": 1, "currency": 1},
        ))
        if len(products) < 2:
            continue
        for p1, p2 in combinations(products, 2):
            if p1["source_platform"] == p2["source_platform"]:
                continue  # 同平台內部不算「跨平台」重複，先跳過
            name1 = p1.get("name_zh") or ""
            name2 = p2.get("name_zh") or ""
            if not name1 or not name2:
                continue
            score = fuzz.token_sort_ratio(name1, name2)
            if score >= PRODUCT_SIMILARITY_THRESHOLD:
                dup_pairs.append({
                    "brand": brand,
                    "similarity": round(score, 1),
                    "product_a": {"platform": p1["source_platform"], "name": name1, "source_url": p1["source_url"]},
                    "product_b": {"platform": p2["source_platform"], "name": name2, "source_url": p2["source_url"]},
                })

    db.product_duplicates.delete_many({})
    if dup_pairs:
        db.product_duplicates.insert_many(dup_pairs)

    print(f"\n[跨平台去重] 掃了 {len(canonical_brands)} 個統一品牌，找到 {len(dup_pairs)} 組疑似跨平台重複商品")
    for d in sorted(dup_pairs, key=lambda x: -x["similarity"])[:15]:
        print(f"  [{d['similarity']}] {d['brand']}: "
              f"{d['product_a']['platform']}「{d['product_a']['name'][:25]}」 vs "
              f"{d['product_b']['platform']}「{d['product_b']['name'][:25]}」")

    return dup_pairs


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    build_brand_aliases()
    find_cross_platform_duplicates()
