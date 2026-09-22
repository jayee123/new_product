"""
從 Olive Young（韓國）商品頁背後的評論 JSON API 抓真實使用者評論，寫進跟 PTT/Dcard/樂天評論
同一個 reviews collection（source="oliveyoung"），欄位相容現有 api/recommend.py 邏輯。

**怎麼抓的**：商品詳細頁點「리뷰」分頁後，網頁自己會呼叫
  POST https://m.oliveyoung.co.kr/review/api/v2/reviews/cursor
body 是 {"goodsNumber","page","size","sortType","reviewType"}。直接用這支 JSON API，
比解析 HTML 穩很多。實測結果（2026-09-20）：
  - 用「頁碼」翻頁無效（page=0/1/2 都回同樣那批），要翻頁得帶 cursorId/cursorScore（本腳本用不到）
  - size 最多 50（100 會回空資料）
  - sortType 有效值：USEFUL_SCORE_DESC（預設，最有幫助）、RATING_DESC（高分在前）、RATING_ASC（低分在前）
  - 不帶 cookie（credentials: omit）就能呼叫，但必須從 www.oliveyoung.co.kr 的頁面裡發請求（跨網域）
  - **會被擋**：短時間連續送幾十個請求，網站會讓 fetch 失敗（Failed to fetch），所以每次請求間隔 2.5 秒，
    失敗就退避等待再試，連續多個商品都失敗就停下來（可以稍後重跑，會自動跳過已完成的）

**取樣**：每個商品取「最有幫助」前 30 則 ＋「最低分」前 10 則。只取最有幫助的話會全是 5 星（跟樂天一樣
全是好評），AI 摘要看不到缺點。注意：因為刻意混入低分評論，sentiment_pos_rate（好評率）會是
「這個取樣混合比例」的結果，不等於商品真實的好評比例。

情緒判斷用評論者自己給的星等（4~5 星 positive，1~3 星 negative），評論是韓文，
不跑中文情緒模型。

前置作業：
  1. 開一個獨立的 Chrome：
     chrome.exe --remote-debugging-port=9223 --user-data-dir=<暫存資料夾> https://www.oliveyoung.co.kr/
  2. 確認首頁正常載入
  3. python -m scripts.scrape_oliveyoung_reviews [--limit N]

**每爬完一批，記得跑 python -m scripts.generate_review_summaries 補 AI 摘要**（見 README 10-4b）。
"""
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright
from pymongo.errors import PyMongoError

from db.mongo_client import get_db

CDP_URL = "http://localhost:9223"
API = "https://m.oliveyoung.co.kr/review/api/v2/reviews/cursor"
HOME = "https://www.oliveyoung.co.kr/"
USEFUL_COUNT = 30
LOWEST_COUNT = 10
SLEEP_BETWEEN_REQUESTS = 2.5
MIN_CONTENT_LEN = 5
MAX_CONSECUTIVE_FAILED_PRODUCTS = 3

FETCH_JS = """
async ([api, body]) => {
  try {
    const r = await fetch(api, {method: 'POST', credentials: 'omit',
        headers: {'content-type': 'application/json', 'accept': 'application/json, text/plain, */*'},
        body: JSON.stringify(body)});
    return {status: r.status, text: await r.text()};
  } catch (e) { return {status: -1, text: String(e)}; }
}
"""


class ApiError(Exception):
    pass


def goods_number_of(url: str):
    m = re.search(r"goodsNo=([A-Za-z0-9]+)", url or "")
    return m.group(1) if m else None


def fetch_reviews(page, goods_number: str, sort_type: str, size: int) -> list[dict]:
    body = {"goodsNumber": goods_number, "page": 0, "size": size,
            "sortType": sort_type, "reviewType": "ALL"}
    for attempt in range(1, 4):
        res = page.evaluate(FETCH_JS, [API, body])
        d = None
        if res["status"] == 200:
            try:
                d = json.loads(res["text"])
            except Exception:
                d = None
        if d is not None:
            if d.get("status") == "SUCCESS":
                return (d.get("data") or {}).get("goodsReviewList") or []
            raise ApiError(f"API 回傳錯誤：{d.get('status')} {d.get('message')}")
        wait = 20 * attempt
        print(f"    [請求失敗，可能被暫時擋住，等 {wait} 秒後重試 {attempt}/3] {res['text'][:60]}")
        time.sleep(wait)
    raise ApiError("連續 3 次請求失敗（疑似被網站擋住）")


def scrape_product(page, goods_number: str) -> list[dict]:
    useful = fetch_reviews(page, goods_number, "USEFUL_SCORE_DESC", USEFUL_COUNT)
    time.sleep(SLEEP_BETWEEN_REQUESTS)
    lowest = fetch_reviews(page, goods_number, "RATING_ASC", LOWEST_COUNT)
    seen, merged = set(), []
    for r in useful + lowest:
        rid = r.get("reviewId")
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        merged.append(r)
    return merged


def save_reviews(db, product_url: str, reviews: list[dict]) -> int:
    saved = 0
    for r in reviews:
        content = (r.get("content") or "").strip()
        if len(content) < MIN_CONTENT_LEN or r.get("reviewScore") is None:
            continue
        rating = int(r["reviewScore"])
        profile = r.get("profileDto") or {}
        goods = r.get("goodsDto") or {}
        db.reviews.update_one(
            {"source": "oliveyoung", "product_id": product_url, "review_id": r["reviewId"]},
            {"$set": {
                "source": "oliveyoung",
                "product_id": product_url,
                "review_id": r["reviewId"],
                "title": content[:50],
                "raw_text": content,
                "sentiment": "positive" if rating >= 4 else "negative",
                "rating": rating,
                "date": r.get("createdDateTime"),
                "option_name": goods.get("optionName"),
                "reviewer_name": profile.get("memberNickname"),
                "skin_type": profile.get("skinType"),
                "helpful_count": r.get("recommendCount", 0),
                "has_photo": bool(r.get("hasPhoto")),
                "is_repurchase": bool(r.get("isRepurchase")),
            }},
            upsert=True,
        )
        saved += 1
    return saved


def save_reviews_with_retry(db, product_url: str, reviews: list[dict], attempts: int = 4) -> int:
    """MongoDB Atlas 長時間連續寫入偶爾會斷線（AutoReconnect），斷了等幾秒重寫；upsert 所以重寫安全"""
    for i in range(1, attempts + 1):
        try:
            return save_reviews(db, product_url, reviews)
        except PyMongoError as e:
            print(f"  [資料庫連線問題，第 {i}/{attempts} 次重試] {str(e)[:100]}")
            time.sleep(3 * i)
    raise PyMongoError(f"連續 {attempts} 次寫入失敗：{product_url[:60]}")


def main(limit: int = None):
    db = get_db()
    products = list(db.products.find(
        {"source_platform": "oliveyoung", "review_count_platform": {"$gt": 0}},
        {"_id": 0, "source_url": 1, "name_zh": 1, "review_count_platform": 1},
    ).sort("review_count_platform", -1))

    already_done = set(db.reviews.distinct("product_id", {"source": "oliveyoung"}))
    products = [p for p in products if p["source_url"] not in already_done]
    print(f"已經抓過、跳過的商品數：{len(already_done)}")
    if limit:
        products = products[:limit]
    print(f"這次要處理的商品數：{len(products)}")

    total_saved = 0
    total_failed = 0
    consecutive_failed = 0

    with sync_playwright() as pw:
        def connect():
            b = pw.chromium.connect_over_cdp(CDP_URL)
            p = b.contexts[0].pages[0]
            if "oliveyoung.co.kr" not in p.url:
                p.goto(HOME, wait_until="domcontentloaded", timeout=40000)
                p.wait_for_timeout(4000)
            return b, p

        browser, page = connect()

        for i, product in enumerate(products, 1):
            name = (product.get("name_zh") or "")[:30]
            print(f"[{i}/{len(products)}] {name}")
            goods_number = goods_number_of(product["source_url"])
            if not goods_number:
                print("  [網址裡找不到 goodsNo，跳過]")
                continue
            try:
                reviews = scrape_product(page, goods_number)
            except ApiError as e:
                print(f"  [商品失敗] {e}")
                total_failed += 1
                consecutive_failed += 1
                if consecutive_failed >= MAX_CONSECUTIVE_FAILED_PRODUCTS:
                    print(f"\n連續 {consecutive_failed} 個商品失敗，疑似被網站擋住，先停下來。"
                          "稍等一陣子（例如半小時）再重跑，會自動跳過已完成的。")
                    break
                time.sleep(30)
                continue
            except Exception as e:
                # Playwright 跟 Chrome 的 CDP 連線偶爾會斷（"Target page, context or browser has been closed"），
                # 斷了之後同一個連線物件後面所有請求都會跟著失敗（2026-09-20 實際發生：第 197 個商品起
                # 217 個全部失敗）。所以斷線要重新 connect_over_cdp() 再試這個商品一次。
                print(f"  [連線異常，重新連上 Chrome 再試一次] {str(e)[:80]}")
                try:
                    try:
                        browser.close()
                    except Exception:
                        pass
                    time.sleep(3)
                    browser, page = connect()
                    reviews = scrape_product(page, goods_number)
                except Exception as e2:
                    print(f"  [重試仍失敗] {str(e2)[:80]}")
                    total_failed += 1
                    consecutive_failed += 1
                    if consecutive_failed >= MAX_CONSECUTIVE_FAILED_PRODUCTS:
                        print(f"\n連續 {consecutive_failed} 個商品失敗，先停下來，檢查 Chrome 還在不在再重跑。")
                        break
                    continue

            consecutive_failed = 0
            try:
                saved = save_reviews_with_retry(db, product["source_url"], reviews)
            except PyMongoError as e:
                print(f"  [資料庫寫入失敗，跳過，下次重跑會補] {e}")
                total_failed += 1
                continue
            total_saved += saved
            print(f"  存了 {saved} 則")
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        try:
            browser.close()
        except Exception:
            pass

    print(f"\n=== 完成：共存了 {total_saved} 則 Olive Young 評論，{total_failed} 個商品失敗 ===")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    limit_arg = None
    for idx, arg in enumerate(sys.argv[1:], 1):
        if arg.startswith("--limit"):
            limit_arg = int(arg.split("=")[1]) if "=" in arg else int(sys.argv[idx + 1])
    main(limit=limit_arg)
