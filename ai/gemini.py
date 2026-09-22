"""
Gemini API 呼叫模組：翻譯 + 評論摘要生成 + 情緒／抱怨面向抽取 + 常見缺點摘要。
對應企劃書「Gemini API（翻譯）」「AI 評論摘要即時生成」這兩項功能，以及 README 10-8
「常見缺點」功能。用原生 REST API（urllib），不裝額外 SDK，跟專案其他地方風格一致。

**免費額度限制**：一開始用 gemini-3.6-flash（最新 preview 模型），實測免費額度
limit=20 且長時間不恢復（疑似極低的每日配額，不是每分鐘），撞到 429 後等再久都沒用。
改用 gemini-3.1-flash-lite（正式版、非 preview）後額度正常很多，連續呼叫沒問題。
如果之後又開始撞 429，一樣是抓「Please retry in N seconds」精準等到視窗重置再重試，
不要連續重試（那樣只會在同一個額度窗口內浪費更多次請求）。

**預算／額度計算**：這支模組目前假設是跑在 Gemini **免費額度**內，所以 _call() 不像
ai/openai_translate.py 那樣用 token 數 × 官方定價換算金額——沒有可靠的定價可以硬編。
configure_budget()/get_usage_summary() 這組介面還是保留（跟 openai_translate.py 一致，
scripts/ 底下的呼叫端不用改邏輯），但每次呼叫算出來的花費固定是 US$0，BUDGET_CAP_USD
實際上不會被撞到；真正的限制是 429 速率限制，交給下面的重試/等待機制處理。
如果之後改用 Gemini 付費層，要記得回來把真正的定價補進 _call() 才能讓預算上限生效。
"""
import json
import re
import threading
import time
import urllib.request
import urllib.error

from config import GEMINI_API_KEY

GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# 免費額度沒有計費，這個上限目前不會被撞到（見上方模組說明）；保留是為了介面跟
# ai/openai_translate.py 一致，之後如果換付費層、把 _call() 裡的定價補上，這個值才會真正生效。
BUDGET_CAP_USD = 2.6

_RETRY_AFTER_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


class GeminiError(Exception):
    pass


class BudgetExceeded(Exception):
    """累計花費已經達到 BUDGET_CAP_USD，呼叫端要停止並收尾，不要再送新的請求。
    免費額度下 _total_cost 固定是 0，理論上不會被丟出來（見模組說明）。"""

    def __init__(self, total_cost: float):
        self.total_cost = total_cost
        super().__init__(f"累計花費 US${total_cost:.4f} 已達上限 US${BUDGET_CAP_USD}，停止呼叫 Gemini")


# 全域累計用量，供 get_usage_summary() 給呼叫端寫進度報告用；多執行緒同時呼叫要上鎖
_total_cost = 0.0
_total_input_tokens = 0
_total_output_tokens = 0
_total_calls = 0
_lock = threading.Lock()


def configure_budget(cap_usd: float, already_spent_usd: float = 0.0) -> None:
    """設定「累計」預算上限（介面跟 ai/openai_translate.py 一致）。免費額度下花費固定是 0，
    already_spent_usd 傳進來也只是原樣存著，不會影響任何行為。"""
    global BUDGET_CAP_USD, _total_cost
    with _lock:
        BUDGET_CAP_USD = cap_usd
        _total_cost = already_spent_usd


def get_usage_summary() -> dict:
    return {
        "total_cost_usd": round(_total_cost, 6),
        "total_input_tokens": _total_input_tokens,
        "total_output_tokens": _total_output_tokens,
        "total_calls": _total_calls,
    }


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
    global _total_input_tokens, _total_output_tokens, _total_calls

    if _total_cost >= BUDGET_CAP_USD:
        raise BudgetExceeded(_total_cost)

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

            usage = data.get("usageMetadata", {}) or {}
            with _lock:
                _total_input_tokens += usage.get("promptTokenCount", 0)
                _total_output_tokens += usage.get("candidatesTokenCount", 0)
                _total_calls += 1
                # 免費額度沒有計費，_total_cost 刻意不累加（見模組頂端說明）

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


def classify_sentiments(texts: list) -> list:
    """
    逐則判斷評論「文字內容」的整體情緒（完全不看星等）：positive / negative / mixed，模型漏判的那則回傳 None。
    nlp/sentiment.py 的模型是中文專用，套在日文、韓文評論上不準，所以日韓評論改用 LLM 直接讀原文判斷。
    """
    if not texts:
        return []
    numbered = "\n".join(f"{i + 1}. {(t or '')[:300].replace(chr(10), ' ')}" for i, t in enumerate(texts))
    prompt = f"""以下是 {len(texts)} 則美妝商品的使用者評論（原文可能是日文或韓文）。
請逐則判斷「評論內文」表達的整體情緒，**只看文字內容，不要猜評論者給了幾顆星**：
- positive：整體滿意、推薦、會回購
- negative：整體不滿、後悔、不推薦、有明顯負面體驗（過敏、無效、品質差等）
- mixed：優缺點並陳，或整體偏保留、有明顯抱怨但仍給予部分肯定

回傳一個 JSON 物件，key 是評論編號（字串），value 是情緒，例如：
{{"1": "positive", "2": "negative", "3": "mixed"}}
必須包含 1 到 {len(texts)} 每一個編號，不要加任何說明文字。

評論：
{numbered}"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    if not isinstance(result, dict):
        raise GeminiError(f"Gemini 回傳格式不對：{result!r}")
    # 改用「編號→情緒」而不是要求陣列剛好 N 筆：LLM 一批 20 則時常常多一筆或少一筆，
    # 用陣列長度驗證會整批作廢。漏掉的編號回傳 None。
    valid = {"positive", "negative", "mixed"}
    out = [result.get(str(i)) if result.get(str(i)) in valid else None for i in range(1, len(texts) + 1)]
    if all(x is None for x in out):
        raise GeminiError(f"Gemini 回傳沒有任何可用標籤：{result!r}")
    return out


# 抱怨面向固定 11 類（2026-09-21 使用者確認，同 ai/openai_translate.py）；模型回傳不在清單裡的一律歸「其他」
COMPLAINT_ASPECTS = ["質地", "顏色／色號", "包裝", "容量", "氣味", "刺激過敏", "保濕／效果", "持妝", "價格", "物流", "其他"]

_KANA_HANGUL = re.compile(r"[぀-ヿ가-힯]")  # 日文假名、韓文字母


def extract_review_aspects(texts: list) -> list:
    """
    逐則評論同時抽出：整體情緒（看文字、不看星等）＋抱怨面向。回傳 list，每則是
    {"sentiment": "positive|negative|mixed", "complaints": [{"aspect": ..., "detail": ...}]}，
    模型漏判的那則回傳 None。用「編號→結果」的物件格式，不要求陣列剛好 N 筆。
    """
    if not texts:
        return []
    numbered = "\n".join(f"{i + 1}. {(t or '')[:300].replace(chr(10), ' ')}" for i, t in enumerate(texts))
    aspects = "、".join(COMPLAINT_ASPECTS)
    prompt = f"""以下是 {len(texts)} 則美妝商品的使用者評論（原文可能是日文、韓文或中文）。
請逐則只根據「評論文字」（不要猜星等）做兩件事：
1. sentiment：整體情緒。positive＝整體滿意；negative＝整體不滿、後悔、不推薦；mixed＝優缺點並陳、或有明顯抱怨但仍有肯定
2. complaints：這則評論提到的缺點或抱怨，每個缺點一筆，含 aspect 與 detail
   - aspect 只能從這 {len(COMPLAINT_ASPECTS)} 個選一個：{aspects}
     各面向的意思：質地＝觸感、黏膩、厚重、乾澀、延展性；顏色／色號＝色差、色號不合、顯色度、氧化變色；
     包裝＝瓶口、幫浦、盒子、開封；容量＝份量太少或太多；氣味＝香味太重或有異味；
     刺激過敏＝刺痛、泛紅、長痘、過敏；保濕／效果＝保濕不足、沒有效果；持妝＝脫妝、掉色、不持久；
     價格＝太貴、不划算；物流＝出貨慢、包裹破損
   - detail：**必須是繁體中文**，15 字內描述具體抱怨，例如「偏黏膩」「瓶口不好擠」「色號偏白」。
     絕對不可以出現日文假名或韓文字母，原文是日文或韓文請自行翻成中文
   - 只有真正的缺點或抱怨才算；單純的使用提醒、中性描述、優點都不要放進來
   - 沒有抱怨就給空陣列

回傳一個 JSON 物件，key 是評論編號（字串），例如：
{{"1": {{"sentiment": "mixed", "complaints": [{{"aspect": "質地", "detail": "偏黏膩"}}]}}, "2": {{"sentiment": "positive", "complaints": []}}}}
必須包含 1 到 {len(texts)} 每一個編號，不要加任何說明文字。

評論：
{numbered}"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    if not isinstance(result, dict):
        raise GeminiError(f"Gemini 回傳格式不對：{result!r}")
    valid_sent = {"positive", "negative", "mixed"}
    out = []
    for i in range(1, len(texts) + 1):
        item = result.get(str(i))
        if not isinstance(item, dict) or item.get("sentiment") not in valid_sent:
            out.append(None)
            continue
        complaints = []
        for c in item.get("complaints") or []:
            if not isinstance(c, dict):
                continue
            aspect = c.get("aspect") if c.get("aspect") in COMPLAINT_ASPECTS else "其他"
            detail = str(c.get("detail") or "").strip()[:30]
            if _KANA_HANGUL.search(detail):
                detail = ""  # 模型沒翻成中文：不顯示那句日韓文，但這則抱怨的面向還是要計入
            complaints.append({"aspect": aspect, "detail": detail})
        out.append({"sentiment": item["sentiment"], "complaints": complaints})
    if all(x is None for x in out):
        raise GeminiError(f"Gemini 回傳沒有任何可用結果：{result!r}")
    return out


def ask_json(prompt: str) -> dict:
    """
    通用的一次性 JSON 呼叫，給不屬於上面幾個固定功能的臨時用途用（例如 ai_image/ 底下的
    圖片 URL 驗證腳本）。prompt 裡要自己講清楚要求 Gemini 回傳什麼格式的 JSON；
    這裡只負責呼叫 + 剝掉 markdown code fence 解出第一個合法 JSON 值，不做欄位驗證，
    呼叫端自己檢查回傳的欄位存不存在。
    """
    raw = _call(prompt)
    return _parse_json_response(raw)


def write_cons_summary(product_name: str, brand: str, aspects: list, n_analyzed: int) -> str:
    """
    把「常見缺點」寫成 1~2 句繁體中文。**只給它程式算好的統計，不給原始評論**，
    所以它只能改寫這些事實，沒有空間自己發揮。aspects: [{"aspect","count","details":[...]}]
    """
    lines = "\n".join(
        f"- {a['aspect']}：{a['count']} 則評論提到" + (f"（例如：{'、'.join(a['details'][:3])}）" if a["details"] else "")
        for a in aspects
    )
    prompt = f"""商品「{product_name}」（品牌：{brand}）共分析 {n_analyzed} 則使用者評論，
統計出下列「至少 2 位不同評論者都提到」的常見缺點：
{lines}

請用繁體中文寫 1~2 句話的「常見缺點」摘要，語氣客觀、像朋友提醒。
規則：只能使用上面列出的缺點與次數，不可加入清單以外的內容，不可誇大（不要寫「大量」「普遍」除非次數很高）。
回傳一個 JSON 物件：{{"cons": "..."}}，不要加任何說明文字。"""
    raw = _call(prompt)
    result = _parse_json_response(raw)
    cons = result.get("cons") if isinstance(result, dict) else None
    if not cons or not isinstance(cons, str):
        raise GeminiError(f"Gemini 回傳缺 cons 欄位：{result!r}")
    return cons.strip()


if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(translate_batch(["코스메데코르테", "라운드랩", "다이브인 토너"], "測試"))
