"""
從樂天商品自己的評論頁面（review.rakuten.co.jp）抓真實使用者評論文字，
寫進跟 PTT/Dcard 評論同一個 reviews collection，讓現有的好評率/AI摘要邏輯直接可以用，
不用額外改 api/recommend.py。

**情緒怎麼判斷**：直接用評論者自己給的星等換算（4~5 星 = positive，1~3 星 = negative），
不跑 nlp/sentiment.py 的中文情緒模型——那個模型是訓練給中文用的，套在日文評論上不準，
而且星等本身就是評論者自己的明確表態，比模型用猜的更可信、也不用多花時間跑模型。

**為什麼要透過真正的 Chrome，不能直接 headless 抓**：實測 item.rakuten.co.jp 這個網域對
headless Playwright / 純 requests 會擋（Akamai 擋下來只回傳一個 Reference 錯誤頁），
但透過真正開著的 Chrome（先手動打開首頁熱身過一次）就抓得到。所以這支腳本假設已經有一個
Chrome 開著 --remote-debugging-port=9222，直接用 Playwright 的 connect_over_cdp() 接上去
繼續操作，不會自己另外開一個 headless 瀏覽器。

執行前置作業：
  1. 開一個獨立的 Chrome：
     chrome.exe --remote-debugging-port=9222 --user-data-dir=<某個暫存資料夾> https://www.rakuten.co.jp/
  2. 確認頁面正常載入（沒有卡在驗證畫面）
  3. python -m scripts.scrape_rakuten_reviews

執行：python -m scripts.scrape_rakuten_reviews [--limit N]
"""
import re
import sys
import time

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from pymongo.errors import PyMongoError

from db.mongo_client import get_db

CDP_URL = "http://localhost:9222"
MAX_PAGES_PER_PRODUCT = 3  # 每個商品最多抓 3 頁＝60 則評論，不需要抓到全部幾萬則
SLEEP_BETWEEN_REQUESTS = 1.5


def parse_review_card(card) -> dict:
    text = card.get_text("\n", strip=True)

    rating_el = card.select_one('[class*="rating-container"] [class*="number-wrapper"] [class*="text-container"]')
    rating = rating_el.get_text(strip=True) if rating_el else None

    date_m = re.search(r"\d{4}/\d{2}/\d{2}", text)
    date = date_m.group() if date_m else None

    name_el = card.select_one('[class*="reviewer-name"]')
    reviewer_name = name_el.get_text(strip=True) if name_el else None

    gender_m = re.search(r"(男性|女性)", text)
    gender = gender_m.group() if gender_m else None

    age_m = re.search(r"(\d0代|70代以上)", text)
    age = age_m.group() if age_m else None

    order_date_m = re.search(r"注文日[：:]\s*(\d{4}/\d{2}/\d{2})", text)
    order_date = order_date_m.group(1) if order_date_m else None

    helpful_m = re.search(r"(\d+)人\s*が参考になった", text)
    helpful_count = int(helpful_m.group(1)) if helpful_m else 0

    body_el = card.select_one('[class*="size-large"][class*="white-space-pre-line"]')
    body = body_el.get_text("\n", strip=True) if body_el else None

    return {
        "rating": rating, "date": date, "reviewer_name": reviewer_name,
        "gender": gender, "age": age, "order_date": order_date,
        "helpful_count": helpful_count, "body": body,
    }


def find_review_base_url(page, item_url: str) -> str | None:
    """進商品頁，找評論連結，回傳評論頁的 base url（例如 .../item/1/409735_10000000/）"""
    page.goto(item_url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(1000)
    links = page.eval_on_selector_all(
        "a",
        "els => els.map(e => e.href).filter(h => h.includes('review.rakuten.co.jp/item/'))",
    )
    for href in links:
        m = re.search(r"(https://review\.rakuten\.co\.jp/item/1/[^/]+/)", href)
        if m:
            return m.group(1)
    return None


def scrape_product_reviews(page, product: dict) -> list[dict]:
    item_url = product["source_url"]
    base_url = find_review_base_url(page, item_url)
    if not base_url:
        print("  [找不到評論連結，跳過]")
        return []

    review_count = product.get("review_count_platform") or 0
    max_pages = MAX_PAGES_PER_PRODUCT
    if review_count:
        max_pages = min(MAX_PAGES_PER_PRODUCT, -(-review_count // 20))  # 無條件進位

    all_reviews = []
    for page_no in range(1, max_pages + 1):
        url = f"{base_url}{page_no}.1/"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"  [第 {page_no} 頁失敗] {e}")
            break
        page.wait_for_timeout(1000)

        soup = BeautifulSoup(page.content(), "html.parser")
        cards = [li for li in soup.find_all("li") if li.select_one('[class*="reviewer-info"]')]
        if not cards:
            break

        page_reviews = [parse_review_card(c) for c in cards]
        page_reviews = [r for r in page_reviews if r["body"] and r["rating"]]
        all_reviews.extend(page_reviews)
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    return all_reviews


def save_reviews(db, product_url: str, reviews: list[dict]) -> int:
    saved = 0
    for r in reviews:
        rating = int(r["rating"])
        sentiment = "positive" if rating >= 4 else "negative"
        db.reviews.update_one(
            {
                "source": "rakuten",
                "product_id": product_url,
                "reviewer_name": r["reviewer_name"],
                "date": r["date"],
            },
            {"$set": {
                "product_id": product_url,
                "source": "rakuten",
                "title": (r["body"] or "")[:50],
                "raw_text": r["body"],
                "sentiment": sentiment,
                "rating": rating,
                "gender": r["gender"],
                "age": r["age"],
                "order_date": r["order_date"],
                "helpful_count": r["helpful_count"],
            }},
            upsert=True,
        )
        saved += 1
    return saved


def save_reviews_with_retry(db, product_url: str, reviews: list[dict], attempts: int = 4) -> int:
    """
    MongoDB Atlas 長時間連續寫入時偶爾會把連線斷掉（AutoReconnect: connection closed），
    pymongo 自己只重試一次，第二次還斷就直接丟例外，整個爬蟲腳本跟著掛掉。
    這裡多包一層重試：斷線時等幾秒再寫（pymongo 下一次操作會自動重連）。
    save_reviews() 是用自然鍵 upsert，重複寫同一批不會產生重複資料，重試是安全的。
    """
    for i in range(1, attempts + 1):
        try:
            return save_reviews(db, product_url, reviews)
        except PyMongoError as e:
            print(f"  [資料庫連線問題，第 {i}/{attempts} 次重試] {str(e)[:100]}")
            time.sleep(3 * i)
    raise PyMongoError(f"連續 {attempts} 次寫入失敗：{product_url[:60]}")


def main(limit: int = None, skip_done: bool = True):
    db = get_db()
    query = {"source_platform": "rakuten", "review_count_platform": {"$gt": 0}}
    products = list(db.products.find(
        query, {"_id": 0, "source_url": 1, "review_count_platform": 1, "name_zh": 1},
    ).sort("review_count_platform", -1))

    already_done = set()
    if skip_done:
        already_done = set(db.reviews.distinct("product_id", {"source": "rakuten"}))
        products = [p for p in products if p["source_url"] not in already_done]
        print(f"已經抓過、跳過的商品數：{len(already_done)}")

    if limit:
        products = products[:limit]
    print(f"這次要處理的商品數：{len(products)}")

    total_saved = 0
    total_failed = 0
    consecutive_failures = 0

    with sync_playwright() as pw:
        def connect():
            browser = pw.chromium.connect_over_cdp(CDP_URL)
            ctx = browser.contexts[0]
            return browser, ctx.pages[0]

        browser, page = connect()

        for i, product in enumerate(products, 1):
            name = (product.get("name_zh") or "")[:30]
            print(f"[{i}/{len(products)}] {name}")
            try:
                reviews = scrape_product_reviews(page, product)
            except Exception as e:
                print(f"  [商品失敗] {e}")
                total_failed += 1
                consecutive_failures += 1
                # 連續失敗代表連線可能斷了（CDP 連線抖動），重新連一次再繼續，
                # 不要讓後面所有商品都因為同一次抖動全部跟著失敗
                if consecutive_failures >= 2:
                    print("  [連續失敗，重新連線瀏覽器]")
                    try:
                        browser.close()
                    except Exception:
                        pass
                    time.sleep(3)
                    try:
                        browser, page = connect()
                        consecutive_failures = 0
                    except Exception as reconnect_err:
                        print(f"  [重新連線失敗，停止]：{reconnect_err}")
                        break
                continue

            consecutive_failures = 0
            try:
                saved = save_reviews_with_retry(db, product["source_url"], reviews)
            except PyMongoError as e:
                print(f"  [資料庫寫入失敗，跳過這個商品，下次重跑會補] {e}")
                total_failed += 1
                continue
            total_saved += saved
            print(f"  存了 {saved} 則")
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        try:
            browser.close()
        except Exception:
            pass

    print(f"\n=== 完成：共存了 {total_saved} 則樂天評論，{total_failed} 個商品失敗 ===")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    limit_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit"):
            limit_arg = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[sys.argv.index(arg) + 1])

    main(limit=limit_arg)
