"""
修正失效的商品圖片（對應組員「待改善.docx」第 2 點「圖片離家出走」）：

1. 檢查所有商品的 image_url 打不打得開（樂天賣家換圖後舊網址會 404）
2. 失效的：用 Playwright 開商品頁（樂天會擋一般程式連線，要用瀏覽器），讀頁面的 og:image 主圖
3. 新圖片確認打得開才更新；舊網址存到 image_url_before_fix，可以還原

注意：/recommend 的圖片網址改成從 MongoDB 讀（api/recommend.py），所以這裡改完不用重建搜尋索引。

執行：python -m scripts.fix_broken_images
"""
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from db.mongo_client import get_db

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
OG_IMAGE = [re.compile(r'property="og:image"\s+content="([^"]+)"'),
            re.compile(r'content="([^"]+)"\s+property="og:image"')]


def image_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url or "", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image")
    except Exception:
        return False


def item_page_url(p: dict) -> str:
    """樂天的 source_url 是聯盟導購連結，真正的商品頁在 pc= 參數裡"""
    url = p["source_url"]
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return q.get("pc", [url])[0]


def main():
    db = get_db()
    products = list(db.products.find({}, {"_id": 0, "source_url": 1, "image_url": 1, "name_zh": 1}))
    with ThreadPoolExecutor(24) as ex:
        oks = list(ex.map(lambda p: image_ok(p.get("image_url")), products))
    broken = [p for p, ok in zip(products, oks) if not ok]
    # 逾時這種暫時性問題再確認一次，避免誤判
    broken = [p for p in broken if not image_ok(p.get("image_url"))]
    print(f"[圖片] 全部 {len(products)}，失效 {len(broken)}", flush=True)
    if not broken:
        return

    from playwright.sync_api import sync_playwright
    fixed, failed = 0, []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA, locale="ja-JP")
        for p in broken:
            new = None
            try:
                page.goto(item_page_url(p), timeout=45000)
                html = page.content()
                m = next((m for rx in OG_IMAGE if (m := rx.search(html))), None)
                new = m.group(1) if m else None
            except Exception as e:
                print(f"  打不開商品頁：{(p.get('name_zh') or '')[:30]}（{str(e)[:60]}）", flush=True)
            if new and new != p.get("image_url") and image_ok(new):
                db.products.update_one({"source_url": p["source_url"]}, {"$set": {
                    "image_url": new, "image_url_before_fix": p.get("image_url"),
                    "image_fixed_at": datetime.now().isoformat(timespec="seconds")}})
                fixed += 1
            else:
                failed.append(p)
        browser.close()
    print(f"[圖片] 修正 {fixed} 筆，修不了 {len(failed)} 筆", flush=True)
    for p in failed:
        print(f"  修不了：{(p.get('name_zh') or '')[:40]}  {p['source_url'][:80]}", flush=True)


if __name__ == "__main__":
    main()
