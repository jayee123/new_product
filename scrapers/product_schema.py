"""
商品 collection 統一欄位 schema
把 Rakuten（日）/ Olive Young（韓）兩支爬蟲各自的中文欄位 CSV，
轉換成同一組英文欄位，再寫入 MongoDB products collection。
"""
import re
from datetime import datetime, timezone

PRODUCT_FIELDS = [
    "source_platform", "source_id", "source_url",
    "name_local", "name_zh",
    "brand_local", "brand_zh",
    "category",
    "price", "currency",
    "image_url", "description", "ingredients",
    "rating_platform", "review_count_platform",
    "capacity",
    "scraped_at",
]


def _to_number(text, cast):
    """從字串取出數字（去掉逗號、貨幣符號等），失敗回傳 None"""
    if text is None or text == "":
        return None
    digits = "".join(ch for ch in str(text) if ch.isdigit() or ch == ".")
    if not digits:
        return None
    try:
        return cast(digits)
    except ValueError:
        return None


def _to_price_jpy(text):
    """
    從 cosme 的「價格」欄位取出第一個「N円」金額。
    這個欄位常常是多規格價格並列，例如
    "30mL・9,900円 / 50mL・14,960円" 或 "5g・7,700円 / -・605円 / -・715円"，
    直接用 _to_number() 會把所有數字段落串在一起變成一個超大的假數字，
    所以要用「數字後面接 円」這個規則只抓第一段。
    """
    if not text:
        return None
    match = re.search(r"([\d,]+)\s*円", str(text))
    if not match:
        # 「オープン価格」(廠商未定價) 或已停產，沒有實際円金額可抓，回傳 None 而不是亂湊數字
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _upsize_image_url(url):
    """
    Rakuten（`?_ex=128x128`）、cosme（`?target=70x70`）的圖片網址預設都只給列表用的小縮圖，
    在商品卡片放大顯示會糊。這兩個 CDN 都支援直接把尺寸參數改大拿到清晰版本，
    改成 400x400（卡片顯示區大概 280px，留一點 retina 螢幕的餘裕）。
    """
    if not url:
        return url
    url = re.sub(r"_ex=\d+x\d+", "_ex=400x400", url)
    url = re.sub(r"target=\d+x\d+", "target=400x400", url)
    return url


_INGREDIENT_LABELS = ("その他の?成分", "有効成分", "全成分")
_INGREDIENT_SECTION_LABELS = (
    "商品特徴", "内容量", "素材タイプ", "使用方法", "ブランド", "広告文責",
    "メーカー名", "商品区分", "原産国", "生産国", "使用上の注意", "セット内容", "サイズ",
)
# 邊界要包含「其他成分標籤」本身，不然「有効成分」那段的 lazy match 會把後面
# 緊接著的「その他の成分」「全成分」一起吞進去，導致後面那段抓不到獨立的 match
_INGREDIENT_BOUNDARY = "|".join(_INGREDIENT_SECTION_LABELS + _INGREDIENT_LABELS)
_INGREDIENT_RE = re.compile(
    rf"(?:{'|'.join(_INGREDIENT_LABELS)})[:：]?\s*(.+?)(?=(?:{_INGREDIENT_BOUNDARY})|$)"
)


def _parse_ingredients_ja(description: str) -> list:
    """
    從 Rakuten 商品說明（日文）裡抓成分表，抓「有効成分」「その他の成分」標籤後面的內容。

    注意：description 目前大部分被截斷在 200 字（scraper 舊版限制，已在
    rakuten_scraper/scraper.py 放寬到 2000 字，但要重新爬過才有完整資料，
    現有資料庫裡的 1116 筆多半還是舊的截斷版），所以這裡抓出來的成分表
    可能不完整——只是「現有資料裡看得到的部分」，不是保證完整的全成分表。

    只用日文全形頓號「、」切分，半形逗號「,」不拆，因為化學成分名稱本身
    常常帶半形逗號（例如「1, 3-ブチレングリコール」＝1,3-丁二醇），拆了會斷字。
    """
    if not description:
        return []
    matches = _INGREDIENT_RE.findall(description)
    if not matches:
        return []
    seen = set()
    ingredients = []
    for chunk in matches:
        for item in chunk.split("、"):
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                ingredients.append(item)
    return ingredients


def normalize_rakuten(row: dict) -> dict:
    """
    row: rakuten_scraper/scraper.py 輸出的 CSV row（dict），欄位為
    ["關鍵字","商品名(日)","品牌","JPY售價","商品URL","圖片URL","商品說明","評分","評論數","rakuten_id"]

    注意：Rakuten 的「品牌」欄位其實是 shopName（店名），不是真正的商品品牌，
    目前先原樣帶過去，之後若要做品牌比對/篩選需要另外處理。
    """
    return {
        "source_platform": "rakuten",
        "source_id": row.get("rakuten_id", ""),
        "source_url": row.get("商品URL", ""),
        "name_local": row.get("商品名(日)", ""),
        "name_zh": "",  # 待接翻譯（比照 cosme/hwahae 用 nllb_translator）
        "brand_local": row.get("品牌", ""),  # 實為店名，非真正品牌
        "brand_zh": "",
        "category": row.get("關鍵字", ""),  # Rakuten 無結構化分類，先用搜尋關鍵字代替
        "price": _to_number(row.get("JPY售價"), int),
        "currency": "JPY",
        "image_url": _upsize_image_url(row.get("圖片URL", "")),
        "description": row.get("商品說明", ""),
        "ingredients": _parse_ingredients_ja(row.get("商品說明", "")),
        "rating_platform": _to_number(row.get("評分"), float),
        "review_count_platform": _to_number(row.get("評論數"), int),
        "capacity": "",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_oliveyoung(row: dict) -> dict:
    """
    row: olive_young_scraper/scraper.py 輸出的 CSV row（dict），欄位為
    ["大分類","大分類(韓)","商品名(韓)","商品名(中)","品牌(韓)","品牌(中)",
     "KRW售價","圖片URL","商品連結","goods_no","評分","評論數","容量","成分表"]
    評分/評論數/容量/成分表 為詳細頁補抓欄位，舊版 CSV（未跑 detail）可能沒有這幾欄。
    """
    ingredients_raw = row.get("成分表", "") or ""
    ingredients = [i.strip() for i in ingredients_raw.split(",") if i.strip()]

    return {
        "source_platform": "oliveyoung",
        "source_id": row.get("goods_no", ""),
        "source_url": row.get("商品連結", ""),
        "name_local": row.get("商品名(韓)", ""),
        "name_zh": row.get("商品名(中)", ""),
        "brand_local": row.get("品牌(韓)", ""),
        "brand_zh": row.get("品牌(中)", ""),
        "category": row.get("大分類", ""),
        "price": _to_number(row.get("KRW售價"), int),
        "currency": "KRW",
        "image_url": row.get("圖片URL", ""),
        "description": "",
        "ingredients": ingredients,
        "rating_platform": _to_number(row.get("評分"), float),
        "review_count_platform": _to_number(row.get("評論數"), int),
        "capacity": row.get("容量", ""),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_cosme(row: dict) -> dict:
    """將 cosme 榜單 CSV 轉成統一商品 schema。"""
    source_url = row.get("商品連結", "") or ""
    source_id = ""
    if source_url:
        match = re.search(r"/products/(\d+)/?", source_url)
        if match:
            source_id = match.group(1)

    return {
        "source_platform": "cosme",
        "source_id": source_id,
        "source_url": source_url,
        "name_local": row.get("商品名(日)", ""),
        "name_zh": row.get("商品名(中)", ""),
        "brand_local": row.get("品牌(日)", ""),
        "brand_zh": row.get("品牌(中)", ""),
        "category": row.get("大分類", ""),
        "price": _to_price_jpy(row.get("價格")),
        "currency": "JPY",
        "image_url": _upsize_image_url(row.get("圖片", "")),
        "description": "",
        "ingredients": [],
        "rating_platform": _to_number(row.get("評分"), float),
        "review_count_platform": _to_number(row.get("口コミ數"), int),
        "capacity": "",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def normalize_hwahae(row: dict) -> dict:
    """將 hwahae 榜單 CSV 轉成統一商品 schema。"""
    return {
        "source_platform": "hwahae",
        "source_id": row.get("商品ID", ""),
        "source_url": row.get("商品連結", ""),
        "name_local": row.get("商品名(韓)", ""),
        "name_zh": row.get("商品名(中)", ""),
        "brand_local": row.get("品牌(韓)", ""),
        "brand_zh": row.get("品牌(中)", ""),
        "category": row.get("大分類(中)", ""),
        "price": _to_number(row.get("KRW售價"), int),
        "currency": "KRW",
        "image_url": row.get("圖片URL", ""),
        "description": "",
        "ingredients": [],
        "rating_platform": _to_number(row.get("平均評分"), float),
        "review_count_platform": _to_number(row.get("評論數"), int),
        "capacity": row.get("容量", ""),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
