"""
iHerb 商品爬蟲（Data 2）
抓取日韓藥妝商品：名稱、品牌、價格、圖片URL、成分
"""
import time
import requests
from bs4 import BeautifulSoup
from config import REQUEST_DELAY, REQUEST_HEADERS

SEARCH_KEYWORDS = [
    "japanese skincare",
    "korean skincare",
    "hada labo",
    "cosrx",
    "skin aqua sunscreen",
    "anessa sunscreen",
    "beauty of joseon",
]

SEARCH_URL = "https://www.iherb.com/search?kw={kw}&s=6"  # s=6: sort by rating


def fetch_search_results(keyword: str, max_pages: int = 2) -> list[str]:
    """搜尋關鍵字，回傳商品頁 URL 清單"""
    product_urls = []
    for page in range(1, max_pages + 1):
        url = SEARCH_URL.format(kw=keyword.replace(" ", "+")) + f"&p={page}"
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            soup = BeautifulSoup(resp.text, "lxml")
            links = soup.select("a.product-link[href]")
            for a in links:
                href = a["href"]
                if href.startswith("/"):
                    href = "https://www.iherb.com" + href
                if href not in product_urls:
                    product_urls.append(href)
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  [搜尋失敗] {keyword} p{page}: {e}")
    return product_urls


def parse_product_page(url: str) -> dict | None:
    """解析商品頁，抓取所有欄位"""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        soup = BeautifulSoup(resp.text, "lxml")

        # 商品名稱
        name_el = soup.select_one("h1.product-title")
        if not name_el:
            return None
        name = name_el.get_text(strip=True)

        # 品牌
        brand_el = soup.select_one("a.brand-name, span.brand-name")
        brand = brand_el.get_text(strip=True) if brand_el else ""

        # 價格（USD）
        price_el = soup.select_one("div.price span.actual-price")
        if not price_el:
            price_el = soup.select_one("[itemprop='price']")
        price_usd_str = price_el.get_text(strip=True).replace("$", "").strip() if price_el else "0"
        try:
            price_usd = float(price_usd_str)
        except ValueError:
            price_usd = 0.0

        # 圖片 URL
        img_el = soup.select_one("img#iherb-product-image, img.product-image-main")
        image_url = ""
        if img_el:
            image_url = img_el.get("src") or img_el.get("data-src") or ""

        # 成分（Supplement Facts 或 Ingredients）
        ingredients = []
        ingr_el = soup.find("div", class_="ingredient-list")
        if not ingr_el:
            ingr_el = soup.find(id="product-specs-list")
        if ingr_el:
            text = ingr_el.get_text(" ", strip=True)
            ingredients = [i.strip() for i in text.split(",") if i.strip()][:20]

        # 分類（breadcrumb）
        cats = soup.select("div.breadcrumb a")
        category = cats[-1].get_text(strip=True) if cats else ""

        return {
            "name_en": name,
            "brand":   brand,
            "origin":  "JP" if any(k in name.lower() for k in ["japan","hada labo","anessa","biore","rohto"]) else "KR",
            "category": category,
            "price_usd": price_usd,
            "price_twd_est": round(price_usd * 32),  # 粗估換算
            "image_url": image_url,
            "ingredients": ingredients,
            "source": "iherb",
            "source_url": url,
        }
    except Exception as e:
        print(f"  [解析失敗] {url}: {e}")
        return None


def run(max_products: int = 30) -> list[dict]:
    """主流程：爬 iHerb，回傳商品資料清單"""
    from db.mongo_client import save_product
    products = []
    seen_urls: set[str] = set()

    for kw in SEARCH_KEYWORDS:
        if len(products) >= max_products:
            break
        print(f"\n[iHerb] 搜尋關鍵字：{kw}")
        urls = fetch_search_results(kw, max_pages=1)
        for url in urls:
            if len(products) >= max_products:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            item = parse_product_page(url)
            if item:
                save_product(item)
                products.append(item)
                print(f"  ✓ {item['brand']} / {item['name_en'][:40]}  ${item['price_usd']} | {item['image_url'][:60]}")
            time.sleep(REQUEST_DELAY)

    print(f"\n[iHerb] 完成，共爬取 {len(products)} 個商品")
    return products


if __name__ == "__main__":
    run(max_products=20)
