import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from Tools import crawl_registry, web_search_cache


class CrawlRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.tempdir.name) / "crawl_registry.json"
        self.path_patch = patch.object(
            crawl_registry, "_REGISTRY_PATH", str(self.registry_path)
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.tempdir.cleanup()

    def test_exact_and_fuzzy_subset_hits(self):
        crawl_registry.register_crawl(
            ["crazy11", "soccerboom"], "머큐리얼", 0, 199_999, 12
        )

        self.assertTrue(
            crawl_registry.is_already_indexed(
                ["crazy11", "soccerboom"], "머큐리얼", 0, 199_999
            )
        )
        self.assertTrue(
            crawl_registry.is_already_indexed(
                ["crazy11"], "나이키 머큐리얼 베이퍼", 100_000, 199_999
            )
        )
        self.assertFalse(
            crawl_registry.is_already_indexed(
                ["redsoccer"], "나이키 머큐리얼 베이퍼", 100_000, 199_999
            )
        )

    def test_naive_timestamp_and_corrupt_entries_do_not_break_lookup(self):
        now_without_timezone = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        self.registry_path.write_text(
            json.dumps(
                {
                    "valid": {
                        "sellers": ["crazy11"],
                        "keyword": "머큐리얼",
                        "min_price": 0,
                        "max_price": 199_999,
                        "indexed_at": now_without_timezone,
                    },
                    "invalid-shape": "not-an-entry",
                    "invalid-price": {
                        "sellers": ["crazy11"],
                        "keyword": "머큐리얼",
                        "min_price": "invalid",
                        "max_price": None,
                        "indexed_at": now_without_timezone,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.assertTrue(
            crawl_registry.is_already_indexed(
                ["crazy11"], "나이키 머큐리얼", 100_000, 199_999
            )
        )


class WebSearchCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tempdir.name) / "web_search_cache.json"
        self.path_patch = patch.object(
            web_search_cache, "_CACHE_PATH", str(self.cache_path)
        )
        self.path_patch.start()
        with web_search_cache._L1_LOCK:
            web_search_cache._L1.clear()

    def tearDown(self):
        with web_search_cache._L1_LOCK:
            web_search_cache._L1.clear()
        self.path_patch.stop()
        self.tempdir.cleanup()

    async def test_l1_and_disk_hits_skip_duplicate_fetches(self):
        calls = 0

        async def fetch():
            nonlocal calls
            calls += 1
            return {"items": [1, 2]}

        first = await web_search_cache.cached_web_search("tavily", " Nike ", 60, fetch)
        second = await web_search_cache.cached_web_search("tavily", "nike", 60, fetch)
        with web_search_cache._L1_LOCK:
            web_search_cache._L1.clear()
        third = await web_search_cache.cached_web_search("tavily", "NIKE", 60, fetch)

        self.assertEqual(first, second)
        self.assertEqual(second, third)
        self.assertEqual(calls, 1)

    async def test_expired_naive_and_corrupt_entries_are_ignored(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(
            tzinfo=None
        )
        key = web_search_cache._cache_key("tavily", "nike")
        self.cache_path.write_text(
            json.dumps(
                {
                    key: {"result": "stale", "expires_at": expired.isoformat()},
                    "invalid": {"result": "bad", "expires_at": {"not": "text"}},
                }
            ),
            encoding="utf-8",
        )

        async def fetch():
            return "fresh"

        result = await web_search_cache.cached_web_search("tavily", "nike", 60, fetch)

        self.assertEqual(result, "fresh")
