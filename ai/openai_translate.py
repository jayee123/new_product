"""
OpenAI 翻譯模組：用 gpt-4o-mini 批次把商品/品牌名稱原文（日文/韓文）翻譯成繁體中文。
介面跟 ai/gemini.py 的 translate_batch() 一致，但呼叫 OpenAI Chat Completions API。

**內建硬性預算上限**：每次呼叫 API 後都會累計花費（用 OpenAI 回傳的 usage token 數 ×
gpt-4o-mini 官方定價換算），一旦累計花費達到 BUDGET_CAP_USD，之後任何一次呼叫都會直接丟出
BudgetExceeded，呼叫端（scripts/translate_all_openai.py）接住之後就會停止、把已經翻好的部分
（已經逐批寫回資料庫的）留著，並把進度寫成文件方便下次接著做。
"""
import json
import re
import threading
import time
import urllib.request
import urllib.error

from config import OPENAI_API_KEY

OPENAI_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

# gpt-4o-mini 官方定價（每 1,000,000 tokens，美金）。如果之後漲價/降價要記得更新這裡。
PRICE_PER_M_INPUT = 0.15
PRICE_PER_M_OUTPUT = 0.60

# 使用者要求：整個翻譯任務累計花費一旦達到這個上限就要立刻停止
BUDGET_CAP_USD = 0.5


class OpenAIError(Exception):
    pass


class BudgetExceeded(Exception):
    """累計花費已經達到 BUDGET_CAP_USD，呼叫端要停止並收尾，不要再送新的請求"""

    def __init__(self, total_cost: float):
        self.total_cost = total_cost
        super().__init__(f"累計花費 US${total_cost:.4f} 已達上限 US${BUDGET_CAP_USD}，停止呼叫 OpenAI")


# 全域累計用量／花費，供 get_usage_summary() 給呼叫端寫進度報告用
_total_cost = 0.0
_total_input_tokens = 0
_total_output_tokens = 0
_total_calls = 0
_lock = threading.Lock()  # 多執行緒同時呼叫時，計費累加要上鎖，不然會漏算


def configure_budget(cap_usd: float, already_spent_usd: float = 0.0) -> None:
    """
    設定「累計」預算：cap_usd 是整個任務（可能跨很多次執行）的花費上限，already_spent_usd 是前幾次
    已經花掉的金額（呼叫端從資料庫帳本讀出來）。之後 get_usage_summary()['total_cost_usd'] 就是累計總額。
    """
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
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text)
        text = text.strip()
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj
    except json.JSONDecodeError as e:
        raise OpenAIError(f"OpenAI 回傳不是合法 JSON：{raw[:300]!r}") from e


def _call(prompt: str, retries: int = 2) -> str:
    global _total_cost, _total_input_tokens, _total_output_tokens, _total_calls

    if _total_cost >= BUDGET_CAP_USD:
        raise BudgetExceeded(_total_cost)

    if not OPENAI_API_KEY:
        raise OpenAIError("OPENAI_API_KEY 沒設定，去 .env 補上")

    body = json.dumps({
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }).encode("utf-8")

    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                OPENAI_URL,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())

            usage = data.get("usage", {}) or {}
            in_tok = usage.get("prompt_tokens", 0)
            out_tok = usage.get("completion_tokens", 0)
            cost = in_tok / 1_000_000 * PRICE_PER_M_INPUT + out_tok / 1_000_000 * PRICE_PER_M_OUTPUT
            with _lock:
                _total_cost += cost
                _total_input_tokens += in_tok
                _total_output_tokens += out_tok
                _total_calls += 1

            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            last_err = f"HTTP {e.code}: {err_body[:300]}"
            if e.code == 429:
                print("    [限流，等 10 秒後重試]")
                time.sleep(10)
            else:
                time.sleep(2.0 * (attempt + 1))
        except (urllib.error.URLError, KeyError, IndexError,
                TimeoutError, OSError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
    raise OpenAIError(f"呼叫 OpenAI 失敗（重試 {retries} 次後放棄）：{last_err}")


def translate_batch(texts: list, note: str = "商品/品牌名稱") -> list:
    """
    批次翻譯成繁體中文。品牌/專有名詞用音譯或保留常見中文慣用譯名，不要逐字直譯。
    """
    if not texts:
        return []

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = f"""你是專業的日韓美妝商品翻譯。把以下 {len(texts)} 個{note}翻譯成繁體中文。

規則：
- 這些是化妝品/保養品的品牌名稱或商品名稱（原文可能是日文或韓文，也可能混雜英文）
- 品牌名稱、專有名詞（公司名、系列名）要用音譯或市場上常見的中文慣用譯名，不要逐字直譯意思
  （錯誤示範：「コスメデコルテ」不要翻成「美容肩部」，正確是「黛珂」；「라운드랩」不要翻成「圓形包裹」，正確是「Round Lab」）
- 商品名稱正常翻譯，但保留品牌名、產品類型、規格數字（例如 ml、色號）
- **只要原文裡有日文假名（ひらがな/カタカナ）或韓文字母，就一定要把那個部分實際翻成中文，
  不可以整串原封不動照抄回傳**（例如「タカミ 公式ショップ楽天市場店」要翻成「TAKAMI 官方商店 樂天市場店」
  這樣，「公式ショップ」「楽天市場店」這種常見詞一定要翻，不能因為前面是品牌名就整串跳過不翻）
- 只有整段完全是英文字母/數字、看不出來是哪種語言的部分，才可以保留原文
- 回傳一個 JSON 物件，格式為 {{"translations": ["翻譯1", "翻譯2", ...]}}，陣列順序要跟輸入完全一致，
  不要加任何說明文字

輸入：
{numbered}"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    items = result.get("translations") if isinstance(result, dict) else result
    if not isinstance(items, list) or len(items) != len(texts):
        raise OpenAIError(f"OpenAI 回傳格式不對：預期 {len(texts)} 筆，實際 {result!r}")
    return [str(x) for x in items]


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
        raise OpenAIError(f"OpenAI 回傳格式不對：{result!r}")
    # 改用「編號→情緒」而不是要求陣列剛好 N 筆：gpt-4o-mini 一批 20 則時常常多一筆或少一筆，
    # 用陣列長度驗證會整批作廢（2026-09-21 實測 40 批全部失敗）。漏掉的編號回傳 None。
    valid = {"positive", "negative", "mixed"}
    out = [result.get(str(i)) if result.get(str(i)) in valid else None for i in range(1, len(texts) + 1)]
    if all(x is None for x in out):
        raise OpenAIError(f"OpenAI 回傳沒有任何可用標籤：{result!r}")
    return out


# 抱怨面向固定 10 類（2026-09-21 使用者確認）；模型回傳不在清單裡的一律歸「其他」
COMPLAINT_ASPECTS = ["質地", "顏色／色號", "包裝", "容量", "氣味", "刺激過敏", "保濕／效果", "持妝", "價格", "物流", "其他"]
# 2026-09-21 健全檢查發現：彩妝的色差、色號不合被硬塞進「質地」，所以在使用者確認的 10 類之外多加「顏色／色號」（共 11 類）

_KANA_HANGUL = re.compile(r"[぀-ヿ가-힯]")  # 日文假名、韓文字母


def extract_review_aspects(texts: list) -> list:
    """
    逐則評論同時抽出：整體情緒（看文字、不看星等）＋抱怨面向。回傳 list，每則是
    {"sentiment": "positive|negative|mixed", "complaints": [{"aspect": ..., "detail": ...}]}，
    模型漏判的那則回傳 None。用「編號→結果」的物件格式，不要求陣列剛好 N 筆
    （gpt-4o-mini 一批 20 則常多一筆少一筆，用陣列長度驗證會整批作廢）。
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
        raise OpenAIError(f"OpenAI 回傳格式不對：{result!r}")
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
        raise OpenAIError(f"OpenAI 回傳沒有任何可用結果：{result!r}")
    return out


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
        raise OpenAIError(f"OpenAI 回傳缺 cons 欄位：{result!r}")
    return cons.strip()


def summarize_reviews(product_name: str, brand: str, reviews: list) -> dict:
    """
    reviews: [{"title": str, "raw_text": str, "sentiment": "positive"/"negative"}]
    回傳 {"summary": "...", "suggested_for": "..."}。跟 ai/gemini.py 的同名函式介面一致，
    這裡是 Gemini key 失效後改用的 OpenAI 版本。
    """
    lines = []
    for r in reviews:
        mark = "正評" if r.get("sentiment") == "positive" else "負評"
        text = (r.get("raw_text") or "")[:400]
        lines.append(f"[{mark}] {r.get('title', '')}\n{text}")
    review_block = "\n\n".join(lines)

    prompt = f"""你是美妝顧問。以下是商品「{product_name}」（品牌：{brand}）的真實社群評論。

評論內容：
{review_block}

請完成兩件事，用繁體中文回答：
1. summary：統整這些評論的重點（優點、缺點、實際使用心得），2-3 句話，語氣自然像朋友推薦，不要條列
2. suggested_for：一句話建議「什麼樣的人適合用這個」（例如膚質、需求、預算取向），根據評論內容判斷，不要空泛

回傳一個 JSON 物件：{{"summary": "...", "suggested_for": "..."}}，不要加任何說明文字"""

    raw = _call(prompt)
    result = _parse_json_response(raw)
    if not isinstance(result, dict) or "summary" not in result or "suggested_for" not in result:
        raise OpenAIError(f"OpenAI 回傳缺欄位：{result!r}")
    return result
