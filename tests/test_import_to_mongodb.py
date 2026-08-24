import unittest

from db.mongo_client import sanitize_for_mongo
from import_to_mongodb import normalize_product_from_row


class ImportToMongoDBTests(unittest.TestCase):
    def test_sanitize_for_mongo_converts_large_ints_to_str(self):
        self.assertEqual(sanitize_for_mongo(2**63), str(2**63))

    def test_normalize_product_from_row(self):
        row = {
            "商品名(中)": "保濕精華",
            "品牌(中)": "A品牌",
            "大分類": "護膚",
            "KRW售價": "15000",
            "商品連結": "https://example.com/product",
            "評分": "4.8",
            "評論數": "120",
        }

        product = normalize_product_from_row(row)

        self.assertEqual(product["name_zh"], "保濕精華")
        self.assertEqual(product["brand_zh"], "A品牌")
        self.assertEqual(product["category"], "護膚")
        self.assertEqual(product["price"], 15000)
        self.assertEqual(product["currency"], "KRW")
        self.assertEqual(product["source_url"], "https://example.com/product")


if __name__ == "__main__":
    unittest.main()
