"""
Gemini API 呼叫模組：翻譯 + 評論摘要生成。
對應企劃書「Gemini API（翻譯）」「AI 評論摘要即時生成」這兩項功能。
用原生 REST API（urllib），不裝額外 SDK，跟專案其他地方風格一致。

**免費額度限制**：一開始用 gemini-3.6-flash（最新 preview 模型），實測免費額度
limit=20 且長時間不恢復（疑似極低的每日配額，不是每分鐘），撞到 429 後等再久都沒用。
改用 gemini-3.1-flash-lite（正式版、非 preview）後額度正常很多，連續呼叫沒問題。
如果之後又開始撞 429，一樣是抓「Please retry in N seconds」精準等到視窗重置再重試，
不要連續重試（那樣只會在同一個額度窗口內浪費更多次請求）。
"""
import json
import re
import time
import urllib.request
import urllib.error

from config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

_RETRY_AFTER_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


class GeminiError(Exception):
    pass


def _parse_json_response(raw: str):
    """
    Gemini 就算開了 responseMimeType=application/json，偶爾還是會夾帶
    ```json 包起來的 code fence、或在 JSON 後面多加一些說明文字。
    這裡先剝掉 markdown fence，再用 raw_decode 只取「第一個」合法 JSON 值，
    忽略後面多出來的雜訊，比直接 json.loads() 硬解更穩。
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = text.strip()
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        raise GeminiError(f"Gemini 回傳不是合法 JSON：{raw[:300]!r}") from e


def _extract_retry_after(err_body: str, default: float = 40.0) -> float:
    m = _RETRY_AFTER_RE.search(err_body or "")
    if m:
        return float(m.group(1)) + 3.0  # 加 3 秒緩衝，避免卡在邊界又撞一次
    return default


def _call(prompt: str, retries: int = 2) -> str:
    if not GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY 沒設定，去 .env 補上")

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }).encode("utf-8")

    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                data=body, headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = f"HTTP {e.code}: {err_body[:200]}"
            if e.code == 429:
                # 429 一定是額度視窗還沒重置，精準等到它重置再試，不要馬上連續重試
                wait = _extract_retry_after(err_body)
                print(f"    [限流，等 {wait:.0f} 秒後重試]")
                time.sleep(wait)
            else:
                time.sleep(2.0 * (attempt + 1))
        # TimeoutError/OSError 涵蓋 socket 逾時；URLError 涵蓋其他 HTTP 層錯誤；
        # KeyError/IndexError 涵蓋回應格式不如預期（例如被安全過濾器擋掉沒有 candidates）
        except (urllib.error.URLError, KeyError, IndexError,
                TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    raise GeminiError(f"呼叫 Gemini 失敗（重試 {retries} 次後放棄）：{last_err}")


def translate_batch(texts: list, note: str = "商品/品牌名稱") -> list:
    """
    批次翻譯成繁體中文。品牌/專有名詞用音譯或保留常見中文慣用譯名，不要逐字直譯
    （修正舊版翻譯把「コスメデコルテ」譯成「美容肩部」這種錯誤）。
    """
    if not texts:
        return []

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = f"""你是專業的日韓美妝商品翻譯。把以下 {len(texts)} 個{note}翻譯成繁體中文。

規則：
- 這些是化妝品/保養品的品牌名稱或商品名稱（原文可能是日文或韓文）
- 品牌名稱、專有名詞（公司名、系列名）要用音譯或市場上常見的中文慣用譯名，不要逐字直譯意思
  （錯誤示範：「コスメデコルテ」不要翻成「美容肩部」，正確是「黛珂」；「라운드랩」不要翻成「圓形包裹」，正確是「Round Lab」）
- 商品名稱正常翻譯，但保留品牌名、產品類型、規格數字（例如 ml、色號）
- 如果本來就是英文或看不出來要怎麼翻，保留原文即可
- 回傳純 JSON 字串陣列，順序要跟輸入完全一致，不要加任何說明文字、不要加 markdown

輸入：
{numbered}

回傳格式：["翻譯1", "翻譯2", ...]"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    if not isinstance(result, list) or len(result) != len(texts):
        raise GeminiError(f"Gemini 回傳格式不對：預期 {len(texts)} 筆，實際 {result!r}")
    return [str(x) for x in result]


def summarize_reviews(product_name: str, brand: str, reviews: list) -> dict:
    """
    reviews: [{"title": str, "raw_text": str, "sentiment": "positive"/"negative"}]
    回傳 {"summary": "...", "suggested_for": "..."}
    """
    lines = []
    for r in reviews:
        mark = "正評" if r.get("sentiment") == "positive" else "負評"
        text = (r.get("raw_text") or "")[:400]
        lines.append(f"[{mark}] {r.get('title', '')}\n{text}")
    review_block = "\n\n".join(lines)

    prompt = f"""你是美妝顧問。以下是商品「{product_name}」（品牌：{brand}）的真實社群評論（來自 PTT/Dcard）。

評論內容：
{review_block}

請完成兩件事，用繁體中文回答：
1. summary：統整這些評論的重點（優點、缺點、實際使用心得），2-3 句話，語氣自然像朋友推薦，不要條列
2. suggested_for：一句話建議「什麼樣的人適合用這個」（例如膚質、需求、預算取向），根據評論內容判斷，不要空泛

回傳純 JSON，不要加任何說明文字：{{"summary": "...", "suggested_for": "..."}}"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    if "summary" not in result or "suggested_for" not in result:
        raise GeminiError(f"Gemini 回傳缺欄位：{result!r}")
    return result


if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(translate_batch(["코스메데코르테", "라운드랩", "다이브인 토너"], "測試"))
