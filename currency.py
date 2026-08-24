"""
即時匯率換算：把商品原幣別（JPY／KRW）換算成新台幣顯示。
用 open.er-api.com（免費、不用 API key，每天更新一次），
本機快取 12 小時，避免每次 /recommend 都對外打一次匯率 API。
"""
import time
import urllib.request
import json

RATE_API = "https://open.er-api.com/v6/latest/TWD"
CACHE_TTL_SECONDS = 12 * 60 * 60  # 12 小時

_cache = {"rates": None, "fetched_at": 0}


def _fetch_rates() -> dict:
    """回傳 {"JPY": 4.988, "KRW": 43.6, ...} —— 1 TWD 能換多少該幣別"""
    req = urllib.request.Request(RATE_API, headers={"User-Agent": "buytuoleai-demo"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read())
    if data.get("result") != "success":
        raise RuntimeError(f"匯率 API 回傳異常：{data}")
    return data["rates"]


def get_rates() -> dict:
    """帶快取的匯率表，12 小時內重複呼叫不會再打外部 API"""
    now = time.time()
    if _cache["rates"] is None or (now - _cache["fetched_at"]) > CACHE_TTL_SECONDS:
        try:
            _cache["rates"] = _fetch_rates()
            _cache["fetched_at"] = now
        except Exception as e:
            # 抓不到最新匯率時，如果還有舊快取就繼續用舊的，總比整個掛掉好；
            # 完全沒快取過才真的失敗
            if _cache["rates"] is None:
                raise RuntimeError(f"無法取得匯率，且沒有可用的舊快取：{e}")
    return _cache["rates"]


def to_twd(price, currency: str):
    """
    把 price（原幣別數值）換算成新台幣，四捨五入到整數。
    price 為 None 或 currency 不支援時回傳 None。
    """
    if price is None or not currency:
        return None
    if currency == "TWD":
        return round(price)
    rates = get_rates()
    rate = rates.get(currency)
    if not rate:
        return None
    return round(price / rate)


if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("匯率表：", get_rates())
    print("9900 JPY ->", to_twd(9900, "JPY"), "TWD")
    print("25000 KRW ->", to_twd(25000, "KRW"), "TWD")
