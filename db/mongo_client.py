from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB

_client = None


def sanitize_for_mongo(value):
    """把超過 BSON 8-byte 數字上限的數值轉成字串，避免寫入 MongoDB 失敗。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, int) and (value < -(2**63) or value > 2**63 - 1):
            return str(value)
        if isinstance(value, float) and (value < -(2**63) or value > 2**63 - 1):
            return str(value)
        return value
    return value

def get_db():
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    return _client[MONGO_DB]


def save_product(product: dict) -> str:
    db = get_db()
    safe_product = {}
    for key, value in product.items():
        if isinstance(value, dict):
            safe_product[key] = {k: sanitize_for_mongo(v) for k, v in value.items()}
        elif isinstance(value, list):
            safe_product[key] = [sanitize_for_mongo(v) for v in value]
        else:
            safe_product[key] = sanitize_for_mongo(value)

    result = db.products.update_one(
        {"source_url": safe_product["source_url"]},
        {"$set": safe_product},
        upsert=True
    )
    return str(result.upserted_id or safe_product.get("source_url"))


def save_review(review: dict) -> str:
    db = get_db()
    result = db.reviews.update_one(
        {"source_url": review["source_url"]},
        {"$set": review},
        upsert=True
    )
    return str(result.upserted_id or review.get("source_url"))


def get_all_products() -> list:
    return list(get_db().products.find({}, {"_id": 0}))


def get_all_reviews() -> list:
    return list(get_db().reviews.find({}, {"_id": 0}))


def count_summary():
    db = get_db()
    return {
        "products": db.products.count_documents({}),
        "reviews":  db.reviews.count_documents({}),
    }
