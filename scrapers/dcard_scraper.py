"""
Dcard 美妝版爬蟲（Playwright 版）
用真實 Chromium 瀏覽器繞過 Cloudflare，攔截 API 回應取得文章資料

執行：python -m scrapers.dcard_scraper
"""
import sys
import time
import json
import asyncio
from playwright.async_api import async_playwright
from db.mongo_client import save_review

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEYWORDS = [
    "日本藥妝", "韓國藥妝", "日韓藥妝",
    "防曬", "精華液", "保濕", "面膜",
    "COSRX", "HADA LABO", "Beauty of Joseon",
    "藥妝店", "松本清", "Olive Young",
]

FORUM_URL  = "https://www.dcard.tw/f/makeup"
SEARCH_URL = "https://www.dcard.tw/search?query={kw}"
PAGE_DELAY = 3   # 翻頁間隔秒


def _is_relevant(title: str, excerpt: str) -> bool:
    text = (title + " " + excerpt).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def _parse(raw: dict) -> dict | None:
    post_id = raw.get("id")
    title   = raw.get("title", "")
    excerpt = raw.get("excerpt", raw.get("content", ""))
    if not title or not post_id:
        return None
    return {
        "title":         title,
        "raw_text":      excerpt[:3000],
        "push_count":    None,  # Dcard 無此互動指標
        "like_count":    raw.get("likeCount", 0),
        "comment_count": raw.get("commentCount", 0),
        "forum":         raw.get("forumName", "beauty"),
        "source":        "dcard",
        "source_url":    f"https://www.dcard.tw/f/beauty/p/{post_id}",
        "product_id":    None,
        "sentiment":     None,
    }


# ── 核心：Playwright 攔截 API ────────────────────────────────────────

async def _scrape_with_playwright(max_posts: int = 200, save_db: bool = True) -> list[dict]:
    results   = []
    api_posts = []   # 攔截到的原始 API 資料

    async with async_playwright() as p:
        # 連接到已開啟的 Chrome（需先用 --remote-debugging-port=9222 開啟並登入 Dcard）
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = await context.new_page()

        # ── 攔截 Dcard API 的 JSON 回應 ──────────────────────────
        async def handle_response(response):
            url = response.url
            is_post_api = (
                "globalPaging" in url or
                "service/api/v2/forums" in url or
                "service/api/v2/posts" in url
            )
            if is_post_api and response.status == 200:
                try:
                    data = await response.json()
                    for widget in data.get("widgets", []):
                        forum_list = widget.get("forumList", {})
                        for item in forum_list.get("items", []):
                            post = item.get("post", {})
                            if post.get("title") and post.get("id"):
                                api_posts.append(post)
                        for post in widget.get("pinnedPosts", {}).get("posts", []):
                            if post.get("title") and post.get("id"):
                                api_posts.append(post)
                except Exception as e:
                    print(f"  [parse error] {e}")

        all_urls = []
        async def log_all(response):
            if "api" in response.url or "service" in response.url:
                all_urls.append((response.status, response.url[:100]))
            await handle_response(response)
        page.on("response", log_all)

        print(f"\n[Dcard] 連接到現有 Chrome，進入美妝版...")
        await page.goto(FORUM_URL, wait_until="load", timeout=60000)

        title = await page.title()
        print(f"  頁面標題：{title[:50]}")
        if "請稍候" in title or "Just a moment" in title:
            print("  [錯誤] Cloudflare 未通過，請確認 Chrome 已手動登入 Dcard")
            await browser.close()
            return results

        await page.wait_for_timeout(4000)
        print(f"  攔截到 {len(api_posts)} 篇（第一頁）")

        # ── 第二步：往下捲動翻頁，持續觸發 API ──────────────────
        scroll_count = 0
        prev_count   = 0
        while len(api_posts) < max_posts * 2 and scroll_count < 30:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)
            scroll_count += 1

            if len(api_posts) != prev_count:
                print(f"  捲動 {scroll_count} 次，攔截到 {len(api_posts)} 篇")
                prev_count = len(api_posts)

            if scroll_count % 5 == 0 and len(api_posts) == prev_count:
                print("  無新文章，停止捲動")
                break

        await browser.close()

    # ── Debug：印出攔截到的 API URL ────────────────────────────────
    print(f"\n[debug] 攔截到的 API URL（前 20 筆）：")
    for status, url in all_urls[:20]:
        print(f"  {status} {url}")
    print(f"\n[debug] 共攔截文章 {len(api_posts)} 筆")

    # ── 過濾藥妝相關文章並存入 DB ────────────────────────────────
    seen_ids = set()
    for raw in api_posts:
        post_id = raw.get("id")
        if post_id in seen_ids:
            continue
        seen_ids.add(post_id)

        title   = raw.get("title", "")
        excerpt = raw.get("excerpt", raw.get("content", ""))
        if _is_relevant(title, excerpt):
            item = _parse(raw)
            if item:
                if save_db:
                    save_review(item)
                results.append(item)
                print(f"  ✓ [{raw.get('likeCount',0)}♥] {title[:45]}")

        if len(results) >= max_posts:
            break

    return results


# ── 同步包裝 ─────────────────────────────────────────────────────────

def run(max_posts: int = 200, csv_path: str = None) -> list[dict]:
    print("[Dcard] 啟動 Playwright 爬蟲...")
    save_db = csv_path is None
    results = asyncio.run(_scrape_with_playwright(max_posts, save_db=save_db))

    if csv_path:
        import csv
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            if results:
                writer = csv.DictWriter(f, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)
        print(f"\n[Dcard] 完成，共 {len(results)} 篇存至 {csv_path}")
    else:
        print(f"\n[Dcard] 完成，共 {len(results)} 篇存入 MongoDB")

    return results


if __name__ == "__main__":
    run(max_posts=50, csv_path="dcard_test.csv")
