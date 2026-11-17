"""
取消顯示／恢復顯示商品：設定 products.hidden，/recommend 搜尋結果和比價都會略過 hidden=True 的商品。
資料不刪除，隨時可以恢復。

2026-11-16 使用者要求：先取消顯示松本清的商品（松本清樂天店 マツモトキヨシ楽天市場店、
松本清台灣官網 matsukiyo_tw 如果之後匯入也一樣）。

執行：
  python -m scripts.hide_products matsukiyo          # 取消顯示松本清商品
  python -m scripts.hide_products matsukiyo --show   # 恢復顯示
"""
import argparse
import sys

from db.mongo_client import get_db

GROUPS = {
    "matsukiyo": {"$or": [
        {"source_platform": "matsukiyo_tw"},
        {"brand_local": {"$regex": "マツモトキヨシ|マツキヨ"}},
        {"source_url": {"$regex": "rakuten\\.co\\.jp%2Fmatsukiyo%2F|rakuten\\.co\\.jp/matsukiyo/"}},
    ]},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("group", choices=list(GROUPS))
    ap.add_argument("--show", action="store_true", help="恢復顯示")
    a = ap.parse_args()
    db = get_db()
    q = GROUPS[a.group]
    if a.show:
        r = db.products.update_many(q, {"$unset": {"hidden": ""}})
        print(f"[{a.group}] 恢復顯示 {r.modified_count} 筆")
    else:
        r = db.products.update_many(q, {"$set": {"hidden": True}})
        print(f"[{a.group}] 符合 {r.matched_count} 筆，取消顯示（hidden=True）")
    for p in db.products.find(q, {"_id": 0, "source_platform": 1, "name_short": 1, "hidden": 1}):
        print("  ", p.get("source_platform"), "|", p.get("name_short"), "| hidden =", p.get("hidden", False))


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
