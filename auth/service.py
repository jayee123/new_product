"""
會員系統核心邏輯：註冊 / 登入 / 登出
對應企劃書 FR3、程序規格書-3。資料存在 MySQL（見 db/mysql_client.py），
跟商品/評論資料（MongoDB）完全獨立，不參與推薦流程。
"""
import re
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from config import JWT_SECRET, JWT_EXPIRE_HOURS
from db.mysql_client import get_connection

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """給 API 層轉成 HTTP 4xx 錯誤用"""


def register(email: str, password: str, confirm_password: str) -> dict:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("email 格式不正確")
    if len(password) < 8:
        raise AuthError("密碼至少要 8 碼")
    if password != confirm_password:
        raise AuthError("兩次密碼輸入不一致")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                raise AuthError("這個 email 已經註冊過了")
            cur.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                (email, password_hash),
            )
        return {"message": "註冊成功"}
    finally:
        conn.close()


def login(email: str, password: str) -> dict:
    email = email.strip().lower()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, password_hash FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
    finally:
        conn.close()

    if not user or not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        raise AuthError("email 或密碼錯誤")

    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=JWT_EXPIRE_HOURS)
    jti = f"{user['id']}-{int(now.timestamp() * 1000)}"
    token = jwt.encode(
        {"sub": str(user["id"]), "email": email, "jti": jti, "iat": now, "exp": exp},
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"token": token, "expires_at": exp.isoformat()}


def decode_token(token: str) -> dict:
    """驗證 token 有效、還沒過期、也還沒被登出撤銷過"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError("token 已過期，請重新登入")
    except jwt.InvalidTokenError:
        raise AuthError("token 無效")

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM revoked_tokens WHERE jti=%s", (payload["jti"],))
            if cur.fetchone():
                raise AuthError("token 已經登出，請重新登入")
    finally:
        conn.close()

    return payload


def logout(token: str) -> dict:
    payload = decode_token(token)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO revoked_tokens (jti, expires_at) VALUES (%s, FROM_UNIXTIME(%s))",
                (payload["jti"], payload["exp"]),
            )
        return {"message": "已登出"}
    finally:
        conn.close()


def try_get_user_id(authorization_header: str) -> int:
    """
    給 /recommend 這種「登入非必要」的端點用：有帶合法 token 就回傳 user_id，
    沒帶、或 token 無效/過期/已登出，都直接回傳 None，不丟例外、不擋請求。
    """
    if not authorization_header or not authorization_header.startswith("Bearer "):
        return None
    token = authorization_header[len("Bearer "):]
    try:
        payload = decode_token(token)
        return int(payload["sub"])
    except Exception:
        return None


def save_search_history(user_id: int, query: str, country: str = None,
                         budget: int = None, category: str = None) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO search_history (user_id, query, country, budget, category) "
                "VALUES (%s, %s, %s, %s, %s)",
                (user_id, query[:500], country, budget, category),
            )
    finally:
        conn.close()


def get_search_history(user_id: int, limit: int = 20) -> list:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT query, country, budget, category, created_at FROM search_history "
                "WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                (user_id, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return rows
