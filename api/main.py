"""
FastAPI 推薦系統入口

執行：
  cd drugstore-demo
  python -m uvicorn api.main:app --reload --port 8000

測試：
  curl -X POST http://localhost:8000/recommend -H "Content-Type: application/json" ^
       -d "{\"query\": \"乾性肌保濕精華，預算500以內\", \"country\": \"JP\", \"top_k\": 5}"
"""
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from api.recommend import recommend, SORT_OPTIONS
from auth.service import (
    AuthError,
    register as auth_register,
    login as auth_login,
    logout as auth_logout,
    try_get_user_id,
    save_search_history,
    get_search_history,
)
from db.mongo_client import count_summary

app = FastAPI(title="Buy託了AI 推薦 API")

# 前端是本機開的靜態 HTML（file://），瀏覽器會把它當成 null origin，
# 這裡只是本機demo，不對外開放，直接放行所有來源最簡單。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RecommendRequest(BaseModel):
    query: str = Field(..., description="使用者需求描述，例如「乾性肌保濕精華，預算500以內」")
    budget: Optional[int] = Field(None, description="預算上限，單位新台幣（會自動把商品原幣別換算成台幣再比較）")
    country: Optional[str] = Field(None, description='"JP" 或 "KR"，不填代表兩邊都找')
    category: Optional[str] = Field(None, description="分類關鍵字子字串比對，例如「防曬」")
    top_k: int = Field(10, ge=1, le=50, description="回傳幾筆")
    sort_by: str = Field(
        "relevance",
        description='排序方式："relevance"（語意相關度，預設）/ "rating"（好評率高→低）/ '
                    '"price_low"（價格低→高）/ "price_high"（價格高→低）',
    )

    @field_validator("sort_by")
    @classmethod
    def _check_sort_by(cls, v):
        if v not in SORT_OPTIONS:
            raise ValueError(f"sort_by 必須是 {SORT_OPTIONS} 其中之一")
        return v


class RegisterRequest(BaseModel):
    email: str = Field(..., description="電子郵件")
    password: str = Field(..., description="密碼，至少 8 碼")
    confirm_password: str = Field(..., description="確認密碼，需跟 password 一致")


class LoginRequest(BaseModel):
    email: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok", **count_summary()}


@app.post("/auth/register")
def register_endpoint(req: RegisterRequest):
    try:
        return auth_register(req.email, req.password, req.confirm_password)
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/auth/login")
def login_endpoint(req: LoginRequest):
    try:
        return auth_login(req.email, req.password)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/logout")
def logout_endpoint(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail='需要帶 "Authorization: Bearer <token>" 標頭')
    token = authorization[len("Bearer "):]
    try:
        return auth_logout(token)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/recommend")
def recommend_endpoint(req: RecommendRequest, authorization: str = Header(None)):
    results = recommend(
        query=req.query,
        budget=req.budget,
        country=req.country,
        category=req.category,
        top_k=req.top_k,
        sort_by=req.sort_by,
    )

    # 有登入的話悄悄記錄這次搜尋，讓「搜尋紀錄只有自己看得到」這件事真的有意義；
    # 沒登入／token 失效都不影響搜尋本身，只是不記錄
    user_id = try_get_user_id(authorization)
    if user_id is not None:
        try:
            save_search_history(user_id, req.query, req.country, req.budget, req.category)
        except Exception:
            pass  # 存紀錄失敗不該讓搜尋整個掛掉

    return {"query": req.query, "count": len(results), "results": results}


@app.get("/auth/history")
def history_endpoint(authorization: str = Header(None)):
    user_id = try_get_user_id(authorization)
    if user_id is None:
        raise HTTPException(status_code=401, detail="請先登入才能查看搜尋紀錄")
    return {"history": get_search_history(user_id)}
