import unittest

from scrapers.product_schema import normalize_cosme, normalize_hwahae


class ProductSchemaTests(unittest.TestCase):
    def test_normalize_cosme(self):
        row = {
            "大分類": "護膚",
            "品牌(中)": "A品牌",
            "商品名(中)": "保濕精華",
            "價格": "715円",
            "商品連結": "https://example.com/products/123",
            "圖片": "https://img.example/1.jpg",
            "評分": "4.8",
            "口コミ數": "120",
        }

        product = normalize_cosme(row)

        self.assertEqual(product["source_platform"], "cosme")
        self.assertEqual(product["source_id"], "123")
        self.assertEqual(product["name_zh"], "保濕精華")
        self.assertEqual(product["brand_zh"], "A品牌")
        self.assertEqual(product["category"], "護膚")
        self.assertEqual(product["price"], 715)
        self.assertEqual(product["currency"], "JPY")
        self.assertEqual(product["rating_platform"], 4.8)
        self.assertEqual(product["review_count_platform"], 120)

    def test_normalize_hwahae(self):
        row = {
            "大分類(中)": "彩妝",
            "品牌(中)": "B品牌",
            "商品名(中)": "氣墊粉底",
            "KRW售價": "35000",
            "容量": "15g",
            "圖片URL": "https://img.example/2.jpg",
            "商品連結": "https://example.com/products/456",
            "平均評分": "4.6",
            "評論數": "80",
            "商品ID": "456",
        }

        product = normalize_hwahae(row)

        self.assertEqual(product["source_platform"], "hwahae")
        self.assertEqual(product["source_id"], "456")
        self.assertEqual(product["name_zh"], "氣墊粉底")
        self.assertEqual(product["brand_zh"], "B品牌")
        self.assertEqual(product["category"], "彩妝")
        self.assertEqual(product["price"], 35000)
        self.assertEqual(product["currency"], "KRW")
        self.assertEqual(product["capacity"], "15g")
        self.assertEqual(product["rating_platform"], 4.6)
        self.assertEqual(product["review_count_platform"], 80)


if __name__ == "__main__":
    unittest.main()
