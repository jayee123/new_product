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


def _product_text_meta(p: dict) -> tuple[str, dict]:
    """一個商品 → (拿去算向量的文字, 搜尋結果帶的 metadata)。ChromaDB 和 numpy 備援共用"""
    name  = p.get("name_zh") or p.get("name_local", "")
    brand = p.get("brand_zh") or p.get("brand_local", "")
    text = " ".join(filter(None, [
        name,
        brand,
        p.get("category", ""),
        " ".join(p.get("ingredients", [])[:5]),
    ]))
    meta = {
        "name":                  name,
        "brand":                 brand,
        "origin":                "JP" if p.get("currency") == "JPY" else "KR",
        "image_url":             p.get("image_url", ""),
        "price":                 p.get("price") if p.get("price") is not None else -1,
        "currency":              p.get("currency", ""),
        "category":              p.get("category", ""),
        "product_type":          p.get("product_type", ""),
        "source_platform":       p.get("source_platform", ""),
        "rating_platform":       p.get("rating_platform") if p.get("rating_platform") is not None else -1.0,
        "review_count_platform": p.get("review_count_platform") if p.get("review_count_platform") is not None else 0,
    }
    return text, meta


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
        text, meta = _product_text_meta(p)
        texts.append(text)
        ids.append(p["source_url"])  # 用 URL 當唯一 ID
        metas.append(meta)

    embeddings = model.encode(texts, show_progress_bar=True).tolist()
    col.upsert(documents=texts, embeddings=embeddings, ids=ids, metadatas=metas)
    print(f"[RAG] 商品索引建立完成，共 {len(products)} 個商品")


# ─── 功能 2：使用者查詢 → 找相關商品 ──────────────────────────────────────

def query_products(user_query: str, top_k: int = 5, product_type: str = None) -> list[dict]:
    """
    使用者輸入需求描述，找最相關商品
    範例：query_products("乾性肌用的保濕精華，預算500以內")

    product_type: 指定的話，直接交給 ChromaDB 的 where 條件做「先篩範圍、再排語意相關度」，
                  不是撈一批語意相關的候選之後才在 Python 這邊篩掉不符合類型的——
                  因為統一產品類型分得很細（見 scripts/classify_product_types.py，40+ 種），
                  冷門類型（例如「精華液」只有 16 件）語意搜尋撈的那一批候選很可能運氣不好一件都沒中，
                  篩完變 0 筆。先用 where 縮小到該類型的商品，才不會有這個問題。
    """
    model  = get_model()
    try:
        chroma = get_chroma()
        col    = chroma.get_or_create_collection("products", metadata={"hnsw:space": "cosine"})
    except Exception as e:
        # 2026-11：Windows「智慧型應用程式控制」封鎖 chromadb 的 Rust DLL，ChromaDB 整個開不起來 →
        # 改用 numpy 備援，同一個模型、同一段商品文字，結果跟 ChromaDB 一樣
        global _chroma_failed
        if not _chroma_failed:
            print(f"[RAG] ChromaDB 無法使用，改用 numpy 備援搜尋：{str(e)[:120]}")
            _chroma_failed = True
        return _numpy_query(user_query, top_k, product_type)

    if col.count() == 0:
        print("[RAG] 向量索引為空，請先執行 build_product_index()")
        return []

    q_vec = model.encode([user_query]).tolist()
    where = {"product_type": product_type} if product_type else None
    results = col.query(query_embeddings=q_vec, n_results=top_k, where=where)

    output = []
    for i in range(len(results["ids"][0])):
        output.append({
            "source_url":  results["ids"][0][i],
            "document":    results["documents"][0][i],
            "similarity":  round(1 - results["distances"][0][i], 4),
            **results["metadatas"][0][i],
        })
    return output


# ─── ChromaDB 開不起來時的 numpy 備援 ─────────────────────────────────────

_chroma_failed = False
_np_index = None   # (ids, texts, metas, 正規化後的向量矩陣)


def _numpy_index():
    """從 MongoDB 讀商品、算向量（存在 CHROMA_PATH/numpy_fallback.pkl，商品文字沒變就直接讀快取）"""
    global _np_index
    if _np_index is None:
        import os
        import pickle
        import numpy as np
        rows = [(p["source_url"], *_product_text_meta(p)) for p in get_all_products() if p.get("source_url")]
        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        cache = os.path.join(CHROMA_PATH, "numpy_fallback.pkl")
        vecs = None
        if os.path.exists(cache):
            with open(cache, "rb") as f:
                c = pickle.load(f)
            if c.get("model") == EMBED_MODEL and c.get("texts") == texts:
                vecs = c["vecs"]
        if vecs is None:
            print(f"[RAG] numpy 備援：計算 {len(texts)} 個商品的向量（第一次約 1 分鐘）...")
            vecs = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
            os.makedirs(CHROMA_PATH, exist_ok=True)
            with open(cache, "wb") as f:
                pickle.dump({"model": EMBED_MODEL, "texts": texts, "vecs": vecs}, f)
        _np_index = (ids, texts, [r[2] for r in rows], np.asarray(vecs, dtype=np.float32))
    return _np_index


def _numpy_query(user_query: str, top_k: int, product_type: str = None) -> list[dict]:
    """跟 ChromaDB 的 cosine 查詢一樣：similarity = 餘弦相似度；有 product_type 就先篩類型再排序"""
    import numpy as np
    ids, texts, metas, mat = _numpy_index()
    q = get_model().encode([user_query], normalize_embeddings=True)[0].astype(np.float32)
    sims = mat @ q
    idx = [i for i in np.argsort(-sims)
           if not product_type or metas[i].get("product_type") == product_type][:top_k]
    return [{"source_url": ids[i], "document": texts[i], "similarity": round(float(sims[i]), 4), **metas[i]}
            for i in idx]


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
