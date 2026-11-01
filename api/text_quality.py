"""
商品文字品質的共用規則：品質檢查（scripts/quality_check.py）跟實際修正都用這一份，
檢查標準跟修正標準才會一致。

- local_tokens / is_duplicate：用日韓「原文」名稱判斷是不是同一個商品被不同店家重複上架。
  不用中文名稱判斷，因為兩筆中文是分開翻譯的（例：同一個 Integrate 粉底，一筆翻「完美持妝粉底」、
  一筆翻「專業完美粉底液」），中文比對不出來；原文去掉廣告詞後幾乎一樣。
- MAINLAND_TERMS：中國大陸用語（支語）清單，對應台灣用語。
- display_name：前端實際顯示的商品名稱（目前＝原始中文名稱，修正廣告詞後會在這裡清理）。
"""
import re

# 名稱裡的廣告詞特徵（樂天賣家常把促銷文字塞進商品名稱）
PROMO_PATTERN = re.compile(
    r"[＼／★☆◆◇■□●○♪！!＠@%％]|OFF|SALE|ポイント|送料|還元|エントリー|クーポン|最大|限定|"
    r"点数|點數|積分|免運|優惠券|超級特賣|購買時機|倍", re.IGNORECASE)

# 會被整段移除的括號（內容多半是店名、廣告、品牌重複）
_BRACKET_SEGMENT = re.compile(r"【[^】]*】|［[^］]*］|\[[^\]]*\]|〔[^〕]*〕|≪[^≫]*≫|《[^》]*》")
# 只拿掉括號符號、保留內容的括號（內容多半是容量、補充包等有意義的資訊）
_PAREN_CHARS = re.compile(r"[（）()「」『』]")
_SPLIT = re.compile(r"[\s　|｜/／・,，、]+")

# 支語 → 台灣用語
MAINLAND_TERMS = {
    "洗面奶": "洗面乳",
    "面膜貼": "面膜",
    "水乳": "化妝水乳液",
    "視頻": "影片",
    "信息": "資訊",
    "屏幕": "螢幕",
    "軟件": "軟體",
    "網絡": "網路",
    "默認": "預設",
}


_DIGIT = re.compile(r"\d")
_REFILL = re.compile(r"レフィル|リフィル|詰め?替え?|つめかえ|付け替え|付替|리필|refill|補充", re.IGNORECASE)


def local_tokens(name_local: str) -> set:
    """原文名稱 → 去掉廣告詞後的詞集合。
    【】等括號只在內容是廣告時整段拿掉；內容不是廣告的（常是口味、色號，例：天然冷壓油【荷荷巴油】）保留。"""
    s = _BRACKET_SEGMENT.sub(lambda m: " " if PROMO_PATTERN.search(m.group()) else " " + m.group()[1:-1] + " ",
                             name_local or "")
    s = _PAREN_CHARS.sub(" ", s)
    tokens = set()
    for t in _SPLIT.split(s):
        t = t.strip().lower()
        if len(t) < 2 or PROMO_PATTERN.search(t):
            continue
        tokens.add(t)
    return tokens


def is_duplicate(name_local_a: str, name_local_b: str, threshold: float = 0.8) -> bool:
    """同一個商品被不同店家重複上架的判斷（用原文名稱）：
    1. 去掉廣告詞後，較短那個名稱的詞有 ≥ threshold 出現在另一個名稱裡（重疊係數）
    2. 含數字的詞（容量、色號、片數，例：オークル20、10片）較短那邊的都要出現在另一邊
    3. 一個是補充包、一個不是 → 不同商品"""
    a, b = local_tokens(name_local_a), local_tokens(name_local_b)
    if not a or not b:
        return False
    if bool(_REFILL.search(name_local_a or "")) != bool(_REFILL.search(name_local_b or "")):
        return False
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    if not {t for t in small if _DIGIT.search(t)} <= large:
        return False
    return len(small & large) / len(small) >= threshold


def has_promo(name: str) -> bool:
    n = name or ""
    return bool(PROMO_PATTERN.search(n) or _EXTRA_PROMO.search(n) or _BRACKET_SEGMENT.search(n)
                or _DATETIME.search(n) or _DATETIME_ZH.search(n)
                or any(_EXTRA_PROMO.search(t) for t in re.split(r"[\s　]+", n) if t))


def mainland_terms_in(text: str) -> list:
    return [w for w in MAINLAND_TERMS if w in (text or "")]


DISPLAY_NAME_MAX = 50
_SEO_TAIL = re.compile(r"\s+[|｜]\s+.*$")           # 「主名稱 | 關鍵字 關鍵字…」後面那段關鍵字
_PROMO_WRAPPED = re.compile(r"＼[^／]*／|★[^★]*★|☆[^☆]*☆")  # ＼促銷文字／、★促銷★
_EXTRA_PROMO = re.compile(r"免運費|當日發貨|日本國內當日發貨|現貨|包郵|發貨|新客戶|新規|超值|折扣券|折價券|無需登[記錄]|日圓|"
                          r"半價|限時|排名第\s*1|第1名|1位|為止|之前|紀念|突破|最高\d|郵寄配送|直販|樂天週榜|即時排名|必得|申請明信片|"
                          r"^至\d{1,2}/\d{1,2}|^\d{2}\.\d{1,2}\.\d{1,2}新$|^滿\d+$")
# 促銷期間（例：6/4(四) 20:00〜6/11(四) 1:59、20:00 ~ 6/11 09:59止、6月4日20:00〜6日」）
_DATETIME_ZH = re.compile(r"\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2}\s*[~～〜\-]\s*(\d{1,2}月)?\d{1,2}日\s*(\d{1,2}:\d{2})?」?")
_DATETIME = re.compile(r"(\d{1,2}/\d{1,2}\s*([（(][^)）]{1,3}[)）])?\s*)?\d{1,2}:\d{2}\s*[~～〜\-]\s*"
                       r"(\d{1,2}/\d{1,2}\s*([（(][^)）]{1,3}[)）])?\s*)?(\d{1,2}:\d{2})?\s*(止|為止|之前|前|限時)?")
_SUB_SPLIT = re.compile(r"[！!。，,]+")


def _keep_bracket(m) -> str:
    """括號段：短的非廣告內容（口味、色號，例：【荷荷巴油】）保留文字；廣告、店名、關鍵字清單整段拿掉"""
    inner = m.group()[1:-1].strip()
    if (not inner or len(inner) > 12 or re.search(r"\s", inner)
            or PROMO_PATTERN.search(inner) or _EXTRA_PROMO.search(inner)
            or re.search(r"官方|公式|商店|店$|ショップ|^NEW$", inner, re.IGNORECASE)):
        return " "
    return " " + inner + " "


def display_name(name: str) -> str:
    """前端實際顯示的商品名稱：拿掉賣家塞進名稱的廣告詞、關鍵字清單，太長的截斷。
    原始名稱（name_zh）不動，精確搜尋仍然比對原始名稱。"""
    s = name or ""
    # 順序：先拿掉促銷期間、＼…／ ★…★、括號，再切「｜」後的關鍵字（括號裡的「｜」不會被誤切）
    s = _DATETIME_ZH.sub(" ", s)
    s = _DATETIME.sub(" ", s)
    s = _PROMO_WRAPPED.sub(" ", s)
    s = _BRACKET_SEGMENT.sub(_keep_bracket, s)
    s = _SEO_TAIL.sub("", s)
    is_promo = lambda t: bool(PROMO_PATTERN.search(t) or _EXTRA_PROMO.search(t))
    chunks = []
    for c in re.split(r"[\s　]+", s):
        if not c or c.isdigit():          # 拿掉廣告後剩下的單獨數字（例：半價 4,200→2,100 的「4」）
            continue
        if not is_promo(c):
            chunks.append(c)
            continue
        # 含廣告詞的段落用標點再切，只丟含廣告詞的小段（例：超值！6月5日限定！…！HAKU美容膳食補充品90粒）
        chunks.extend(p for p in _SUB_SPLIT.split(c) if p and not p.isdigit() and not is_promo(p))
    if not chunks:
        # 整串沒空白也沒標點、全部被當廣告（2026-10-03 修：舊版直接退回原名＝廣告詞全回來）：只刪廣告字詞本身
        cleaned = PROMO_PATTERN.sub("", _EXTRA_PROMO.sub("", s)).strip(" ・-")
        chunks = [cleaned] if len(cleaned) >= 4 else []
    out = " ".join(chunks).strip(" ・|｜,，、-")
    if not out:                        # 整個名稱都是廣告詞的極端情況：退回原名
        out = (name or "").strip()
    if len(out) > DISPLAY_NAME_MAX:
        cut = out[:DISPLAY_NAME_MAX]
        out = (cut.rsplit(" ", 1)[0] if " " in cut[20:] else cut) + "…"
    return out
