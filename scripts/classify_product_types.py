"""
幫每個商品打上一個乾淨、統一的「產品類型」欄位 product_type，取代原本前端「分類關鍵字」
文字框直接比對雜亂 category 欄位的做法。

分類邏輯分兩層，優先順序：
1. **平台原始分類已經夠精確的，直接對照過去**（例如 oliveyoung/hwahae 的「底妝」「眼妝」
   「護髮」這些本來就夠用，不需要再猜；cosme「精華液」、rakuten「美容液」也是本來就明確）
2. **平台原始分類是大水桶（cosme「乳液・精華」、oliveyoung/hwahae「護膚」）**，
   才用商品名稱（優先看已翻譯的 name_zh）裡的關鍵字去細分成 精華/化妝水/乳液/面霜等

任何一層都比對不到的，歸進 "其他保養"（如果原始分類看得出是保養品）或 "其他"（完全看不出來的）。

執行：python -m scripts.classify_product_types
"""
import sys
from collections import Counter

from db.mongo_client import get_db

# 平台原始 category 值 -> 統一 product_type。
# 值是 None 代表「這個分類太籠統，要再用商品名稱關鍵字細分」。
CATEGORY_DIRECT_MAP = {
    # --- cosme ---
    "精華液": "精華",
    "乳液・精華": None,
    "化妝水": "化妝水",
    "卸妝": "卸妝",
    "洗顏": "洗顏",
    "防曬": "防曬",
    "面霜": "面霜",
    "面膜": "面膜",
    "身體護理": "身體護理",
    "粉底": "底妝",
    "妝前乳・遮瑕": "底妝",
    "蜜粉": "底妝",
    "眼影": "眼妝",
    "眼線": "眼妝",
    "睫毛膏": "眼妝",
    "眉筆": "眼妝",
    "唇妝": "唇妝",
    "腮紅": "腮紅",
    "保健食品": "保健食品",
    "補充劑": "保健食品",
    "藥品": "藥品",
    # --- oliveyoung / hwahae ---
    "護膚-化妝水": "化妝水",
    "護膚": None,
    "護髮": "護髮",
    # 底妝/眼妝/唇妝/卸妝/防曬/面膜/保健食品 跟上面 cosme 那組同名，Python dict 天然去重不衝突
    # --- rakuten（日文原文分類） ---
    "美容液": "精華",
    "化粧水": "化妝水",
    "乳液": "乳液",
    "フェイスクリーム": "面霜",
    "日焼け止め": "防曬",
    "クレンジング": "卸妝",
    "洗顔料": "洗顏",
    "ファンデーション": "底妝",
    "アイシャドウ": "眼妝",
    "マスカラ": "眼妝",
    "リップ 口紅": "唇妝",
    "サプリメント 美容": "保健食品",
}

# 商品名稱關鍵字細分表：只用在原始分類是大水桶（護膚 / 乳液・精華）的商品身上。
# 順序有意義：越具體的排前面，才不會被更籠統的關鍵字先比對到（例如「精華液」要比「精華」先比對）。
NAME_TYPE_KEYWORDS = [
    ("精華", ["精華液", "精華霜", "精華油", "精華凍", "精華露", "精華水", "精華", "セラム", "エッセンス", "美容液"]),
    ("化妝水", ["化妝水", "爽膚水", "柔膚水", "潔顏水", "化粧水", "トナー"]),
    ("乳液", ["乳液", "乳霜", "ミルク"]),
    ("面霜", ["面霜", "凝霜", "臉霜", "クリーム"]),
    ("眼霜", ["眼霜", "眼膠", "眼貼"]),
    ("面膜", ["面膜", "マスク", "パック"]),
    ("安瓶", ["安瓶", "アンプル"]),
    ("身體護理", ["身體乳", "身體油", "沐浴乳", "身體霜"]),
    ("精油", ["精油", "オイル美容"]),
    ("噴霧", ["噴霧", "ミスト"]),
]

# 第二層細分：只套用在第一層分類結果是這幾個「大類」的商品身上，
# 因為這幾類商品名稱大多是英文/韓文品牌用語（例如「VDL Cover Stain Perfecting Cushion」），
# 中文關鍵字比對不到，要另外加英文/韓文關鍵字才拆得出更細的子類型。
# 比對時全部轉小寫比對英文，不分大小寫；順序一樣是越具體的排越前面。
SUBTYPE_KEYWORDS = {
    "底妝": [
        ("氣墊", ["氣墊", "cushion", "쿠션"]),
        ("遮瑕", ["遮瑕", "concealer", "컨실러"]),
        ("蜜粉/散粉", ["蜜粉", "散粉", "setting powder", "loose powder", "powder", "파우더"]),
        ("妝前乳/隔離", ["妝前", "隔離", "primer", "프라이머"]),
        ("修容", ["修容", "contour", "컨투어"]),
        ("打亮", ["打亮", "highlighter", "하이라이터"]),
        ("腮紅", ["腮紅", "blush", "cheek", "블러셔"]),
        ("粉底", ["粉底液", "粉底霜", "粉底", "foundation", "파운데이션"]),
    ],
    "眼妝": [
        ("眼影", ["眼影", "eyeshadow", "아이섀도"]),
        ("眼線", ["眼線", "eyeliner", "아이라이너"]),
        ("睫毛膏", ["睫毛膏", "染睫", "mascara", "마스카라"]),
        ("眉部彩妝", ["眉筆", "眉粉", "染眉", "eyebrow", "brow", "아이브로우"]),
        ("臥蠶", ["臥蠶", "臥蚕"]),
        ("假睫毛", ["睫毛", "lash", "속눈썹"]),
    ],
    "唇妝": [
        ("唇釉", ["唇釉", "lip tint", "tint", "틴트"]),
        ("唇彩/唇蜜", ["唇彩", "唇蜜", "lip gloss", "gloss", "글로스"]),
        ("唇線筆", ["唇線", "lip liner", "립라이너"]),
        ("唇油", ["唇油", "lip oil"]),
        ("口紅", ["口紅", "唇膏", "lipstick", "립스틱"]),
    ],
    "防曬": [
        ("防曬噴霧", ["防曬噴霧", "sun spray", "선스프레이"]),
        ("防曬乳", ["防曬乳", "防曬霜", "sunscreen", "선크림"]),
    ],
    "卸妝": [
        ("卸妝油", ["卸妝油", "cleansing oil", "클렌징 오일", "클렌징오일"]),
        ("卸妝水", ["卸妝水", "cleansing water", "클렌징 워터", "클렌징워터"]),
        ("卸妝膏", ["卸妝膏", "cleansing balm", "클렌징밤"]),
        ("卸妝乳/潔顏乳", ["卸妝乳", "潔顏乳", "潔膚", "潔面", "cleansing foam", "cleansing mousse",
                       "클렌징폼", "클렌징 폼"]),
    ],
    "精華": [
        ("安瓶", ["安瓶", "ampoule", "앰플"]),
        ("精華液", ["精華液", "serum", "세럼"]),
        ("精華霜", ["精華霜"]),
        ("精華油", ["精華油"]),
    ],
}


def refine_subtype(parent_type: str, name: str) -> str:
    """第二層細分：比對不到子類型的話，維持原本的大類標籤"""
    rules = SUBTYPE_KEYWORDS.get(parent_type)
    if not rules:
        return parent_type
    name_lower = name.lower()
    for subtype, keywords in rules:
        for k in keywords:
            if k.lower() in name_lower:
                return subtype
    return parent_type


def classify_one(category: str, name: str) -> str:
    category = (category or "").strip()
    name = name or ""

    if category in CATEGORY_DIRECT_MAP:
        mapped = CATEGORY_DIRECT_MAP[category]
        if mapped is not None:
            return mapped
        # mapped is None：大水桶分類，往下用名稱關鍵字細分
        for typ, keywords in NAME_TYPE_KEYWORDS:
            if any(k in name for k in keywords):
                return typ
        return "其他保養"

    # 原始分類不在對照表裡（理論上不太會發生，四平台的分類值都已經涵蓋），
    # 保底再用名稱關鍵字試一次，比對不到就真的歸類為「其他」
    for typ, keywords in NAME_TYPE_KEYWORDS:
        if any(k in name for k in keywords):
            return typ
    return "其他"


def main():
    db = get_db()
    counter = Counter()
    updates = []

    for p in db.products.find({}, {"_id": 1, "category": 1, "name_zh": 1, "name_local": 1}):
        name_zh = p.get("name_zh") or ""
        name_local = p.get("name_local") or ""
        name = f"{name_zh} {name_local}"
        product_type = classify_one(p.get("category"), name)
        product_type = refine_subtype(product_type, name)
        counter[product_type] += 1
        updates.append((p["_id"], product_type))

    print(f"總商品數：{len(updates)}")
    for pid, product_type in updates:
        db.products.update_one({"_id": pid}, {"$set": {"product_type": product_type}})

    print(f"\n分出 {len(counter)} 種統一產品類型：\n")
    for typ, cnt in counter.most_common():
        print(f"  {typ}: {cnt} 件")

    other_count = counter.get("其他", 0) + counter.get("其他保養", 0)
    print(f"\n分類不出來（其他 / 其他保養）：{other_count} 件"
          f"（{other_count / len(updates) * 100:.1f}%）")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
