import asyncio
import unittest
from unittest.mock import patch

from Crawling import seller_total_test


class CrawlerNormalizationTests(unittest.TestCase):
    def test_normalize_item_uses_nonempty_fallback_fields(self):
        raw = {
            "product_name": None,
            "product_price": None,
            "price": 109_000,
            "sizes": None,
            "image_url": None,
            "product_url": "",
            "detail_url": "https://seller.test/product/1",
        }

        item = seller_total_test.normalize_item("soccerboom", raw)

        self.assertEqual(item["seller"], "soccerboom")
        self.assertEqual(item["product_name"], "")
        self.assertEqual(item["product_price"], 109_000)
        self.assertEqual(item["sizes"], [])
        self.assertEqual(item["image_url"], "")
        self.assertEqual(item["product_url"], "https://seller.test/product/1")
        self.assertIs(item["raw"], raw)

    def test_dedupe_items_preserves_first_identical_row(self):
        first = {
            "seller": "soccerboom",
            "product_name": "머큐리얼",
            "product_price": 109_000,
            "product_url": "https://seller.test/product/1",
        }
        duplicate = dict(first)

        self.assertEqual(seller_total_test.dedupe_items([first, duplicate]), [first])


class CrawlerRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_one_seller_normalizes_async_crawler_output(self):
        async def fake_crawler(**kwargs):
            self.assertEqual(kwargs["product_keyword"], "머큐리얼")
            return [{"product_name": "제품", "price": 99_000}]

        def run_coro(coro):
            return asyncio.run(coro)

        with (
            patch.dict(
                seller_total_test.SELLER_CRAWLERS,
                {"soccerboom": fake_crawler},
                clear=False,
            ),
            patch.object(
                seller_total_test,
                "_run_async_in_new_loop",
                side_effect=run_coro,
            ),
        ):
            result = await seller_total_test.run_one_seller(
                seller="soccerboom",
                product_keyword="머큐리얼",
                min_price=0,
                max_price=199_999,
                seller_semaphore=asyncio.Semaphore(1),
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_price"], 99_000)
        self.assertEqual(result[0]["seller"], "soccerboom")
