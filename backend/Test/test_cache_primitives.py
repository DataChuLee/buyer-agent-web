import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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


