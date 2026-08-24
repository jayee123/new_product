import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MONGO_URI      = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB       = os.getenv("MONGO_DB", "drugstore_demo")

GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_ID      = os.getenv("GOOGLE_CSE_ID", "")

# MySQL（會員系統）
MYSQL_HOST     = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT     = int(os.getenv("MYSQL_PORT", "3307"))
MYSQL_USER     = os.getenv("MYSQL_USER", "")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DB       = os.getenv("MYSQL_DB", "buytuoleai_auth")
JWT_SECRET       = os.getenv("JWT_SECRET", "")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

# Gemini API（翻譯 + 評論摘要）
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 爬蟲設定
REQUEST_DELAY  = 1.5   # 每次請求間隔秒數
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

# RAG 設定
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHROMA_PATH = "./chroma_db"
