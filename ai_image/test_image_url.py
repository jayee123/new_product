"""
Demo 驗證：AI API 能不能回傳正確的商品圖片連結？

測試兩種策略：
  Strategy A：直接問 GPT-4o（不給工具），看它會不會幻覺
  Strategy B：讓 GPT-4o 生成搜尋字串，再用 Google Custom Search 找圖

執行方式：
  python ai_image/test_image_url.py
"""
import requests
from openai import OpenAI
from config import OPENAI_API_KEY, GOOGLE_CSE_API_KEY, GOOGLE_CSE_ID

client = OpenAI(api_key=OPENAI_API_KEY)

TEST_PRODUCTS = [
    {"name": "HADA LABO Gokujyun Hyaluronic Lotion", "brand": "HADA LABO", "origin": "JP"},
    {"name": "COSRX Advanced Snail 96 Mucin Power Essence", "brand": "COSRX", "origin": "KR"},
    {"name": "Beauty of Joseon Relief Sun Rice + Probiotics SPF50+", "brand": "Beauty of Joseon", "origin": "KR"},
    {"name": "Anessa Perfect UV Sunscreen Aqua Booster", "brand": "ANESSA", "origin": "JP"},
    {"name": "LANEIGE Water Sleeping Mask Lavender", "brand": "LANEIGE", "origin": "KR"},
]


def verify_url(url: str) -> dict:
    """驗證 URL 是否真的是一張圖片"""
    if not url or not url.startswith("http"):
        return {"valid": False, "reason": "URL 格式錯誤或為空"}
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        content_type = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and "image" in content_type:
            return {"valid": True, "status": resp.status_code, "type": content_type}
        else:
            return {"valid": False, "status": resp.status_code, "type": content_type}
    except Exception as e:
        return {"valid": False, "reason": str(e)}


# ─── Strategy A：直接問 GPT-4o ─────────────────────────────────────────────

def strategy_a_ask_gpt(product: dict) -> dict:
    """直接問 GPT-4o 要商品圖片 URL（無工具，測試是否幻覺）"""
    prompt = (
        f"I need a direct image URL (.jpg or .png) for this cosmetic product:\n"
        f"Product: {product['name']}\n"
        f"Brand: {product['brand']}\n"
        f"Reply ONLY with the image URL, nothing else. "
        f"If you are not sure of an exact working URL, say UNSURE."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0,
    )
    url = resp.choices[0].message.content.strip()
    result = verify_url(url)
    return {"url": url, "verify": result}



# ─── Strategy B：GPT 生搜尋字串 + Google CSE ───────────────────────────────

def strategy_b_google_image_search(product: dict) -> dict:
    """讓 GPT 生成搜尋字串，再用 Google Custom Search API 找圖"""
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        return {"url": "", "verify": {"valid": False, "reason": "Google CSE API Key 未設定"}}

    # Step 1: GPT 生成搜尋字串
    prompt = (
        f"Generate a Google image search query to find the official product image of:\n"
        f"{product['name']} by {product['brand']}\n"
        f"Reply with ONLY the search query string, no explanation."
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=60,
        temperature=0,
    )
    search_query = resp.choices[0].message.content.strip()

    # Step 2: Google Custom Search Image
    cse_url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_CSE_API_KEY,
        "cx":  GOOGLE_CSE_ID,
        "q":   search_query,
        "searchType": "image",
        "num": 1,
        "imgType": "product",
    }
    try:
        r = requests.get(cse_url, params=params, timeout=10)
        data = r.json()
        items = data.get("items", [])
        if not items:
            return {"search_query": search_query, "url": "", "verify": {"valid": False, "reason": "搜尋無結果"}}
        image_url = items[0]["link"]
        result = verify_url(image_url)
        return {"search_query": search_query, "url": image_url, "verify": result}
    except Exception as e:
        return {"search_query": search_query, "url": "", "verify": {"valid": False, "reason": str(e)}}


# ─── 主測試流程 ─────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("AI 圖片 URL 驗證測試")
    print("=" * 70)

    results = []
    for product in TEST_PRODUCTS:
        print(f"\n商品：{product['name']}")
        print("-" * 50)

        # Strategy A
        print("[Strategy A] 直接問 GPT-4o-mini...")
        sa = strategy_a_ask_gpt(product)
        a_ok = "✅ 有效" if sa["verify"]["valid"] else "❌ 無效"
        print(f"  URL: {sa['url'][:80]}")
        print(f"  驗證: {a_ok} | {sa['verify']}")

        # Strategy B（需要 Google CSE Key）
        print("[Strategy B] GPT 生搜尋字串 + Google Image Search...")
        sb = strategy_b_google_image_search(product)
        b_ok = "✅ 有效" if sb["verify"]["valid"] else "❌ 無效（或未設定 CSE Key）"
        if "search_query" in sb:
            print(f"  搜尋字串: {sb['search_query']}")
        print(f"  URL: {sb.get('url','')[:80]}")
        print(f"  驗證: {b_ok} | {sb['verify']}")

        results.append({
            "product": product["name"],
            "strategy_a": {"url": sa["url"], "valid": sa["verify"]["valid"]},
            "strategy_b": {"url": sb.get("url",""), "valid": sb["verify"]["valid"]},
        })

    # 最終統計
    print("\n" + "=" * 70)
    print("測試結果統計")
    print("=" * 70)
    a_pass = sum(1 for r in results if r["strategy_a"]["valid"])
    b_pass = sum(1 for r in results if r["strategy_b"]["valid"])
    total  = len(results)
    print(f"Strategy A（直接問 GPT）：{a_pass}/{total} 有效圖片連結")
    print(f"Strategy B（GPT+Google）：{b_pass}/{total} 有效圖片連結")
    print()
    if a_pass < total * 0.5:
        print("⚠ Strategy A 失敗率高 → GPT 直接給 URL 有幻覺問題，不建議用於 production")
        print("→ 建議改為：爬蟲時直接抓 iHerb/Cosme.net 的 <img> src（最可靠）")
    if b_pass > a_pass:
        print("✅ Strategy B 效果較好 → 可作為備用方案（需 Google CSE Key）")

    return results


if __name__ == "__main__":
    run()
