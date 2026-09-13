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
