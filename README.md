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

## ▶ 怎麼把網站跑起來（Windows PowerShell，照順序打）

需要 **Python 3.11**（`python --version` 確認）。以下指令都在 repo 根目錄執行。

**第一次（只要做一次）**

```powershell
# 1. 下載專案
git clone https://github.com/jayee123/new_product.git
cd new_product

# 2. 建虛擬環境並啟用（之後每次開新的終端機都要重新啟用，看到最前面有 (venv) 就對了）
python -m venv venv
venv\Scripts\activate

# 3. 安裝套件（約 1.5～2 GB，要等幾分鐘）
pip install -r requirements.txt

# 4. 建立設定檔，用記事本打開填入金鑰（MONGO_URI、MONGO_DB、MYSQL_*、JWT_SECRET、GEMINI_API_KEY，跟組員要）
copy .env.example .env
notepad .env

# 5. 建立商品向量索引 chroma_db（沒進版控，第一次一定要建；第一次會下載 embedding 模型 ~120MB）
python -c "from rag.embedder import build_product_index; build_product_index()"
```

> ⚠ 第 5 步不要用 `python -m rag.embedder`，那支除了建索引還會跑「評論配對」，會改到資料庫。

**每次要測試**

```powershell
# 1. 先開會員資料庫（XAMPP MySQL）：打開 XAMPP Control Panel 按 MySQL 的 Start，或直接執行
C:\xampp\mysql_start.bat
#    沒開的話搜尋還是能用，但「註冊／登入」會失敗，前端跳出
#    Unexpected token 'I', "Internal S"... is not valid JSON（後端是連不上 MySQL 的 500 錯誤）
#    （2026-09-13 起 Aiven 雲端 MySQL 連不上，改用本機 XAMPP，見 3-1b 節）

# 2. 啟動網站
venv\Scripts\activate
python -m uvicorn api.main:app --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 後，用瀏覽器打開 **http://localhost:8000/**。
第一次搜尋會比較慢（約 15～20 秒，在載入模型），之後每次搜尋不到 1 秒。

- **關掉**：在跑 uvicorn 的終端機按 `Ctrl + C`
- **改了 `api/` 底下的程式**：要按 `Ctrl + C` 關掉再重新啟動才會生效（這台機器上 `--reload` 不可靠，不要用）
- **出現 `address already in use` / port 8000 被佔用**：代表已經有一個在跑，直接開瀏覽器就好；或先找出來關掉：
  ```powershell
  netstat -ano | findstr :8000        # 最後一欄是 PID
  taskkill /PID <上面的PID> /F
  ```

**有新爬的評論時（選用）**：樂天/Olive Young 新評論要跑 RoBERTa 判斷正負評，好評率才會用文字判斷（只會跑還沒跑過的，CPU 約每秒 5～8 則，第一次會下載模型 ~1.1GB）：
```powershell
python -m scripts.run_roberta_sentiment
```

**手動測試可以看的地方**（排序規則見第 11 節）
- 排序預設是「綜合推薦」：有社群評論的在前 → 好評率等級（≥90% A、80~90% B、<80% C）→ 平台星等 → 相關度
- 商品類型選「化妝水」、需求打「保濕」：前面都是 A 級，同一級裡照星等高→低
- 需求打「乾性肌保濕精華」：沒有社群評論的商品會排在最後面；評論少於 5 則的就算 100% 也只算 B 級
- 排序改成「價格低→高 / 高→低」：依台幣價格排

## ▶ 在這台電腦開 ngrok 給別人連（一鍵）

對 repo 根目錄的 **`start_ngrok.bat` 點兩下**，會自動開 MySQL、網站、ngrok 三個視窗（已經在跑的會跳過）。
公開網址在「ngrok - KEEP OPEN」視窗的 `Forwarding` 那行，或瀏覽器開 http://127.0.0.1:4040 也看得到。
三個視窗都不要關，電腦不能睡眠。第一次用要先設定 ngrok 金鑰：`ngrok config add-authtoken <金鑰>`（設一次就好）；ngrok 版本太舊會被拒絕連線，執行 `ngrok update` 更新。

## ▶ 搬到另一台 server，用 ngrok 給別人連

要搬的東西有 4 樣，**只有程式碼在 GitHub 上**，其他 3 樣要自己處理：

| 東西 | 在哪裡 | 怎麼搬 |
|---|---|---|
| 程式碼 | GitHub | `git clone` |
| `.env`（金鑰、密碼） | 原本那台電腦的 repo 根目錄 | **自己複製檔案過去**（隨身碟／雲端硬碟），**絕對不要推上 GitHub** |
| 會員資料庫（MySQL） | 原本那台的 XAMPP | 原本那台匯出成 `buytuoleai_auth.sql`，到 server 匯入 |
| 商品向量索引 `chroma_db` | 沒進版控 | 到 server 重建（指令見上面第一次第 5 步） |

商品／評論資料在雲端 MongoDB Atlas，**不用搬**。但要去 Atlas 的 **Network Access** 確認有允許 server 的 IP（或已設 `0.0.0.0/0`），不然 server 連不到資料庫。

**在原本那台電腦（匯出會員資料庫）**
```powershell
# MySQL 要先開著；-u 後面換成 .env 裡的 MYSQL_USER，有密碼的話加 -p
C:\xampp\mysql\bin\mysqldump.exe -u root --databases buytuoleai_auth --result-file buytuoleai_auth.sql
```

**在 server 上（Windows，照順序）**
```powershell
# 1. 下載程式碼（目前最新的在 ranking-roberta-sentiment 分支）
git clone -b ranking-roberta-sentiment https://github.com/jayee123/new_product.git
cd new_product

# 2. 把 .env 複製到這個資料夾（new_product\.env）

# 3. 安裝 XAMPP（https://www.apachefriends.org/），開 XAMPP Control Panel 按 MySQL 的 Start，再匯入會員資料庫
C:\xampp\mysql\bin\mysql.exe -u root < buytuoleai_auth.sql
#    注意 .env 的 MYSQL_PORT 要跟 server 上 MySQL 的 port 一樣（XAMPP 預設 3306）

# 4. 照上面「第一次」的第 2、3、5 步：建 venv、pip install、建 chroma_db

# 5. 啟動網站
venv\Scripts\activate
python -m uvicorn api.main:app --port 8000

# 6. 另開一個終端機，用 ngrok 公開（第一次要先到 https://dashboard.ngrok.com 註冊，複製 authtoken）
ngrok config add-authtoken <你的authtoken>
ngrok http 8000
```
ngrok 畫面上 `Forwarding` 那行的 `https://xxxx.ngrok-free.app` 就是給別人連的網址。

- **網站（uvicorn）、MySQL、ngrok 三個都要一直開著**，任何一個關掉，網址就連不到或註冊／登入會壞
- 免費版 ngrok **每次重開網址都會變**，要重新把新網址給別人；第一次打開會有一頁 ngrok 的警告頁，按「Visit Site」就好
- server 若是 Linux：步驟一樣，差別是 `source venv/bin/activate`、MySQL 用 `sudo apt install mysql-server`、匯入用 `mysql -u root -p < buytuoleai_auth.sql`

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
- 每筆結果除了商品資料，還會帶 `sentiment_positive`/`sentiment_negative` 好評壞評數、`ai_summary`（AI 評論摘要）跟 `complaint_stats`（常見缺點統計）。
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
**（2026-09-21 更正）** 這段原本寫「全部是 positive（0 negative）」只對最早那批成立。實際查 29,507 則：
1 星 82、2 星 58、3 星 241、4 星 6,415、5 星 22,711 → **負評（1~3 星）共 381 則，僅 1.3%，好評 98.7%**。
偏正面有兩層原因：① 樂天評論本身就很正面（例如評論 4.5 萬則的那個商品，平台顯示 5 星 73%、4 星 23%，
1~2 星合計不到 1%）；② 我們只抓預設排序（「参考になった順」＝最有幫助優先）的第 1~3 頁，比真實分布更偏正面，
對**平台星等本來就低的商品**尤其失真（樂天有 116 件商品平台平均星等低於 4）。
**兩個平台取樣方式不一致，好評率不可跨平台比較**：Olive Young 是「最有幫助 30 則 + 最低分 10 則」，
結果 1 星占 22.1%，比真實情況**偏負**（該平台商品平均星等約 4.9）。
如果要改善：樂天多抓「評価が低い順」排序的前幾頁，或兩個平台都改成依平台真實星等分布（Olive Young 的
`/reviews/{goodsNo}/stats`、樂天評論頁頂端的星等分布）按比例取樣／加權。目前都還沒做。

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

### 10-4b. **每次爬完一批評論，都要重跑 `scripts/generate_review_summaries.py` 補 AI 摘要**

前端商品卡片顯示的「評論摘要 + 適合族群」（`products.ai_summary`，見第 3-4 節）是**批次預先生成**的，
不會自動因為 `reviews` collection 多了新資料就自動更新。**這是一個持續性流程，不是做一次就結束**：
只要有新的評論被爬進來、配對到商品（不管是樂天/Olive Young 評論爬蟲直接寫入，還是以後 PTT/Dcard
再抓新的），都要記得回來跑一次：

```
python -m scripts.generate_review_summaries
```

腳本會自動跳過已經有 `ai_summary` 的商品，只處理新配對到評論、還沒生成摘要的部分，可以放心重跑。

**2026-09-13：Gemini key 失效，這支腳本已經改用 OpenAI gpt-4o-mini**
（`ai/openai_translate.py` 的 `summarize_reviews()`），一樣有 `BUDGET_CAP_USD`（US$0.5）硬性預算保護，
超過會自動停止，下次重跑會自動接續沒做完的部分。跑第一批 272 個樂天評論配對商品的補摘要時，
花費請看執行輸出的「本次花費」那行（每次執行都是獨立計算，不是累加歷史總花費）。

### 10-4c. 2026-09-20 樂天爬蟲另一個當機原因：MongoDB Atlas 寫入斷線（已修）

除了 Chrome/CDP 斷線（10-4），還發現樂天爬蟲另一次當機是 **MongoDB Atlas 在寫入評論時斷線**
（`pymongo.errors.AutoReconnect: connection closed`），寫入那一步原本沒包錯誤處理，整個腳本跟著死掉。
已加上 `save_reviews_with_retry()`（斷線等幾秒重寫，upsert 所以重寫安全），寫不進去也只跳過該商品。
這個問題跟你電腦網路穩不穩有關，Atlas 查詢偶爾會慢到 8~9 秒。Olive Young 爬蟲也用了同樣的重試邏輯。

### 10-6. Olive Young 評論爬蟲（2026-09-20 完成探索並開跑）

程式：`scripts/scrape_oliveyoung_reviews.py`（詳細技術筆記寫在檔案開頭 docstring）。

**跟樂天不一樣，Olive Young 有乾淨的 JSON API，不用解析 HTML**：商品頁點「리뷰」分頁後，網頁自己呼叫
`POST https://m.oliveyoung.co.kr/review/api/v2/reviews/cursor`，body：
`{"goodsNumber","page","size","sortType","reviewType"}`，回傳結構化 JSON（星等、內文、規格、膚質、日期、有幫助數）。

實測到的行為（下次接手不用再探索）：
- 用 `page` 頁碼翻頁**無效**（回同一批），要翻頁必須帶 `cursorId`/`cursorScore`（回傳的 `nextCursorId`/`nextCursorScore`）
- `size` 上限 50（100 會回空資料）
- `sortType` 有效值：`USEFUL_SCORE_DESC`（最有幫助）、`RATING_DESC`（高分在前）、`RATING_ASC`（低分在前）；
  亂猜的其他名稱一律回 400，錯誤訊息不會列出合法值
- 不帶 cookie 就能呼叫，但必須從 `www.oliveyoung.co.kr` 頁面裡用 `fetch` 發（跨網域），
  所以腳本是連上真 Chrome（CDP，port 9223），在頁面裡 `page.evaluate(fetch)`
- **會被暫時擋住**：短時間連續送幾十個請求，`fetch` 會回 `Failed to fetch`（連本來能用的請求也失敗），
  等約 2 分鐘會恢復。腳本已限速（每個請求 2.5 秒）＋失敗退避重試＋連續 3 個商品失敗就停下來
- 商品頁本身**沒被 Cloudflare 擋**（用真 Chrome 進去），第 6 節那個「容易被擋」的擔心這次沒有發生

**取樣**：每個商品「最有幫助」前 30 則 ＋「最低分」前 10 則。只取最有幫助的話全是 5 星，AI 摘要看不到缺點。
**注意**：因為刻意混入低分，`sentiment_pos_rate` 是這個取樣混合的結果，**不等於商品真實好評比例**。
（樂天那邊是只取預設排序前 3 頁，同樣偏正面，兩邊取樣方式不一致，見 10-1。）

評論是韓文，`reviews` collection 欄位跟樂天評論相容（`source: "oliveyoung"`、`sentiment` 用星等換算：
4~5 星 positive，1~3 星 negative），額外存了 `review_id`（去重用）、`skin_type`、`option_name` 等。

### 10-7. 2026-09-21 文字情緒 vs 星等分析（樂天／Olive Young 各隨機抽 400 則）

動機：使用者問「樂天到底有沒有負面評論」，並提出用情緒偵測（看文字）取代/補充星等。
`nlp/sentiment.py` 的模型是**中文專用**，套在日文、韓文上不準，所以改用 gpt-4o-mini 直接讀原文，
函式是 `ai/openai_translate.py` 的 `classify_sentiments()`（輸出 positive / negative / mixed，**完全不看星等**，
漏判回傳 None）。抽 800 則花費 **US$0.0133**（40 次呼叫），推估全部 4.6 萬則約 US$0.8、幾千次呼叫。

| | 文字：正面 | 文字：褒貶並陳 | 文字：負面 | 星等判斷的負面（1~3 星） |
|---|---|---|---|---|
| **樂天** | 79.2% | 20.0% | **0.8%**（400 則只有 3 則） | 2.2% |
| **Olive Young** | 60.8% | 22.2% | 17.0% | 23.5% |

發現：
1. **樂天真的幾乎沒有純負面評論**（約 0.8%），不是我們爬漏了。但約 **20% 是「褒貶並陳」**：給 4~5 星，
   文字裡卻有抱怨（質地、包裝、夏天不適合等）。樂天 4 星的評論有約 40% 是褒貶並陳。
2. **兩個平台都一樣：4~5 星的評論裡約 20% 文字有抱怨，光看星等會漏掉。**
3. 星等跟文字幾乎不會方向相反：樂天 1~2 星沒有任何「文字正面」；Olive Young 1~2 星有 7/82 文字正面（可能誤點星等）。
4. **Olive Young 的 17% 負面被高估**：我們每個商品刻意混入 10 則最低分（見 10-6），不代表真實比例。
5. **含意**：樂天負評太少，「好評率」（正/(正+負)）會全部擠在 98~99%，**無法區分商品好壞**。對樂天更有鑑別力的訊號是
   「褒貶並陳的比例」與**具體抱怨內容**（AI 摘要的缺點段落）。
6. 侷限：n=400 誤差約 ±4~5 個百分點；「褒貶並陳」是 LLM 主觀判斷，界線偏寬（連「薄荷醇敏感肌請注意」這種輕微
   提醒也可能被標成褒貶並陳），20% 應視為偏高的上限。

**還沒做**：把 `classify_sentiments()` 跑全部評論、把結果存成新欄位（例如 `sentiment_text`，不要覆蓋現有用星等換算的 `sentiment`）。
踩坑：一批 20 則要求 LLM 回傳「陣列長度剛好 20」會整批作廢（模型常多一筆少一筆，40 批全失敗），
要用「編號→情緒」的物件格式。

### 10-8. 「常見缺點」功能規劃（2026-09-21 討論定案，**決定已經齊了、但還沒開始實作；使用者說 OK 才開始做，下次接手直接照這節做，不用再討論**。剩下唯一沒回答的：是否加「摘要面向必須存在於統計」的程式檢查，開始實作時再問一次即可）

**📍 第一輪執行結果（2026-09-21）**：跑完 501 個商品（依評論數多→少），失敗 0，花費 US$1.0027（達上限自動暫停），耗時 48.8 分鐘；其中 460 個有缺點摘要、42 個沒有「≥2 人提到」的缺點。`--recheck` 程式檢查 460 個全數通過（0 個換成固定句型）。**第二輪（同日，使用者同意繼續）**：`BUDGET_CAP_USD` 調成 2.6，跑完剩下 877 個，失敗 0，累計花費 US$2.0796，耗時 55.9 分鐘；其中 334 個沒有「≥2 人提到」的缺點。全部合計 1,378 個商品處理完，1,003 個有缺點摘要；`--recheck` 通過 1,001 個，另 2 個本來就是固定句型（cons_source="template"，檢查時跳過）。

**📍 實作狀態（2026-09-21 使用者說「直接全跑，US$1 就暫停」，已實作並開跑）**
- 程式：`scripts/build_cons_summaries.py`（一條龍，docstring 有完整說明）、`ai/openai_translate.py`
  （新增 `extract_review_aspects()`、`write_cons_summary()`、`configure_budget()`，計費加了執行緒鎖）、
  `api/recommend.py` 多回傳 `complaint_stats`、`frontend/index.html` 新增「⚠ 常見缺點」區塊（缺點摘要＋
  `面向 ×次數` 標籤＋「看原文」展開，並標明「依取樣 N 則評論統計」）
- **做法是以「商品」為單位一個一個做完**（抽抱怨→統計→重生摘要，評論多的優先），不是先全部抽取再全部寫摘要，
  這樣預算暫停時，做完的商品都是完整可用的；4 條同時跑；已完成的商品（有 `complaint_stats`）重跑會跳過
- **預算**：累計上限 US$1，已花金額記在 MongoDB `ai_budget` 集合（`_id: "cons_feature"`），跨執行累計；
  要繼續就調高 `build_cons_summaries.py` 的 `BUDGET_CAP_USD` 再重跑，自動接續
- ✅ **比使用者原本確認的「固定 10 類」多加一類（使用者 2026-09-21 已追認 OK）**：健全檢查時發現彩妝的色差／色號不合被硬塞進「質地」，
  所以多加一類 **「顏色／色號」（共 11 類）**，已告知使用者並獲追認，之後面向清單就是這 11 類
- 另一個防呆：模型偶爾沒把抱怨翻成中文，程式會把含日文假名／韓文字母的抱怨描述清空（面向仍計數，只是不顯示那句）
- **實測費用比原本估的高**：評論 60 則的商品每個約 US$0.0027（原本估 US$0.0014）；全部 1,379 個商品估計要
  **約 US$2.3~2.5**，不是先前說的 US$1.7~2，US$1 大約只能做完前 400~500 個商品
- ✅ **缺點摘要的程式檢查（使用者 2026-09-21 同意加，已做）**：`validate_cons()` 用程式單向比對（不是 AI 檢查 AI，
  摘要也不會回頭當任何步驟的輸入）：缺點摘要提到的面向關鍵字、出現的數字，都必須存在於統計裡；例外是關鍵字本來就出現在
  統計的抱怨描述文字中（視為合法引用）。不通過就重寫一次，還是不行就改用 `template_cons()` 程式拼的固定句型（不可能有幻覺）。
  結果存在 `ai_summary.cons_source`（`"ai"` 或 `"template"`）。
  - **踩坑**：第一版檢查太嚴、有誤判（關鍵字表放了泛用詞「效果」，「持妝效果不佳」被誤判成保濕／效果面向；
    AI 照實引用別的面向的描述詞也被擋），11/126 被誤換成生硬的固定句型，且原本的 AI 文字已被覆蓋；
    修正後用 `--recheck --regen-template` 讓那 11 個重寫，全部通過。改檢查邏輯後要重跑 `--recheck` 補檢查舊資料
  - `python -m scripts.build_cons_summaries --recheck` 回頭檢查已完成商品（**不呼叫 AI、不花錢**），
    `--regen-template` 額外讓被換成固定句型的重新用 AI 寫一次（少量呼叫）
  - 舊版程式（檢查上線前）產生的缺點摘要沒有 `cons_source`，全部跑完後要再跑一次 `--recheck` 補檢查

**目標**：使用者希望不管樂天或 Olive Young，評論中偏負面／褒貶並陳的地方，都要在商品卡片上被特別抓出來顯示，
而不是被正面評論淹沒。**根本原因**：現在的摘要偏正面是結構性的——`generate_review_summaries.py` 取評論時是
`.limit(15)` 不排序（樂天多半是最有幫助的 5 星），缺點根本沒進到輸入裡，光改提示詞沒用。
（補充：原本 Gemini 版沒有 limit，PTT/Dcard 少量評論是全部合併摘要；`.limit(15)` 是 2026-09-13 改用 OpenAI 時我加的。）

**已定案的做法**
1. 對每則評論用 LLM 做**固定格式的抽取**：情緒（正面／褒貶並陳／負面）＋抱怨面向（固定清單，提議 10 類：質地、包裝、
   容量、氣味、刺激過敏、保濕／效果、持妝、價格、物流、其他）＋一句繁體中文抱怨內容。一次呼叫做完，不覆蓋現有的
   星等換算 `sentiment`，存新欄位（如 `sentiment_text`、`complaints`）。`ai/openai_translate.py` 的
   `classify_sentiments()` 已寫好且測過（只做情緒分類，尚未含抱怨面向）。
2. 商品層**直接計數**（例如「質地偏黏 ×12」）存進 products，計數來自原始評論，**不來自摘要**。
3. **證據評論用平台自己的票數挑**（樂天 `helpful_count`、Olive Young 推薦數 `recommendCount`，都已存在 reviews 裡）：
   每個缺點面向，附上票數最高的那則真實抱怨原文，可追溯、不靠 AI 判斷。
4. **（2026-09-21 使用者改變決定）缺點也要有 AI 寫的摘要**，不是只放標籤＋原文：負評很多時原文太長，
   而且「有些是摘要、有些是原文」格式不一致，使用者說不 OK。做法（使用者 2026-09-21 已同意）：AI **只根據程式算好的
   結構化統計**（面向＋次數＋一句話）寫 1~2 句缺點摘要，不讓它直接讀幾十則原文自由發揮；計數標籤放旁邊；
   真實原文引用收在「看原文」展開裡，預設不顯示，版面格式就一致了。
5. 前端商品卡片新增「⚠ 常見缺點」區塊，並標明「依取樣評論統計」（樂天只取前幾頁，不是全部評論）。

**使用者明確決定不做的**
- ❌ **信賴區間（±X%）先不做**，除非之後有必要
- ⚠️ **寫完摘要後的自動核對：使用者立場有變，待確認**。原本說不做（擔心摘要幻覺影響後續處理），但後來要求缺點也要
  AI 摘要，代表幻覺面回來了。**不變的原則：AI 生成的摘要只是最終顯示，永遠不當成下一步的輸入**；缺點資料一律從原始評論算，
  不從摘要來。我的建議是加一個很小的**程式檢查（不是 AI）**：摘要提到的缺點面向必須存在於統計裡，這是單向比對，
  不會把摘要回饋到任何後續處理。要不要加由使用者決定。

**還沒確認／實作前要先問使用者**
- ✅ 抱怨面向清單用固定 10 類：**使用者 2026-09-21 已確認 OK**
- **抽樣與「什麼算主流缺點」（2026-09-21 討論中）**：使用者擔心票數會被行銷操作、極端評論被放大。我的修正建議：
  缺點認定改用「頻率」（每則評論一票，需被 **≥2 位**不同評論者提到才算（使用者決定 N=2）），票數只用來挑展示原文；
  「用真實星等分布加權」對缺點摘要這個目標不需要，先不做（那是為了算好評率，兩件事我先前混在一起）。
  **抽樣來源：✅ 使用者選 A（用現有資料），不補抓、不重爬「最新」排序**。（當時的兩個選項如下，B 已捨棄：）用現有資料（樂天是「最有幫助」排序前 3 頁、Olive Young 是 30 則最有幫助＋10 則最低分，皆有偏差），
  或補抓「最新」排序（樂天評論頁有「新着レビュー順」；Olive Young 有效的 sortType 目前只確認 USEFUL_SCORE_DESC／
  RATING_DESC／RATING_ASC，最新排序名稱尚未確認）——後者較接近隨機但要再爬一輪
- 費用上限：預估全部 4.6 萬則約 US$1~1.5（使用者表示約 US$1 等級可接受），程式目前 `BUDGET_CAP_USD = 0.5`
  要調高，開跑前先確認實際要設多少
- 分層抽樣＋用平台真實星等分布加權（還原真實比例）：需要額外存每個商品的星等分布（Olive Young 有
  `/reviews/{goodsNo}/stats` API，樂天要補解析評論頁頂端），使用者只有針對「以前是不是全部評論合併摘要」提問，
  這一項還沒正式同意，實作前再問

**⚠ 順序提醒**：如果要做缺點欄位，**先不要跑 `generate_review_summaries` 補那 792 個摘要**（否則之後還要重生，重複花錢），
等這個功能決定好、改完提示詞與取樣再一起跑。

### 10-5. 下次接手的具體步驟

**📍 進度快照（2026-09-21 更新，數字是當下查資料庫的實際值，接手時請重查）**

| 項目 | 進度 |
|---|---|
| 樂天評論 | **916 / 1031** 個商品有評論，累計 **30,805 則**；**115 個沒存到評論**（見下方「樂天收尾紀錄」，使用者決定先停，不一定要再爬） |
| Olive Young 評論 | ✅ **全部完成 415 / 415**，累計 16,335 則（正 11,845 / 負 4,490，含刻意混入的低分評論） |
| `reviews` collection 總筆數 | 47,290（PTT 99 + Dcard 51 + 樂天 30,805 + Olive Young 16,335） |
| AI 評論摘要 | 有配對到評論的商品 1,379 個，已有摘要 368，**待補 1,011**（要先做完 10-8 缺點功能再一起跑，避免重複花錢） |
| 爬蟲行程 | 已全部停止；除錯 Chrome（9222/9223）不一定還開著，接手時先檢查 port |

**樂天收尾紀錄（2026-09-21）**：最後 341 個（都是評論數最少的冷門商品，因為腳本照評論數由多到少爬）只存了 1,304 則，
不是出錯：190 個只有 1~9 則、31 個 10~30 則、6 個 31 則以上，**95 個沒存到**（69 個商品頁**找不到評論連結**、
20 個 `Page.goto: net::ERR_ABORTED`／1 個 `ERR_HTTP2_PROTOCOL_ERROR`／1 個逾時，都是連到樂天聯盟轉址連結
`hb.afl.rakuten.co.jp` 時被中斷）。加上更早失敗的，目前共 **115 個沒存到**，平台顯示的評論數中位數 14、最少 1、
**最多 5,433**（有幾個評論不少的是暫時性失敗，值得重試）。使用者於 2026-09-21 決定「先停」，重試跑到一半就被停掉，沒有救回任何商品。
- **重跑方式不變**：`python -m scripts.scrape_rakuten_reviews`，只會處理「還沒存到評論」的這 115 個，很快（幾分鐘）；
  但 69 個找不到評論連結的多半重跑也一樣失敗。
- **可能的改善（沒做）**：轉址連結容易被中斷，可以改成解碼連結裡的 `pc=` 參數，直接連 `item.rakuten.co.jp` 商品頁。
- 注意：「沒存到評論」的商品每次重跑都會被重新處理（`skip_done` 只跳過已有評論的），是預期行為。

**Olive Young 收尾紀錄**：第一輪（196 個商品）後遇到 Playwright↔Chrome CDP 連線斷掉，補上自動重連後，
第二輪續跑剩下的 206 個，**0 失敗、0 次被網站擋、0 次斷線**，全部完成。中途使用者要求暫停過一次（不是出錯）。

**建議接手順序**：① 跑樂天剩 341 個 → ② 跑一次 `generate_review_summaries` 一次補完 792 個摘要
（比每爬完一批就跑更省事，OpenAI 花費約 US$0.1~0.4，上次補 272 個花了 US$0.0973）。

**樂天**（見上面快照；每次跑不用加參數）：
1. 確認 XAMPP MySQL 有沒有開（見第 3-1b 節，如果要測會員系統的話；跟爬蟲本身無關）
2. 照 10-3 的指令開一個新的 Chrome（`--remote-debugging-port=9222`），等首頁載入
3. `cd new_product && .\venv\Scripts\python.exe -m scripts.scrape_rakuten_reviews`
   （不用加參數，會自動跳過已完成的）

**Olive Young**：✅ 415 個有評論的商品已全部完成，不用再跑（技術細節見 10-6）。
之後如果想**更新評論**（例如過幾個月想抓新評論）：先在 MongoDB 刪掉 `source: "oliveyoung"` 的評論
（或改腳本的 `already_done` 跳過邏輯），再照下面步驟重跑：
1. 開 Chrome：`chrome.exe --remote-debugging-port=9223 --user-data-dir=<暫存資料夾> https://www.oliveyoung.co.kr/`
2. `.\venv\Scripts\python.exe -m scripts.scrape_oliveyoung_reviews`（被擋會自己停）

**兩邊都一樣**：
- **每爬完一批（不管有沒有全部抓完），都跑一次 `python -m scripts.generate_review_summaries`
  補上新配對到評論的商品的 AI 摘要**（見 10-4b）
- 兩個爬蟲可以同時跑（用不同的 Chrome / port），但都會寫 MongoDB，Atlas 連線不穩時可能互相拖慢

## 11. 2026-09-24 綜合推薦排序 + RoBERTa 讀文字判斷正負評（已完成，47,290 則全部跑完）

### 11-1. 已完成：排序改成「綜合推薦」（`api/recommend.py`）

- 排序選項只剩 `recommended`（預設）/ `price_low` / `price_high`，**舊的 `relevance`、`rating` 已移除**（API 會回 422）。前端下拉選單、`api/main.py` 預設值都已同步。
- **2026-09-29 改成硬排序（不用權重）**，依序比較，前一個一樣才比下一個：
  1. 有沒有社群評論（沒有的一律排最後）
  2. 好評率等級：≥90% A、80~90% B、<80% C（`POS_RATE_GRADES`）；評論數 < 5 則最高只到 B（`MIN_REVIEWS_FOR_TOP_GRADE`）
  3. 平台星等 高→低
  4. 相關度 高→低
  - 好評率先分級，是因為連續小數幾乎不會同分，直接硬排序的話後面的條件永遠輪不到
  - 商品名稱精確命中的排在語意結果前面，但精確命中那批內部一樣照上面規則排
  - 不設相關度門檻；候選池 = `top_k × RERANK_POOL_MULTIPLIER(3)`，排完再取前 top_k
  - （09-24 第一版是加權分數 0.3×相關度＋0.7×口碑，已被取代）
- 資料庫查詢改成批次：好評/負評數一次 aggregate、AI 摘要一次 `$in`，不再逐筆查（實測每次搜尋 < 1 秒）
- 拿掉 `sample_reviews`（每個商品 3 則評論），前端沒有 AI 摘要時只顯示「評論配對 N 篇・好評率・正/負」

### 11-2. 硬排序版本待討論的點（等開會）

- 好評率分級的分界（90% / 80%）、評論數門檻（5 則）
- 同一級裡面好評率高低不再比：例如「化妝水＋保濕」Dress Snow 好評率 97% 排在 ETUDE 92% 後面，因為兩個都是 A 級、ETUDE 星等較高
- 相關度排在最後，實際上幾乎不影響排序
- 平台星等沒有考慮評分人數（117 人跟 3,961 人評分一樣看待）

### 11-3. RoBERTa 讀評論文字判斷正/負評（2026-09-24 全部跑完）

**團隊決定**：好評率要用 RoBERTa 讀評論**文字**判斷，不是星等；**模型判「中立」一律算負評**。

- 評論沒有中文翻譯（`raw_text` 是日韓原文，翻譯腳本只翻商品名/品牌），原本的中文 RoBERTa 看不懂日文（實測把「推薦！」判成負評），所以日韓文改用多語言 **`cardiffnlp/twitter-xlm-roberta-base-sentiment`**（需要 `sentencepiece`，已加進 requirements.txt）
- PTT/Dcard 是中文長文，多語言模型實測 99 則有 95 則判中立，所以**PTT/Dcard 沿用原本中文 RoBERTa 的結果**
- 寫到 reviews 新欄位（原本 `sentiment` 不動）：
  - `sentiment_roberta_raw`：`positive` / `neutral` / `negative`（PTT/Dcard 記成 `zh_model`）
  - `sentiment_roberta`：二元結果，`/recommend` 好評率讀這個；**還沒跑到的評論會退回舊的 `sentiment`（星等換算）**
  - 要改中立算法不用重跑模型，用 `sentiment_roberta_raw` 重算 `sentiment_roberta` 即可
- 程式：`nlp/sentiment.py`（新增 `analyze_batch_multilingual`，中文 `run_batch` 保留原模型）、`scripts/run_roberta_sentiment.py`

**跑完的結果**（47,290 則全部有 `sentiment_roberta`）：

| 來源 | 正 / 中立 / 負 | 好評率：舊（星等 ≥4）→ 新（RoBERTa，中立算負評） |
|---|---|---|
| 樂天 | 27,526 / 1,398 / 1,881 | 98.4% → 89.4% |
| Olive Young | 11,320 / 1,311 / 3,704 | 72.5% → 69.3% |
| PTT / Dcard | 沿用中文模型 | 不變（90.9% / 82.4%） |

之後新爬的樂天/Olive Young 評論要再跑一次 `python -m scripts.run_roberta_sentiment`（只會跑還沒跑過的），
沒跑之前 `/recommend` 會先用星等換算的 `sentiment`。CPU 實測約每秒 5~8 則。
在 Claude Code 裡跑長時間任務要用獨立程序（PowerShell `Start-Process`），綁在對話上的背景指令會在視窗關掉時一起被砍。

查進度：
```
python -c "from db.mongo_client import get_db; print(get_db().reviews.count_documents({'sentiment_roberta_raw': {chr(36) + 'exists': True}}), '/ 47290')"
```

## 12. 2026-10-02 組員「待改善.docx」8 點修正 + 品質檢查

### 12-1. 怎麼量：`scripts/quality_check.py`（只讀，不改資料）

8 個問題各一項檢查，**每項從相關母體隨機抽 200 筆，不到 200 就全部**，每次執行重新抽樣，結果存 `reports/quality_<時間>.json`（`reports/` 不進版控）。隨機抽樣誤差約 ±3～5%。

| # | 問題 | 改善前 | 改善後 | 怎麼修 |
|---|---|---|---|---|
| 1 | 出現一樣的東西 | 82.0% | 100% | `/recommend` 合併重複上架（用日韓**原文**去廣告詞後比對，中文是分開翻譯的比不出來；色號、片數、補充包不同不算重複）：`api/text_quality.is_duplicate` |
| 2 | 圖片離家出走 | 98.5% | 100% | 樂天賣家換圖舊網址 404：`scripts/fix_broken_images.py` 用 Playwright 開商品頁抓 og:image（樂天擋一般程式連線）；`/recommend` 圖片改從 MongoDB 讀 |
| 3 | 負評 0 卻有常見缺點 | 99.5% | 100% | 前端：負評 0 時標題改「好評中也有人提到」 |
| 4 | 有負評但沒有統整 | 79.0% | 99.5% | `scripts/fill_missing_cons.py`：有負評沒缺點摘要的 225 個商品，用「1 人提到也算」重新統計＋AI 寫摘要（補了 207 個）；前端只有 1 人提到時標題寫「少數使用者提到」 |
| 5 | 洗面奶是支語 | 99.0% | 100% | `scripts/fix_text_data.py --mainland`（41 筆），清單在 `api/text_quality.MAINLAND_TERMS` |
| 6 | 幹話太多 | 32.5% | 100% | 顯示名稱拿掉廣告詞、關鍵字清單、太長截斷（`api/text_quality.display_name`），資料庫原名不動，滑鼠移到名稱上看完整原名 |
| 7 | 亂打字也查得到 | 34.6% | 100% | 相似度門檻擋不了（tjgjfgke 0.711 ≈ 正常查詢 0.744），改規則：沒有中日韓文字、英文詞也不在任何商品名稱品牌裡 → 查無此資料（`api/recommend.looks_meaningful`） |
| 8 | 翻譯不正確（肌膚正確遮瑕膏） | 83.5% | 93.0% | `scripts/fix_text_data.py --translation`：Gemini 對照原文檢查 1972 筆，修正 776 筆（舊名存 `name_zh_before_fix`） |
| | **平均** | **76.1%** | **99.1%** | |

### 12-2. ⚠ 要人工確認的

- **第 8 點的 776 筆翻譯修正**：Gemini 偶爾會加油添醋（例：原文只有 ダイブイン マスク，被改成「Dive-In 低分子玻尿酸補水面膜」）。`scripts/review_name_fixes.py` 讓 AI 二次審查並標記可疑的，輸出到 `Downloads\商品名稱翻譯修正對照表.csv`（可疑的排最前面，2026-10-02 二次審查標出 219 筆），**人工看標記的那些**，改錯的可單筆還原成 `name_zh_before_fix`
- 第 8 項分數是 Gemini 檢查 Gemini 修過的翻譯，可能偏高，報告時要寫清楚量法

### 12-3. 備份與還原

- 改資料前整個 products 備份在 `reports/backup_products_20261002_171036.json`
- 全部還原名稱與摘要：`python -m scripts.fix_text_data --restore reports/backup_products_20261002_171036.json`
- 改了商品名稱後要重建搜尋索引（網站先關）：`python -c "from rag.embedder import build_product_index; build_product_index()"`

### 12-4. 其他順便修的

- `db/mongo_client.py`：Atlas 連線逾時 3 秒 → 15 秒；DNS 查不到 SRV 紀錄時自動重試並改用 8.8.8.8 / 1.1.1.1（這台的網路 DNS 常逾時，網站第一次搜尋會隨機 500）
- 回傳筆數上限 50 → 200（前端選單加 50/100/200）

### 12-5. 第二輪：OpenAI（gpt-4.1）獨立檢查與修正（2026-10-02）

Gemini 產生的內容改用不同家的 OpenAI 檢查（`scripts/openai_judge.py`），再依結果修正（`scripts/round2_fixes.py`），最後兩家各自判斷同一批樣本（`scripts/verify_dual.py`）。金鑰用 `--env` 指向另一份 .env，不寫進專案。

| 項目 | Gemini 判斷 | OpenAI 判斷 |
|---|---|---|
| 翻譯正確率（同一批 200，改善前 → 後） | 80.0% → 92.5% | 75.0% → 77.0%（未達 80%） |
| 補寫缺點摘要忠實度 | 額度用完未完成 | 第一輪 73.5% → 第二輪 95.5% |

第二輪：還原 80 筆「修正前較好」的翻譯（`name_fix_reverted`）、71 筆拿掉多加內容（`name_fix_stripped`，第一輪結果存 `name_zh_round1`）、缺點摘要重寫 77 個／移除 4 個（舊的存 `ai_summary.cons_round1`）。第二輪前備份：`reports/backup_products_20261002_202125.json`。
人工審核表已依兩家 AI 的疑慮排序：優先 64 筆、其次 125 筆。完整報告：https://claude.ai/artifact/1fiTsq3kZA3dXQi8Uq8NPQ

### 12-6. 第三輪（2026-10-03）：全商品重新翻譯 + 亂打警示

組員回報：名稱還有整段日文（ディオールショウ サンク クルール）、英文直譯（Pure C Mask → 純C面膜）。前兩輪只檢查「意思錯沒錯」並把保留原文當成沒錯，所以沒翻的日韓文沒被抓到。

- **重新翻譯**（`scripts/retranslate_all.py`，OpenAI gpt-4.1）：卡片上所有文字（名稱、品牌／店名、評論摘要、適合族群、缺點摘要）對照原文檢查，1,300 個商品 1,717 處修改（舊內容存 `v3_before.<欄位>`）。規則：日韓文一律翻成台灣繁中；英文品牌、系列名保留但說明翻出意思（Pure C Mask → 純維他命C面膜）；片假名品牌用台灣中文名（キュレル → 珂潤）；沒有中文名的專有名詞用官方英文或羅馬拼音；店名 公式ショップ → 官方商店。殘留的 34 個詞用逐詞替換＋6 筆人工修正。人工審核表：`Downloads\商品翻譯全面修正對照表_1003.csv`
- **亂打警示**（`api/recommend.query_warning`、`api/main.py` 的 `force`）：規則判斷是亂打（英文詞、中日韓兩字詞都不在商品資料裡；只有數字、注音）**或**第 1 名相似度 < 0.58（使用者指定）→ 回傳 `warning`，前端顯示〔回去修改〕〔仍要搜尋〕。相似度單獨用效果差（亂打 0.31～0.78、正常 0.577～0.94 重疊；中文亂打「的的的」0.70），主要靠規則
- 品質檢查第 7 項改成檢查警示（含中文亂打），新增第 9 項「沒有沒翻完的日韓文」（全部 1,973 筆，不抽樣；「・」「ー」標點不算）
- 第三輪前備份：`reports/backup_products_20261003_144925.json`

| 項目 | 結果 |
|---|---|
| 品質檢查 9 項平均 | 99.1%（第 7、9 項 100%） |
| 翻譯正確率（同一批 200，改善前 → 後） | Gemini 80.5% → 92.0%；OpenAI 67.5% → 81.0% |
| 缺點摘要忠實度（OpenAI） | 94.5%（Gemini 被限流，未完成） |
