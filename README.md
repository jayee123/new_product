## 🚀 測試前必看：需要裝哪些套件、大概要多少空間

**只要跑 API／前端 Demo（不需要重新爬蟲）**：
```
git clone https://github.com/jayee123/new_product.git
cd new_product
pip install -r requirements.txt
```
套件安裝後**約佔 1.5～2 GB 硬碟空間**，其中比較大的幾個：

| 套件 | 大小 | 用途 |
|---|---|---|
| torch | 1.1 GB | LSTM／LLM 相關運算 |
| transformers | 78 MB | Hugging Face 模型 |
| pandas | 60 MB | 資料處理 |
| playwright（Python 套件本身） | 108 MB | 爬蟲框架 |
| numpy | 30 MB | 數值運算 |
| 其餘（chromadb／pymongo／sentence-transformers／openai／fastapi 等） | 共約 40 MB | RAG、API、資料庫 |

**如果還要跑爬蟲（`scrapers/oliveyoung_scraper.py` 等）**，另外要執行 `playwright install` 下載瀏覽器二進位檔，**再多佔約 1.4 GB**——只是要測試 API/Demo 的話**不需要做這一步**。

複製 `.env.example` 改名成 `.env`，填入需要的 API key（MongoDB／Gemini／MySQL，跟我要或參考下面說明），啟動指令：
```
python -m uvicorn api.main:app --port 8000
```
瀏覽器打開 `http://localhost:8000/` 即可測試。

---

# Buy託了AI 專案進度總表

> **這是這個專題的唯一進度依據。** 每次要接手做事之前先看這份，做完事情要回來更新這份。
> 不要相信任何其他地方寫的數字/狀態（包括對話紀錄、其他 .md 手寫的提示詞），以這份為準，
> 有疑問就直接查 MongoDB 現況，不要用猜的或用記憶裡的舊數字。

最後更新：2026-08-30（實際數字用下面指令查證過）

> 正式的畢業專題企劃書內容以 `專題計劃書摘要.pdf`（作者本機保存，未收錄進本 repo）為準，PDF 裡有幾項現在系統還沒做的功能，列在下面「PDF 有寫但還沒做的功能」一節。

在 repo 根目錄執行以下指令，查驗資料庫實際筆數（需要先設定好 `.env` 裡的 `MONGO_URI`）：

```bash
python -c "
from db.mongo_client import get_db
db = get_db()
print('products:', db.products.count_documents({}))
for p in db.products.distinct('source_platform'):
    print(' ', p, db.products.count_documents({'source_platform': p}))
print('reviews:', db.reviews.count_documents({}))
for s in db.reviews.distinct('source'):
    print(' ', s, db.reviews.count_documents({'source': s}))
print('reviews with sentiment:', db.reviews.count_documents({'sentiment':{'\$ne':None}}))
print('reviews with product_id:', db.reviews.count_documents({'product_id':{'\$ne':None}}))
"
```

---

## 1. 專案是什麼

日韓藥妝智慧推薦系統。整合官方商品 API + 社群評論，用情緒分析 + RAG 向量搜尋，依膚質/預算/需求推薦日韓藥妝。

## 2. 資料現況（已驗證，2026-07-31）

**products collection：1973 筆**

| source_platform | 筆數 | 說明 |
|---|---|---|
| rakuten | 1116 | 日本，Rakuten Ichiba API，含平台評分/評論數 |
| oliveyoung | 424 | 韓國，Playwright 爬蟲，415 筆有評分、367 筆有成分表 |
| cosme | 346 | 日本口碑榜單，只有排名/評分，無成分表/說明 |
| hwahae | 87 | 韓國口碑榜單，只有排名/評分，無成分表/說明（原始 CSV 860 列，去重後只有 87 個不重複商品，屬正常） |

**reviews collection：150 筆**

| source | 筆數 |
|---|---|
| ptt | 99 |
| dcard | 51 |

- 150 篇全部跑過情緒分析（`sentiment` 已填）
- 144 篇成功配對到商品（`product_id` 已填），剩 6 篇是板規公告/閒聊文，本來就不該配對成功

**RAG 向量索引**：`chroma_db`，1973 個商品都建了索引，用餘弦相似度（cosine，不是預設的 L2，見下方踩過的坑），metadata 裡含 `category`/`source_platform`/`rating_platform`/`review_count_platform`，供 API 篩選用。

## 3. 統一 schema

商品欄位定義在 `scrapers/product_schema.py`：

```
source_platform, source_id, source_url,
name_local, name_zh, brand_local, brand_zh,
category, price, currency,
image_url, description, ingredients,
rating_platform, review_count_platform, capacity, scraped_at
```

四個平台各自的 `normalize_xxx(row)` 函式都在這支檔案裡（`normalize_rakuten` / `normalize_oliveyoung` / `normalize_cosme` / `normalize_hwahae`）。

對應的匯入腳本在 `scrapers/`：`rakuten_scraper.py`、`oliveyoung_scraper.py`、`cosme_scraper.py`、`hwahae_scraper.py`，每支都支援 `--csv <path>`（讀既有 CSV 匯入）。

## 4. 已完成

- [x] 商品資料：Rakuten + Olive Young（含詳細頁評分/評論數/成分表）
- [x] 口碑補充：@cosme + 화해
- [x] 評論資料：PTT + Dcard
- [x] 統一欄位 schema，四個商品來源都用同一套
- [x] 情緒分析（`nlp/sentiment.py`，uer/roberta 中文模型）
- [x] RAG 向量索引（`rag/embedder.py`，sentence-transformers + ChromaDB，餘弦相似度）
- [x] 評論 ↔ 商品配對
- [x] `demo_runner.py` 一鍵驗證腳本（**不含 iHerb，iHerb 已確認不用，不要再爬**）
- [x] FastAPI `/recommend` API（`api/`，見第 3-1 節）
- [x] 前端頁面（`frontend/index.html`，見第 3-2 節）
- [x] 推薦清單排序切換（相關度/好評率/價格），對應 FR9
- [x] 會員系統（MySQL + JWT，註冊/登入/登出），對應 FR3，見第 3-1b 節
- [x] 品牌別名聚類 + 跨平台去重基礎建設（`scripts/brand_dedup.py`），對應第二階段「資料清洗」，見第 3-3 節
- [x] Rakuten 成分表解析（`_parse_ingredients_ja()`），155/1116 筆（13.9%）解析成功，受限於舊版 200 字截斷，等重新爬才會提高（仍卡在沒有 Rakuten API key，見第 5 節）
- [x] 前端登入/註冊/登出畫面，接上會員系統 API
- [x] **Gemini API 翻譯**（`ai/gemini.py` + `scripts/translate_data.py`），2026-08-24 完成，見第 3-4 節
- [x] **AI 評論摘要**（`scripts/generate_review_summaries.py`），批次預先生成存回 `products.ai_summary`，2026-08-24 完成，見第 3-4 節

### 3-1. `/recommend` API

- 檔案：`api/main.py`（FastAPI app）+ `api/recommend.py`（推薦邏輯：語意搜尋 + 預算/國家/分類篩選 + 評論好評率）
- 啟動：`python -m uvicorn api.main:app --port 8000`（在 repo 根目錄執行）
- 互動文件：http://localhost:8000/docs
- `GET /health` → `{"status":"ok","products":N,"reviews":N}`
- `POST /recommend`，body：
  ```json
  {"query": "乾性肌保濕精華，預算500以內", "budget": 500, "country": "JP", "category": "精華", "top_k": 10}
  ```
  `query` 必填，其他都選填。`budget` 是跟商品原幣別比較（不做匯率換算，JP 商品用 JPY、KR 商品用 KRW），`country` 是 `"JP"`/`"KR"`。已測試過語意搜尋 + 篩選都正確（country=KR + budget≤20000 只會回傳符合的商品）。
- 每筆結果除了商品資料，還會帶 `sample_reviews`（最多 3 篇實際配對到的評論標題/來源/情緒）+ `sentiment_positive`/`sentiment_negative` 好評壞評數，商品跟評論資料是一起回傳的，不是只有數字。
- API 沒有設定成開機自動啟動，**每次要用都要手動下指令重開**，伺服器不會自己一直開著（這是預期行為，不是壞掉）。
- **`--reload` 在這台機器上不可靠**：保險做法是**改完 `api/` 底下的檔案，一律整個關掉背景的 uvicorn process 再重新啟動**，不要依賴 `--reload` 自動生效，啟動指令不用加 `--reload`：`python -m uvicorn api.main:app --port 8000`。
- `/recommend` 支援 `sort_by` 參數：`"relevance"`（預設，語意相關度）/ `"rating"`（好評率高→低）/ `"price_low"` / `"price_high"`。好評率＝`sentiment_positive/(sentiment_positive+sentiment_negative)`，回應裡是 `sentiment_pos_rate` 欄位（0~1 之間，沒有配對到評論的商品是 `None`，排序時會排最後面，不會因為「沒負評」誤判成最高好評率）。

### 3-1b. 會員系統（MySQL + JWT）— 2026-08-16 完成，2026-08-30 MySQL 遷移到雲端（Aiven）

對應企劃書 FR3、程序規格書-3。跟商品/評論資料完全獨立，不參與 `/recommend` 推薦流程。

- **MySQL 環境（2026-08-30 更新：已從本機搬到雲端）**：原本是這台電腦本機的 MySQL，**現在已經搬到 [Aiven](https://aiven.io) 的雲端 MySQL 服務**（免費方案，MySQL 8.4.8，永久免費非限時試用，不用信用卡，見第 6 節「為什麼選 Aiven」的比較）。
  - 好處：跟 MongoDB（已經是 Atlas 雲端）一樣不用再手動開本機服務，之後部署到 PaaS 平台時，雲端 API 服務才連得到這個 MySQL（本機版連不到，PaaS 伺服器跟你的電腦是兩台不同機器）
  - 本機版保留當備用（本機開發、Aiven 連不上時的 fallback），但現在 `.env` 預設指向 Aiven，正常情況不用再手動啟動本機 MySQL 了
- **連線資訊**：都在 `.env` 的 `MYSQL_*` 那幾行，資料庫名稱 `MYSQL_DB=buytuoleai_auth`，是自己在 Aiven 上 `CREATE DATABASE` 建的，免費方案雖然預設只給一個 `defaultdb`，但實測**可以自己額外建資料庫**
- **權限退化，已知取捨**：本機版原本刻意用一個非 root、只開放單一資料庫權限的帳號連線；Aiven 免費方案目前只給 `avnadmin` 這一個帳號，等於是整個 MySQL 服務的管理者權限，沒辦法比照本機版建一個權限受限的專用帳號。對這個規模的展示型專案風險可接受，但如果之後要正式營運要注意這點
- **Aiven 強制要求 TLS 連線**，`db/mysql_client.py` 的 `get_connection()` 已加上 `ssl={"ssl": {}}` 參數，本機 MySQL 沒有這個要求但加了不影響
- **2026-09-13：Aiven 連不上了，已切回本機 XAMPP MySQL 當備用**。當時預留的 fallback 這次真的用上了：
  `mysql-114a23-jay2004931101-ec0f.d.aivencloud.com` 這個主機名稱 DNS 完全解析不到（其他外部連線，
  像 MongoDB Atlas，都正常，確認不是本機網路問題，應該是 Aiven 免費方案閒置太久被暫停或服務被刪了）。
  改用 `C:\xampp\mysql` 的本機 MariaDB 10.4.32，`.env` 的 `MYSQL_*` 已改回本機設定
  （`127.0.0.1:3306`，`root` 帳號無密碼——這台是個人開發機，風險可接受，正式環境不能這樣設）。
  `buytuoleai_auth` 資料庫 + `users`/`revoked_tokens`/`search_history` 三張表都是照 `auth/service.py`
  的 SQL 語法重新反推建的（原本沒有留 schema 建立腳本），完整測過註冊/重複註冊擋掉/登入/查詢紀錄/
  登出/重複登出擋掉，全部正常。**下次如果要改回 Aiven，先去 Aiven 主控台確認服務有沒有復活，
  有的話把 `.env` 裡註解掉的那組 Aiven 連線字串換回來就好。**
- 三張表：`users`（id/email/password_hash/created_at，密碼用 **bcrypt** 雜湊，不是明文）、`revoked_tokens`（存已登出的 JWT jti，讓登出真的有效果，不是只是前端假裝清掉）、`search_history`（見下面 3-1d 節）
- 邏輯在 `auth/service.py`（`register()`/`login()`/`decode_token()`/`logout()`），API 路由在 `api/main.py` 的 `/auth/register`、`/auth/login`、`/auth/logout`
- 已經測過完整流程：註冊 → 重複註冊被擋 → 密碼錯誤被擋 → 登入拿到 JWT → 登出 → 同一個 token 再登出一次會被擋（因為已經在 `revoked_tokens` 裡）。搬到 Aiven 後也重新測過一次註冊+登入端到端，成功拿到 JWT。
- **登入鎖定決策**：不硬鎖 `/recommend`（不登入也能搜），但登入後會多一個「搜尋紀錄只有自己看得到」的實際功能，讓登入這件事有看得見的價值，同時不會因為 MySQL 沒開而讓整個搜尋功能掛掉。見下面「搜尋紀錄」小節。

### 3-1d. 搜尋紀錄（登入才有的功能）— 2026-08-23 完成

- 新增 MySQL 表 `search_history`（user_id / query / country / budget / category / created_at）。
- `POST /recommend` 現在會讀 `Authorization` header（**選填**，沒帶或 token 失效都不影響搜尋本身），有帶合法 token 就把這次查詢悄悄記錄下來。
- 新增 `GET /auth/history`（**必須登入**，沒 token 回 401）回傳該使用者的搜尋紀錄，最新的在前面。
- 前端：登入後右上角多一個「🕘 我的搜尋紀錄」按鈕，點開會列出過去的查詢，點一筆可以直接重新搜尋一次。

### 3-1c. 台幣即時匯率換算 — 2026-08-23 完成

- 檔案：`currency.py`，用 `open.er-api.com`（免費、**不用申請 API key**、每天更新一次）抓 TWD 對其他幣別的匯率，本機快取 12 小時，不會每個請求都打外部 API。
- `api/recommend.py` 的每筆結果現在回傳 `price_twd`（換算後台幣，主要顯示用）+ `price_original`/`currency_original`（原幣別，次要參考）。
- **`budget` 篩選跟 `sort_by=price_low/price_high` 排序，現在都是比較台幣金額**，不再是直接比 JPY/KRW 原始數字。
- 匯率 API 打不通時（沒網路、對方掛掉）會回傳 `price_twd: null` 而不是讓整個 `/recommend` 掛掉，但那樣 budget 篩選會把該商品濾掉（因為判斷不了是否在預算內），要注意這個邊界情況。

### 3-2. 前端

- 檔案：`frontend/index.html`（單一檔案，純 HTML/CSS/JS，沒有建置工具，直接雙擊在瀏覽器打開就能用）
- 呼叫 `http://localhost:8000/recommend`，已加 CORS
- 有搜尋框、國家/預算/分類篩選、5 個實測過資料最完整的建議查詢按鈕
- 排序下拉選單（相關度／好評率高→低／價格低→高／高→低），對應企劃書 FR9
- 商品卡片會顯示圖片/名稱/品牌/價格/平台評分，下面附最多 3 篇實際配對到的評論標題 + 情緒 + 來源 + 好評率百分比
- API 沒開的時候會顯示清楚的錯誤訊息，不會整頁空白
- **登入/註冊畫面**：右上角「登入／註冊」按鈕，登入成功後 token 存在 `localStorage`

### 3-3. 品牌別名對照表 + 跨平台商品去重 — 2026-08-24 重跑，翻譯補上後有改善

對應企劃書第二階段「資料清洗與跨語言商品配對」。程式在 `scripts/brand_dedup.py`，執行：`python -m scripts.brand_dedup`。

做兩件事：
1. `build_brand_aliases()`：把所有商品的 `brand_zh`（中文品牌名）用 `rapidfuzz.fuzz.ratio()` 聚類（門檻 85 分），相近的字串歸成同一個「統一品牌」，寫進新的 `brand_aliases` collection，並把每個商品標上 `brand_canonical` 欄位。
2. `find_cross_platform_duplicates()`：在同一個統一品牌底下，用 `rapidfuzz.fuzz.token_sort_ratio()`（門檻 80 分）比對不同平台的商品名稱，抓出疑似同一款商品在多個平台上架的組合，寫進 `product_duplicates` collection。

**2026-08-24 重跑結果（Gemini 翻譯補上後）：358 個不重複品牌名稱 → 聚成 358 組，2 組有 2 個以上別名（跨平台品牌統一成功），仍是 0 組跨平台重複商品。**

品牌聚類確實改善了：找到 `colorgram`/`Colorgram`（hwahae + oliveyoung）、`beplain`/`Beplain`（hwahae + oliveyoung）兩組跨平台同一品牌的別名，證實翻譯補上後 `rapidfuzz` 真的能比對出原本比不出來的品牌。

跨平台**商品**重複仍是 0 組，原因是各平台商品命名風格差異很大（Olive Young 商品名常帶「企劃組」「+贈品」等長串修飾語，cosme/화해 只有簡短商品名），**這不是 bug，是資料本身的限制**，之後想改善的方向是比對時只取商品名的核心部分再比對。

Rakuten（1116 筆，佔資料庫最大宗）目前完全沒進到這個比對流程，因為它的 `brand_zh` 本來就是空的。

### 3-4. Gemini API 翻譯 + AI 評論摘要 — 2026-08-24 完成

對應企劃書「Gemini API（翻譯）」與「AI 評論摘要」兩項功能。程式：`ai/gemini.py`（核心呼叫模組）、`scripts/translate_data.py`（翻譯批次腳本）、`scripts/generate_review_summaries.py`（評論摘要批次腳本）。

**翻譯部分**（`python -m scripts.translate_data`）：
- Olive Young `name_zh`（商品名稱）：原本完全沒翻譯，現在 **424/424** 全部翻好
- Olive Young `brand_zh`（品牌名稱）：**415/424** 翻好，剩 9 筆是 `brand_local` 本來就是空字串
- cosme `brand_zh` 重譯：**152/152** 個不重複品牌，更新 275 筆商品
- 화해 `brand_zh` 重譯：**62/62** 個不重複品牌，更新 83 筆商品
- 已知誤譯案例驗證修復：「コスメデコルテ」（COSME DECORTE）原本被舊版翻譯誤譯成「美容肩部」，現在正確譯成「黛珂」；「라운드랩」（Round Lab）原本誤譯成「圓形包裹」，現在正確保留品牌名「Round Lab」

**AI 評論摘要部分**（`python -m scripts.generate_review_summaries`）：
- 有配對到評論的商品共 96 個，**96/96** 全部成功生成，寫回 `products.ai_summary`（`{summary, suggested_for, generated_at}`），是**批次預先生成**，`/recommend` 只是讀取現成欄位，不會每次即時呼叫 Gemini
- `api/recommend.py` 每筆結果新增 `ai_summary` 欄位；前端優先顯示 AI 摘要 + 建議適合族群，沒有摘要的商品會 fallback 回原本的評論標題列表

## 5. 還沒做（照優先順序）

1. **部署**（Render.com / GitHub Pages）— API 服務本身還沒上雲端（前端還是本機檔案 + 本機跑的 API），但**兩個資料庫都已經是雲端的了**（MongoDB Atlas + 2026-08-30 新遷移的 Aiven MySQL，見第 3-1b 節），少的只是把 FastAPI 服務本身也部署上去這一步
2. 資料清洗：
   - **Rakuten 成分表仍只有 155/1116 筆（13.9%）解析得出來**，卡在需要 Rakuten API key（目前仍然沒有）才能重爬取得完整資料
3. API 效能：實測 3180ms，超過 NFR1 的 500ms 標準 6 倍，主因是每筆結果對 MongoDB Atlas 多打 3 次查詢，要改成一次 aggregation
4. 跨平台商品去重：品牌翻譯已補上但仍是 0 組，卡在商品命名風格差異
5. P2 加分項（不急）：GPT-4o 商品摘要、Whisper 影片轉錄、Demo 影片

## 6. 踩過的坑（不要重踩）

- **iHerb 不要爬。** 跟企劃書的 Rakuten/Olive Young 無關，已從 `demo_runner.py` 移除。
- **`import_to_mongodb.py` 不要用。** 邏輯有問題：不管來源全部標成 `source_platform: "mixed"`、覆蓋時會把欄位清空。
- **ChromaDB 預設距離是 L2 不是 cosine**，`similarity = 1 - distance` 在預設設定下會算出負數。`embedder.py` 的 `get_or_create_collection()` 已加上 `metadata={"hnsw:space": "cosine"}` 修正。
- **Python 環境是全域共用的，不是 venv。** numpy 要保持 `<2`（跟 torch 相容）。
- **Olive Young 爬蟲容易被 Cloudflare 擋**，尤其短時間內開很多次 headless Playwright session。
- **Dcard 爬蟲需要手動登入的 Chrome**，透過 `--remote-debugging-port` 連上去。
- **Rakuten API 目前沒有 key**，只能用既有 CSV 匯入。
- **ChromaDB metadata 不接受 `None`**，缺值要轉成 sentinel（`-1`/`-1.0`/`0`）。
- **cosme 的「價格」欄位常常是多規格並列**，已加 `_to_price_jpy()` 抓第一個金額。
- **批次寫資料庫一定要「每批寫一次」，不要累積到最後才寫。** 曾經因為累積寫入 + 中途崩潰，白做了 175 筆翻譯。
- **Gemini 免費額度：不同模型差很多。** `gemini-3.6-flash`（preview）額度很低，改用 `gemini-3.1-flash-lite`（正式版）額度正常很多。
- **Gemini 就算要求 JSON 回應也可能夾雜 markdown fence**，要用 `JSONDecoder().raw_decode()` 而不是直接 `json.loads()`。
- **`python script.py` 不會把當前目錄加進 `sys.path`**，一律用 `python -m scripts.xxx` 執行。
- **為什麼選 Aiven 當雲端 MySQL**：比較過 AWS RDS、Google Cloud SQL、Supabase、TiDB Cloud、Aiven。AWS RDS 2025/7/15 後新帳號已無 12 個月免費、GCP Cloud SQL 完全沒有永久免費方案、Supabase 底層是 PostgreSQL 不是 MySQL、TiDB Cloud 底層是協定相容但非真 MySQL。**Aiven 是唯一「真 MySQL + 永久免費 + 不用信用卡」的選項**。
- **Aiven（以及大多數雲端 MySQL）強制要求 TLS 連線**，`pymysql.connect()` 要手動加 `ssl={"ssl": {}}` 參數。

## 7. 下次接手時該怎麼做

1. 先跑第 2 節開頭的驗證指令，確認實際數字，不要相信這份文件寫的數字沒過期
2. 對照第 5 節「還沒做」清單，挑一項開始
3. 做完之後回來更新這份文件的第 2、4、5 節
4. 如果又發現什麼踩坑的事，補進第 6 節，下次才不會重踩

## 8. PDF 有寫但還沒做的功能

企劃書（`專題計劃書摘要.pdf`）跟現在系統對照後發現這些落差：

| 企劃書內容 | 現況 |
|---|---|
| **翻譯／評論摘要用 Gemini API** | ✅ 已完成。翻譯（Olive Young 全量 + cosme/화해 品牌重譯）跟評論摘要都做完了，評論摘要是**批次預先生成存 `products.ai_summary`**，不是即時呼叫 |
| **會員系統**（FR3）：MySQL + JWT | ✅ 已完成，含搜尋紀錄，前端也接上了 |
| **品牌別名對照表 + rapidfuzz 跨語言去重** | ✅ 翻譯補上後重跑，品牌聚類有改善，商品去重仍 0 組（命名風格差異，非翻譯問題） |
| **每 3 日自動排程爬蟲**（FR10） | 沒做，實務上很難全自動：Olive Young 容易被擋、Dcard 需要人手動登入 |
| **NFR1：API 回應時間 < 500ms** | ❌ 實測 3180ms，超標 6 倍，主因是每筆結果對 MongoDB Atlas 多打 3 次查詢 |
| **排序切換（FR9）** | ✅ 已完成 |

## 9. 2026-09-12 使用者實測回報：評論資料覆蓋率不足 + 排序異常

**2026-09-13 更新：9-1 排序異常已修正**（`api/recommend.py`，改成兩層排序：有社群評論的排前面，
沒有的用平台星等當次要依據），驗證過防曬乳搜尋案例排序恢復正常。9-2/9-3 評論覆蓋率/擴充爬蟲的部分
還沒處理，見下面。

用戶實際操作前端時發現：搜尋防曬乳、排序選「好評率高→低」，結果第一名商品顯示的星等卻只有 ★2.4，
排在後面的反而是 ★4.6、★4.7，看起來像排序整個是亂的；同時發現很多商品（尤其樂天）完全沒有配對到
社群評論。已經查證過根本原因，記錄如下，**還沒動手修，等下次接手時處理**。

### 9-1. 排序異常：根本原因是「好評率」跟「平台星等」是兩個不同欄位，被使用者混淆

- 排序選單的「好評率高→低」（`sort_by=rating`）排序依據是 `sentiment_pos_rate`
  （PTT/Dcard 社群評論裡正評/(正評+負評) 的比例，見 `api/recommend.py`），
  **不是**畫面上商品卡片顯示的 `★ rating_platform`（樂天/OliveYoung/cosme/화해 自己平台頁面上的星等）。
  這兩個是完全不同的兩組數字，程式邏輯本身沒有錯（`recommend.py` 註解也寫了「跟平台自己的星等評分
  rating_platform 是兩回事」），但前端沒有把這個差異講清楚，使用者會直覺以為排序是依照畫面上看到的 ★ 數字。
- 問題出在：**如果一批商品全部都是 `sentiment_pos_rate = None`**（完全沒配對到社群評論，樂天商品常常是這樣，
  見下面 9-2），排序邏輯會把這些 None 全部當成同一個值（`-1`），排序等於沒作用，結果會維持在
  「套用排序之前」的原始順序（也就是語意相關度順序），這時候畫面上看到的 ★ 數字就會顯得雜亂無章，
  讓人誤以為排序壞掉了，其實排序有執行，只是「依據的那個欄位」全部沒資料。
- **建議修法（還沒做）**：
  1. 排序邏輯加一個 fallback：`sentiment_pos_rate` 是 None 的商品，改用 `rating_platform` 當次要排序依據，
     這樣至少視覺上看起來合理
  2. 前端排序選單文字改清楚一點，例如「好評率高→低（依社群評論，非平台星等）」，避免使用者誤解
  3. 或者乾脆多加一個新的排序選項「平台星等高→低」，把兩種排序都留給使用者選

### 9-2. 樂天 / Olive Young 社群評論配對率查證（2026-09-12 查資料庫得出）

| 平台 | 商品數 | 配對到至少 1 篇 PTT/Dcard 評論的商品數 | 對應到的評論總篇數 |
|---|---|---|---|
| rakuten | 1116 | 48（4.3%） | 73 篇 |
| oliveyoung | 424 | 10（2.4%） | 15 篇 |
| cosme | 346 | 31（9.0%） | 44 篇 |
| hwahae | 87 | 7（8.0%） | 12 篇 |

`reviews` collection 目前**只有** dcard（51 篇）+ ptt（99 篇）＝150 篇，全部是台灣社群論壇貼文，
**不是**樂天/Olive Young 平台自己使用者寫的評論文字。樂天/Olive Young 商品卡片上顯示的 ★ 星等跟
「(1,184)」這種評論篇數，只是平台頁面上的**彙總數字**（`rating_platform` / `review_count_platform`），
資料庫裡完全沒有存這些平台評論的逐篇文字內容。

### 9-3. 查證過爬蟲原始碼：兩個平台都沒有抓過平台自己的評論文字，是否值得擴充爬蟲待確認

- **樂天（`scrapers/rakuten_scraper.py` + `rakuten_scraper/scraper.py`）**：資料來源是官方 **Rakuten Ichiba
  商品搜尋 API**，這支 API 本身的回應就只有 `reviewAverage`/`reviewCount` 這兩個彙總欄位，
  **不會**回傳逐篇評論文字。如果要拿到真的評論內文，要另外串樂天獨立的「レビュー検索 API」
  （同一組 `RAKUTEN_APP_ID`/`RAKUTEN_ACCESS_KEY` 應該可以用，但目前程式完全沒有呼叫這支 API），
  是一個全新的爬蟲/串接工作，不是修個小 bug 而已。
- **Olive Young（`scrapers/oliveyoung_scraper.py`，用 Playwright 爬詳細頁）**：目前詳細頁只有抓
  評分/評論數/成分表，**沒有**進到評論列表分頁去抓文字。技術上詳細頁確實看得到韓文使用者評論，
  是可以擴充爬蟲去抓，但要注意第 6 節已經記錄過的坑：**Olive Young 容易被 Cloudflare 擋，
  尤其短時間內開很多次 headless Playwright session**——抓評論等於要對同一頁面多開分頁/多次請求，
  會提高被擋的風險，需要控制頻率。

### 9-4. 下次接手時要做的事（按這次調查的優先順序）

1. 決定要不要真的去擴充爬蟲抓樂天/Olive Young 平台自己的評論文字（工程量：樂天要串新的 Review API，
   Olive Young 要擴充 Playwright 抓評論列表分頁 + 控制被擋風險），還是維持現狀只用 PTT/Dcard 配對
2. 如果決定要擴充，抓回來的評論文字要接上現有的 `nlp/sentiment.py` 情緒分析 + 評論-商品配對流程，
   格式要跟現有 PTT/Dcard 評論相容，`sentiment_pos_rate`/AI 摘要邏輯才吃得到這批新資料
3. ~~9-1 那個排序邏輯的 fallback 應該先修掉~~ ✅ 2026-09-13 已修正

## 10. 2026-09-13 樂天評論擴充爬蟲：進行中，**下次先把樂天爬完再做 Olive Young**

對應第 9-3/9-4 節的待辦。實際做下去發現不需要走「樂天 Review API」這條路，
直接爬樂天自己的評論網頁更簡單可靠，見下面說明。**這是目前唯一在進行中的爬蟲工作，
下次接手請先看這一節，不要重新規劃。**

### 10-1. 目前進度（隨時可能變動，接手時請先重跑查證指令）

```bash
python -m scripts._check_progress   # 這支腳本已經刪掉了，要查進度請用下面這段：
```
```python
from db.mongo_client import get_db
db = get_db()
print(db.reviews.count_documents({"source": "rakuten"}))  # 樂天評論總數
print(len(db.reviews.distinct("product_id", {"source": "rakuten"})))  # 已完成商品數
print(db.products.count_documents({"source_platform": "rakuten", "review_count_platform": {"$gt": 0}}))  # 目標商品總數
```

**2026-09-13 停止時的數字**：樂天評論 **15,201 則**，已完成 **286 / 1031** 個商品，剩 **745 個**。
目前抓到的評論 sentiment 全部是 positive（0 negative）——這不是 bug，是因為預設只抓每個商品
評論頁的第 1~3 頁（見 10-3 為什麼只抓前幾頁），樂天評論頁預設排序是「参考になった順」（最有幫助优先），
高票評論本來就容易偏正面。**如果之後想要負評也有代表性，可以改成額外多抓一次「評価が低い順」排序
的前幾頁**，目前這版沒做。

### 10-2. 資料存在哪裡、怎麼用

評論直接寫進跟 PTT/Dcard 評論同一個 `reviews` collection（`source: "rakuten"` 區分來源），
欄位相容現有的 `api/recommend.py` 邏輯（`product_id`/`sentiment`/`title`/`source`），
**不用額外改前後端，資料存進去就會自動被現有的好評率排序、AI 摘要邏輯吃到**
（不過 `ai_summary` 是批次預先生成的欄位，見第 3-4 節，這批新評論還沒有觸發重新生成摘要，
如果要讓新配對到樂天評論的商品也有 AI 摘要，要重跑 `scripts/generate_review_summaries.py`）。

**情緒判斷用的是評論者自己給的星等**（4~5 星 = positive，1~3 星 = negative），
**沒有**跑 `nlp/sentiment.py` 的中文情緒模型——那個模型是訓練給中文用的，套在日文評論上不準，
星等本身就是更直接可信的依據，也省了跑模型的時間。

### 10-3. 怎麼抓到的（給下次接手的技術說明）

- **不是**用官方 Rakuten API，是直接爬樂天自己的評論網頁（`review.rakuten.co.jp`），完全不需要
  `RAKUTEN_APP_ID`/`RAKUTEN_ACCESS_KEY`（第 9-3 節講的「要另外串 Review API」是想多了，實測直接爬
  網頁更簡單）
- 評論網址格式：`https://review.rakuten.co.jp/item/1/<店家數字編號>_<商品編號>/<頁碼>.1/`
  （例如 `.../item/1/409735_10000000/1.1/`），這組「店家數字編號」沒辦法從我們資料庫既有欄位算出來，
  要先進商品頁（`source_url`）本身，抓頁面上 `href` 含 `review.rakuten.co.jp/item/` 的連結才拿得到
- **關鍵限制**：`item.rakuten.co.jp`（樂天個別商品頁）對 headless Playwright 或 `requests`/`curl`
  會擋（Akamai 只回一個 Reference 錯誤頁，或直接逾時連不上），**但用真正開著的 Chrome（非 headless）
  就抓得到**——原因不確定，但實測結果就是這樣，不用花時間再驗證這件事
- 解法：**手動開一個獨立的 Chrome**（不要用你平常在用的那個 profile，開一個乾淨的），指令：
  ```
  chrome.exe --remote-debugging-port=9222 --user-data-dir=<任一個暫存資料夾> https://www.rakuten.co.jp/
  ```
  等首頁正常載入（不要卡在驗證畫面）之後，這支腳本會用 Playwright 的 `connect_over_cdp()` 連上去，
  之後全自動操作，不用人再手動點
- 評論卡片的 HTML 解析邏輯、選好的 CSS selector 都寫在 `scripts/scrape_rakuten_reviews.py` 的
  `parse_review_card()` 裡，已經測過對 20/20 則評論解析成功，欄位包含：星等、日期、使用者名稱/
  性別/年齡層、購買規格、評論全文、有幫助票數

### 10-4. 已知不穩定問題：Chrome / CDP 連線會斷

跑到一半 Chrome 會斷線兩次（"Target page, context or browser has been closed"），原因不明確
（不確定是系統睡眠、Chrome 記憶體問題、還是單純的連線抖動）。**已經加上自動重連邏輯**
（`scrape_rakuten_reviews.py` 的 `main()`，連續失敗 2 次就重新呼叫 `connect_over_cdp()`），
但如果 Chrome **整個程式**被關掉（不只是分頁），自動重連也救不回來，要重新照 10-3 的指令
手動開一個新的 Chrome，再重跑腳本。

**腳本可以安全重跑**：`main()` 裡的 `skip_done=True`（預設）會先查資料庫，跳過已經有評論的商品，
不會重複抓、不會浪費時間。

### 10-5. 下次接手的具體步驟

1. 確認 XAMPP MySQL 有沒有開（見第 3-1b 節，如果要測會員系統的話；跟樂天爬蟲本身無關）
2. 照 10-3 的指令開一個新的 Chrome（`--remote-debugging-port=9222`），等首頁載入
3. `cd new_product && .\venv\Scripts\python.exe -m scripts.scrape_rakuten_reviews`
   （不用加參數，會自動跳過已完成的 286 個，處理剩下的 745 個）
4. 這次跑完、確認樂天全部 1031 個商品都處理完之後，**才開始 Olive Young**：
   - `olive_young_scraper/scraper.py` 目前**只抓商品資料，完全沒有抓評論文字的程式碼**
     （只抓了評分/評論數/成分表這些彙總欄位，見第 9-3 節）
   - 要先用同一招（真 Chrome + CDP 連線）去 Olive Young 商品詳細頁找評論區塊的 HTML 結構
     （這部分完全還沒探索過，跟樂天不一樣，要重新來一次 10-3 那樣的探索過程），
     再比照 `scripts/scrape_rakuten_reviews.py` 的寫法寫一支新的 `scripts/scrape_oliveyoung_reviews.py`
   - Olive Young 本身有 Cloudflare 防護（見第 6 節），流程可能會比樂天更容易卡，要有心理準備
