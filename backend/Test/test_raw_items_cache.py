import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from Tools import crawl_and_index


class RawItemsCacheTests(unittest.TestCase):
    def test_naive_timestamp_and_malformed_entries_do_not_break_lookup(self):
        cache = {
            "valid": {
                "sellers": ["crazy11"],
                "keyword": "머큐리얼",
                "min_price": 0,
                "max_price": 199999,
                "cached_at": datetime.now(timezone.utc)
                .replace(tzinfo=None)
                .isoformat(),
                "items": [
                    "not-an-item",
                    {
                        "seller": "crazy11",
                        "product_name": "머큐리얼 베이퍼 16 TF",
                        "product_price": 129000,
                    },
                ],
            },
            "invalid-shape": "not-an-entry",
            "invalid-time": {"cached_at": {"not": "text"}},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "raw_items_cache.json"
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

            with patch.object(crawl_and_index, "_RAW_CACHE_PATH", str(cache_path)):
                items = crawl_and_index.load_raw_items_cache(
                    "머큐리얼 베이퍼 16 TF", min_price=100000, max_price=199999
                )

        self.assertEqual(len(items or []), 1)
        self.assertEqual(items[0]["product_price"], 129000)

    def test_no_price_limit_uses_overlapping_cache_and_filters_keyword_items(self):
        cache = {
            "all|머큐리얼|0|99999": {
                "sellers": ["crazy11", "soccerboom", "redsoccer", "cafostore"],
                "keyword": "머큐리얼",
                "min_price": 0,
                "max_price": 99999,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "items": [
                    {
                        "seller": "soccerboom",
                        "product_name": "주니어 머큐리얼 베이퍼 15 클럽 TF",
                        "product_price": 26900,
                        "product_url": "https://soccerboom.co.kr/product/1",
                    },
                    {
                        "seller": "crazy11",
                        "product_name": "나이키 머큐리얼 베이퍼 15 클럽 TF 주니어",
                        "product_price": 39000,
                        "product_url": "https://crazy11.co.kr/product/1",
                    },
                    {
                        "seller": "redsoccer",
                        "product_name": "나이키 줌 머큐리얼 베이퍼 15 아카데미 TF",
                        "product_price": 49000,
                        "product_url": "https://redsoccer.co.kr/product/1",
                    },
                    {
                        "seller": "cafostore",
                        "product_name": "나이키 머큐리얼 슈퍼플라이 10 TF",
                        "product_price": 59000,
                        "product_url": "https://cafostore.co.kr/product/1",
                    },
                ],
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "raw_items_cache.json"
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

            with patch.object(crawl_and_index, "_RAW_CACHE_PATH", str(cache_path)):
                items = crawl_and_index.load_raw_items_cache(
                    "머큐리얼 베이퍼 15 TF",
                    min_price=0,
                    max_price=9_999_999,
                )

        self.assertIsNotNone(items)
        self.assertEqual(
            ["crazy11", "redsoccer", "soccerboom"],
            sorted({item["seller"] for item in items}),
        )
        self.assertFalse(
            any("슈퍼플라이" in item["product_name"] for item in items or [])
        )

    def test_deduplicates_same_seller_and_product_name_across_cache_entries(self):
        base_item = {
            "seller": "crazy11",
            "product_name": "나이키 머큐리얼 베이퍼 15 클럽 TF 주니어",
            "product_price": 39000,
        }
        cache = {
            "crazy11|머큐리얼|0|99999": {
                "sellers": ["crazy11"],
                "keyword": "머큐리얼",
                "min_price": 0,
                "max_price": 99999,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "items": [
                    {
                        **base_item,
                        "product_url": "https://crazy11.co.kr/item?branduid=1&search=머큐리얼",
                    }
                ],
            },
            "crazy11|TF|0|99999": {
                "sellers": ["crazy11"],
                "keyword": "TF",
                "min_price": 0,
                "max_price": 99999,
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "items": [
                    {
                        **base_item,
                        "product_url": "https://crazy11.co.kr/item?branduid=1&search=TF",
                    }
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "raw_items_cache.json"
            cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

            with patch.object(crawl_and_index, "_RAW_CACHE_PATH", str(cache_path)):
                items = crawl_and_index.load_raw_items_cache(
                    "머큐리얼 베이퍼 15 TF",
                    min_price=0,
                    max_price=9_999_999,
                )

        self.assertEqual(1, len(items or []))


if __name__ == "__main__":
    unittest.main()
