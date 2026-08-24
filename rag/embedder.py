"""
RAG 向量化模組
功能 1：評論 ↔ 商品 配對（把評論提到的商品自動對齊）
功能 2：使用者查詢 ↔ 商品 搜尋（輸入需求，找最相關商品）

使用：
  - sentence-transformers（多語言，支援中/日/韓）
  - ChromaDB（本機向量資料庫，零設定）
"""
import chromadb
from sentence_transformers import SentenceTransformer
from config import EMBED_MODEL, CHROMA_PATH
from db.mongo_client import get_all_products, get_all_reviews, get_db

_model  = None
_chroma = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"[RAG] 載入嵌入模型 {EMBED_MODEL}（首次需下載 ~120MB）...")
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def get_chroma():
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=CHROMA_PATH)
    return _chroma


# ─── 功能 1：建立商品向量索引 ───────────────────────────────────────────────

def build_product_index():
    """把所有商品存入 ChromaDB 向量索引"""
    products = get_all_products()
    if not products:
        print("[RAG] 商品資料庫為空，請先跑爬蟲")
        return

    model  = get_model()
    chroma = get_chroma()
    col    = chroma.get_or_create_collection("products", metadata={"hnsw:space": "cosine"})

    # 組合每個商品的文字描述，用來生成向量
    texts = []
    ids   = []
    metas = []
    for p in products:
        name  = p.get("name_zh") or p.get("name_local", "")
        brand = p.get("brand_zh") or p.get("brand_local", "")
        text = " ".join(filter(None, [
            name,
            brand,
            p.get("category", ""),
            " ".join(p.get("ingredients", [])[:5]),
        ]))
        texts.append(text)
        ids.append(p["source_url"])  # 用 URL 當唯一 ID
        metas.append({
            "name":                  name,
            "brand":                 brand,
            "origin":                "JP" if p.get("currency") == "JPY" else "KR",
            "image_url":             p.get("image_url", ""),
            "price":                 p.get("price") if p.get("price") is not None else -1,
            "currency":              p.get("currency", ""),
            "category":              p.get("category", ""),
            "source_platform":       p.get("source_platform", ""),
            "rating_platform":       p.get("rating_platform") if p.get("rating_platform") is not None else -1.0,
            "review_count_platform": p.get("review_count_platform") if p.get("review_count_platform") is not None else 0,
        })

    embeddings = model.encode(texts, show_progress_bar=True).tolist()
    col.upsert(documents=texts, embeddings=embeddings, ids=ids, metadatas=metas)
    print(f"[RAG] 商品索引建立完成，共 {len(products)} 個商品")


# ─── 功能 2：使用者查詢 → 找相關商品 ──────────────────────────────────────

def query_products(user_query: str, top_k: int = 5) -> list[dict]:
    """
    使用者輸入需求描述，找最相關商品
    範例：query_products("乾性肌用的保濕精華，預算500以內")
    """
    model  = get_model()
    chroma = get_chroma()
    col    = chroma.get_or_create_collection("products", metadata={"hnsw:space": "cosine"})

    if col.count() == 0:
        print("[RAG] 向量索引為空，請先執行 build_product_index()")
        return []

    q_vec = model.encode([user_query]).tolist()
    results = col.query(query_embeddings=q_vec, n_results=top_k)

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "source_url":  results["ids"][0][i],
            "document":    results["documents"][0][i],
            "similarity":  round(1 - results["distances"][0][i], 4),
            **results["metadatas"][0][i],
        })
    return output


# ─── 功能 3：評論 ↔ 商品 配對 ──────────────────────────────────────────────

def match_reviews_to_products(batch_size: int = 50, threshold: float = 0.65):
    """
    從 reviews 集合取未配對的文章，
    用向量相似度找最相關的商品，寫入 review.product_id
    """
    model  = get_model()
    chroma = get_chroma()
    col    = chroma.get_or_create_collection("products", metadata={"hnsw:space": "cosine"})

    if col.count() == 0:
        print("[RAG] 商品向量索引為空，請先執行 build_product_index()")
        return

    db = get_db()
    reviews = list(
        db.reviews.find({"product_id": None}, {"_id": 1, "raw_text": 1, "title": 1}).limit(batch_size)
    )
    print(f"[RAG] 待配對評論：{len(reviews)} 篇")

    matched = 0
    for rev in reviews:
        text = (rev.get("title", "") + " " + rev.get("raw_text", ""))[:300]
        q_vec = model.encode([text]).tolist()
        result = col.query(query_embeddings=q_vec, n_results=1)

        if not result["ids"][0]:
            continue
        distance   = result["distances"][0][0]
        similarity = 1 - distance
        product_url = result["ids"][0][0]
        product_name = result["metadatas"][0][0].get("name", "")

        if similarity >= threshold:
            db.reviews.update_one(
                {"_id": rev["_id"]},
                {"$set": {"product_id": product_url, "match_score": round(similarity, 4)}}
            )
            matched += 1
            print(f"  ✓ 配對成功 ({similarity:.2f}): {rev.get('title','')[:30]} → {product_name[:30]}")
        else:
            print(f"  ✗ 相似度過低 ({similarity:.2f}): {rev.get('title','')[:30]}")

    print(f"\n[RAG] 配對完成：{matched}/{len(reviews)} 篇成功配對")


if __name__ == "__main__":
    print("=== 建立商品向量索引 ===")
    build_product_index()

    print("\n=== 測試使用者查詢 ===")
    queries = [
        "乾性肌保濕精華，預算500以內",
        "敏感肌防曬，不白臉",
        "韓國蝸牛黏蛋白修護",
    ]
    for q in queries:
        print(f"\n查詢：{q}")
        results = query_products(q, top_k=3)
        for r in results:
            print(f"  [{r['similarity']}] {r['name']} ({r['origin']}) {r['price']} {r['currency']}")

    print("\n=== 評論配對 ===")
    match_reviews_to_products(batch_size=20)
