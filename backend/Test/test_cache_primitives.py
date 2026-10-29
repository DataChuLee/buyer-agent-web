import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from Tools import crawl_registry


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


class NegativeCacheTests(unittest.IsolatedAsyncioTestCase):
    """접속 실패 판매처는 잠깐 재크롤을 건너뛰고, 실패한 판매처는 성공 캐시에 등록하지 않는다."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(crawl_registry, "_REGISTRY_PATH", str(Path(self.tempdir.name) / "r.json")),
            patch.dict(crawl_registry._recent_failures, clear=True),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tempdir.cleanup()

    def test_failure_expires_after_ttl(self):
        crawl_registry.mark_seller_failed("crazy11")
        self.assertTrue(crawl_registry.recently_failed("crazy11"))
        crawl_registry._recent_failures["crazy11"] -= timedelta(minutes=11)
        self.assertFalse(crawl_registry.recently_failed("crazy11"))

    async def test_failed_seller_is_skipped_and_not_registered(self):
        from Tools import crawl_and_index as cai

        item = {"seller": "사커붐", "product_name": "나이키 머큐리얼", "product_price": 99000, "product_url": "https://x.test/1"}
        crawl = AsyncMock(return_value={"items": [item], "errors": {"crazy11": "TimeoutError()"}})
        payload = {"sellers": ["crazy11", "soccerboom"], "product_keyword": "머큐리얼", "min_price": 0, "max_price": 999999}
        with (
            patch("Crawling.seller_total_test.crawl_multiple_sellers", crawl),
            patch.object(cai, "_add_new_documents", return_value=1),
            patch.object(cai, "_store_raw_items"),
        ):
            await cai.crawl_and_index.ainvoke(payload)
            # 성공한 판매처만 캐시에 등록, 실패한 판매처는 등록 안 됨(복구 후 재크롤 가능)
            self.assertTrue(crawl_registry.is_already_indexed(["soccerboom"], "머큐리얼", 0, 999999))
            self.assertFalse(crawl_registry.is_already_indexed(["crazy11"], "머큐리얼", 0, 999999))
            # 바로 다음 요청: 실패한 판매처는 타임아웃을 다시 기다리지 않고 건너뜀
            result = await cai.crawl_and_index.ainvoke({**payload, "sellers": ["crazy11"]})

        self.assertEqual(crawl.await_count, 1)
        self.assertIn("최근 접속에 실패한 판매처", result)
