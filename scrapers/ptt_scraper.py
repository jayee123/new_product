"""
PTT 美妝板（MAKEUP）爬蟲（Data 1）
抓取評論文章，存入 reviews 集合
"""
import sys
import time
import requests
from bs4 import BeautifulSoup
from config import REQUEST_DELAY

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

BASE_URL   = "https://www.ptt.cc"
BOARD_URL  = "https://www.ptt.cc/bbs/MAKEUP/index.html"
SESSION    = requests.Session()
SESSION.cookies.set("over18", "1")  # 跳過成人確認


def get_index_pages(start_index: str = "", max_pages: int = 5) -> list[str]:
    """取得看板首頁和往前幾頁的 URL"""
    urls = []
    url = BOARD_URL if not start_index else f"{BASE_URL}/bbs/MAKEUP/index{start_index}.html"
    for _ in range(max_pages):
        urls.append(url)
        try:
            resp = SESSION.get(url, timeout=8)
            soup = BeautifulSoup(resp.text, "lxml")
            prev = soup.select_one("a.btn.wide:-soup-contains('‹ 上頁')")
            if not prev:
                prev = soup.find("a", string=lambda s: s and "上頁" in s)
            if not prev:
                break
            url = BASE_URL + prev["href"]
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"  [分頁取得失敗] {e}")
            break
    return urls


def get_article_links(index_url: str) -> list[dict]:
    """從看板頁取得文章連結清單"""
    links = []
    try:
        resp = SESSION.get(index_url, timeout=8)
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.select("div.r-ent"):
            title_el = item.select_one("div.title a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href  = title_el["href"]
            # 只抓推薦、心得、開箱類文章，跳過問題文
            if title.startswith("[問題]") or title.startswith("Re:"):
                continue
            links.append({"title": title, "url": BASE_URL + href})
    except Exception as e:
        print(f"  [取得文章清單失敗] {e}")
    return links


def parse_article(url: str, title: str) -> dict | None:
    """解析文章頁面，取得正文內容"""
    try:
        resp = SESSION.get(url, timeout=8)
        soup = BeautifulSoup(resp.text, "lxml")

        # 移除 meta 資訊區塊
        main_content = soup.find(id="main-content")
        if not main_content:
            return None
        for tag in main_content.select("div.article-metaline, div.article-metaline-right"):
            tag.decompose()
        for tag in main_content.select("span.f2"):  # 推文區
            tag.decompose()

        raw_text = main_content.get_text("\n", strip=True)
        raw_text = raw_text[:3000]  # 最多取 3000 字

        if len(raw_text) < 50:
            return None

        # 推文數（聲量指標）
        pushes = len(soup.select("div.push"))

        return {
            "title":         title,
            "raw_text":      raw_text,
            "push_count":    pushes,
            "like_count":    None,  # PTT 無此互動指標
            "comment_count": None,  # PTT 無此互動指標
            "source":        "ptt",
            "source_url":    url,
            "product_id":    None,  # 之後由 RAG 對齊
            "sentiment":     None,  # 之後由情緒分析填入
        }
    except Exception as e:
        print(f"  [文章解析失敗] {url}: {e}")
        return None


def run(max_articles: int = 100) -> list[dict]:
    """主流程：爬 PTT MAKEUP 板"""
    from db.mongo_client import save_review
    reviews = []
    index_pages = get_index_pages(max_pages=10)

    for idx_url in index_pages:
        if len(reviews) >= max_articles:
            break
        links = get_article_links(idx_url)
        for link in links:
            if len(reviews) >= max_articles:
                break
            item = parse_article(link["url"], link["title"])
            if item:
                save_review(item)
                reviews.append(item)
                print(f"  ✓ [{item['push_count']}推] {item['title'][:40]}")
            time.sleep(REQUEST_DELAY)

    print(f"\n[PTT] 完成，共爬取 {len(reviews)} 篇文章")
    return reviews


if __name__ == "__main__":
    run(max_articles=50)
