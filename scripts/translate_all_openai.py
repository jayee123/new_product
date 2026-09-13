"""
用 OpenAI gpt-4o-mini 把資料庫裡「所有平台」商品的品牌/名稱原文（日文/韓文）
翻譯成繁體中文，只翻還沒翻過的（brand_zh / name_zh 是空的、或還跟原文一模一樣）。

執行：python -m scripts.translate_all_openai

**硬性預算上限**：累計花費一達到 ai/openai_translate.py 裡設定的 BUDGET_CAP_USD
（目前是 US$0.5），會立刻停止，不會再送出下一批請求。

**可以安全重跑，會自動接續**：
- 每一批翻完就立刻寫回 MongoDB，不會因為中途停止而遺失已經翻好的部分
- 判斷「有沒翻過」是看 name_zh/brand_zh 有沒有值、跟原文是否相同，已經翻好的批次
  重跑這支腳本時會自動跳過，不會重翻、不會重複花錢
- 每次執行完（不管是正常跑完還是撞到預算上限），都會把最新進度寫進專案根目錄的
  TRANSLATION_PROGRESS.md，下次要接手可以先看那份文件
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ai.openai_translate import translate_batch, OpenAIError, BudgetExceeded, get_usage_summary
from db.mongo_client import get_db

BATCH_SIZE = 25
SLEEP_BETWEEN_BATCHES = 1.0

# (source_platform, 給 prompt 用的說明文字)
PLATFORMS = [
    ("rakuten", "日本樂天市場美妝保養"),
    ("oliveyoung", "韓國 Olive Young 美妝保養"),
    ("cosme", "日本 @cosme 美妝保養"),
    ("hwahae", "韓國화해美妝保養"),
]

PROGRESS_FILE = Path(__file__).resolve().parent.parent / "TRANSLATION_PROGRESS.md"

stop_reason = None  # 記錄是正常做完還是撞到預算上限中途停止


def _untranslated_brand_filter(platform: str) -> dict:
    """brand_local 有值，但 brand_zh 是空的或還跟原文一樣，判定為「還沒翻」"""
    return {
        "source_platform": platform,
        "brand_local": {"$ne": ""},
        "$expr": {
            "$or": [
                {"$eq": ["$brand_zh", ""]},
                {"$eq": ["$brand_zh", None]},
                {"$eq": ["$brand_zh", "$brand_local"]},
            ]
        },
    }


def _untranslated_name_filter(platform: str) -> dict:
    return {
        "source_platform": platform,
        "name_local": {"$ne": ""},
        "$expr": {
            "$or": [
                {"$eq": ["$name_zh", ""]},
                {"$eq": ["$name_zh", None]},
                {"$eq": ["$name_zh", "$name_local"]},
            ]
        },
    }


def translate_platform_brands(platform: str, note: str) -> bool:
    """回傳 False 代表撞到預算上限，呼叫端要整個停止，不要再處理下一個平台"""
    global stop_reason
    db = get_db()
    brands = db.products.distinct("brand_local", _untranslated_brand_filter(platform))
    if not brands:
        print(f"[{platform}] 品牌/店名：沒有需要翻譯的（已經翻完，或這個平台本來就沒有品牌欄位）")
        return True

    print(f"[{platform}] 品牌/店名：{len(brands)} 個不重複、還沒翻譯")
    for i in range(0, len(brands), BATCH_SIZE):
        chunk = brands[i:i + BATCH_SIZE]
        print(f"  翻譯第 {i + 1}-{i + len(chunk)} 筆（共 {len(brands)} 筆）...")
        try:
            translated = translate_batch(chunk, note=f"{note}商品的品牌/店名")
        except BudgetExceeded as e:
            stop_reason = str(e)
            print(f"  [預算上限] {e}")
            return False
        except OpenAIError as e:
            print(f"    [這批失敗，跳過，之後可以重跑腳本補上] {e}")
            continue

        for orig, zh in zip(chunk, translated):
            db.products.update_many(
                {"source_platform": platform, "brand_local": orig},
                {"$set": {"brand_zh": zh}},
            )
        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"  [{platform}] 品牌/店名翻譯這輪處理完畢")
    return True


def translate_platform_names(platform: str, note: str) -> bool:
    global stop_reason
    db = get_db()
    products = list(db.products.find(
        _untranslated_name_filter(platform),
        {"_id": 0, "source_url": 1, "name_local": 1},
    ))
    if not products:
        print(f"[{platform}] 商品名稱：沒有需要翻譯的")
        return True

    print(f"[{platform}] 商品名稱：{len(products)} 筆還沒翻譯")
    for i in range(0, len(products), BATCH_SIZE):
        chunk = products[i:i + BATCH_SIZE]
        names = [p["name_local"] for p in chunk]
        print(f"  翻譯第 {i + 1}-{i + len(chunk)} 筆（共 {len(products)} 筆）...")
        try:
            translated = translate_batch(names, note=f"{note}商品名稱")
        except BudgetExceeded as e:
            stop_reason = str(e)
            print(f"  [預算上限] {e}")
            return False
        except OpenAIError as e:
            print(f"    [失敗，跳過這批] {e}")
            continue

        for p, zh in zip(chunk, translated):
            db.products.update_one({"source_url": p["source_url"]}, {"$set": {"name_zh": zh}})
        time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"  [{platform}] 商品名稱翻譯這輪處理完畢")
    return True


def write_progress_report(completed: bool):
    db = get_db()
    usage = get_usage_summary()

    lines = [
        "# 翻譯進度報告（OpenAI gpt-4o-mini）",
        "",
        f"最後更新：{datetime.now(timezone.utc).isoformat()}",
        "",
        f"本次執行花費：US${usage['total_cost_usd']:.4f}"
        f"（input tokens={usage['total_input_tokens']}，"
        f"output tokens={usage['total_output_tokens']}，呼叫次數={usage['total_calls']}）",
        "",
    ]

    if completed:
        lines.append("**狀態：這一輪所有平台都處理過了，沒有撞到預算上限。**")
        lines.append("")
        lines.append("如果下面「各平台剩餘未翻譯數量」還有非 0 的項目，代表那些批次呼叫 OpenAI 失敗被跳過了")
        lines.append("（例如逾時、格式錯誤），直接重跑 `python -m scripts.translate_all_openai` 補翻即可。")
    else:
        lines.append(f"**狀態：因為累計花費撞到預算上限（US${0.5}）中途停止。**")
        lines.append("")
        lines.append(f"停止原因：{stop_reason}")
        lines.append("")
        lines.append("## 下次怎麼接著做")
        lines.append("")
        lines.append("1. 如果要繼續翻，先去 `ai/openai_translate.py` 把 `BUDGET_CAP_USD` 調高")
        lines.append("2. 直接重新執行：`python -m scripts.translate_all_openai`")
        lines.append("3. 這支腳本判斷「有沒翻過」的方式是看 name_zh/brand_zh 是不是空的或跟原文一樣，")
        lines.append("   已經翻好的會自動跳過，不會重翻、不會重複花錢，只會接著翻還沒翻的部分")

    lines.append("")
    lines.append("## 各平台剩餘未翻譯數量（跑完這次之後）")
    for platform, _ in PLATFORMS:
        remain_brand = len(db.products.distinct("brand_local", _untranslated_brand_filter(platform)))
        remain_name = db.products.count_documents(_untranslated_name_filter(platform))
        lines.append(f"- {platform}：品牌/店名剩 {remain_brand} 個未翻譯，商品名稱剩 {remain_name} 筆未翻譯")

    PROGRESS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n進度報告已寫入 {PROGRESS_FILE}")


if __name__ == "__main__":
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    completed = True
    for platform, note in PLATFORMS:
        if not translate_platform_brands(platform, note):
            completed = False
            break
        if not translate_platform_names(platform, note):
            completed = False
            break

    write_progress_report(completed)
    usage = get_usage_summary()
    print(f"\n=== 執行結束，本次總花費 US${usage['total_cost_usd']:.4f} ===")
