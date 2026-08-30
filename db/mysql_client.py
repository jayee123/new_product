"""
MySQL 連線（僅供會員系統使用：註冊/登入/登出、JWT 黑名單）
跟商品/評論資料完全分開，商品資料一律走 MongoDB（見 mongo_client.py）
"""
import pymysql
from config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB


def get_connection():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        # Aiven（雲端 MySQL）強制要求 TLS 連線，本機 MySQL 沒這個要求但加了也不影響。
        ssl={"ssl": {}},
    )
