import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from Agent.seller_search_agent import (
    SELLER_DOMAINS,
    _build_cache_table,
    _build_tavily_table,
    _excluded_seller_names,
    _normalize_candidates,
    _run_tavily,
    _seller_search_keyword,
    build_seller_search_query,
    is_no_seller_result_answer,
    parse_seller_markdown_table,
    run_seller_search_pipeline,
    search_sellers,
)
from Tools.crawl_and_index import _RAW_CACHE_STOPWORDS


def cache_row(seller="crazy11", price=99000, **overrides):
    domains = {"crazy11": "crazy11.co.kr", "soccerboom": "soccerboom.co.kr", "redsoccer": "redsoccer.co.kr", "capostore": "capostore.co.kr"}
    row = {
        "seller": seller,
        "raw_name": "나이키 머큐리얼 베이퍼 16 아카데미 FG",
        "product_price": price,
        "consumer_price": 149000,
        "source_url": f"https://{domains[seller]}/product/1",
        "availability": "판매 중",
        "sizes": [260, 270],
    }
    row.update(overrides)
    return row


def web_row(domain="soccerboom.co.kr", name="나이키 머큐리얼 베이퍼 16", text="판매가 99,000원 판매 중", **overrides):
    row = {"title": name, "content": text, "url": f"https://{domain}/item/1"}
    row.update(overrides)
    return row


class SellerSearchAgentModuleTest(unittest.TestCase):
    def test_supported_domains_match_project_contract(self):
        self.assertEqual(SELLER_DOMAINS, ["crazy11.co.kr", "soccerboom.co.kr", "redsoccer.co.kr", "capostore.co.kr"])

    def test_cache_normalization_and_parser_preserve_verified_fields(self):
        table = _build_cache_table([cache_row()], product_keyword="나이키 머큐리얼 베이퍼")
        cards = parse_seller_markdown_table(table)
        self.assertEqual("크레이지11", cards[0]["name"])
        self.assertEqual(99000, cards[0]["sale_price"])
        self.assertEqual("https://crazy11.co.kr/product/1", cards[0]["url"])
        self.assertEqual("판매 중", cards[0]["availability"])

    def test_web_result_rejects_unsupported_unpriced_unavailable_mismatch_and_corrupt(self):
        rows = [
            web_row(),
            web_row(domain="unsupported.example"),
            web_row(text="가격 문의 판매 중"),
            web_row(text="판매가 80,000원 품절"),
            web_row(name="나이키 머큐리얼 수퍼플라이", text="판매가 70,000원 판매 중"),
            None,
        ]
        candidates, rejected = _normalize_candidates(rows, "머큐리얼 베이퍼", source="web_search")
        self.assertEqual(1, len(candidates))
        for reason in ("unsupported_seller", "unverified_price", "unavailable", "product_mismatch", "invalid_candidate"):
            self.assertIn(reason, rejected)

    def test_sale_price_precedes_original_and_original_falls_back(self):
        candidates, _ = _normalize_candidates([
            cache_row(product_price="89,000원", consumer_price="129,000원"),
            cache_row("soccerboom", None, consumer_price="99,000원"),
        ], "머큐리얼 베이퍼", source="raw_cache")
        self.assertEqual([89000, 99000], [row["effective_price"] for row in candidates])

    def test_duplicate_url_is_removed(self):
        candidates, rejected = _normalize_candidates([cache_row(price=109000), cache_row(price=99000)], "머큐리얼 베이퍼", source="raw_cache")
        self.assertEqual(1, len(candidates))
        self.assertEqual(99000, candidates[0]["effective_price"])
        self.assertEqual(1, rejected["duplicate"])

    def test_exclusion_query_and_keyword_helpers(self):
        query = "머큐리얼 베이퍼 10만원대 판매처 추천 exclude: 크레이지11, 사커붐"
        self.assertEqual(frozenset({"크레이지11", "사커붐"}), _excluded_seller_names(query))
        self.assertEqual("머큐리얼 베이퍼", _seller_search_keyword(query))
        self.assertIn("사커붐 제외", build_seller_search_query("머큐리얼 베이퍼", rejected_sellers=["사커붐"]))
        self.assertIn("추천", _RAW_CACHE_STOPWORDS)

    def test_unverified_web_result_does_not_create_card(self):
        table = _build_tavily_table([{"url": "https://soccerboom.co.kr/item/1"}], product_keyword="머큐리얼 베이퍼")
        self.assertIn("찾지 못했습니다", table)
        self.assertEqual([], parse_seller_markdown_table(table))


class SellerPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_or_failed_product_input_never_calls_external_layers(self):
        queries = ("", "상품 검색 실패", "search_status=error 머큐리얼 베이퍼", "search_status=no_results 머큐리얼 베이퍼")
        for query in queries:
            with self.subTest(query=query), patch("Agent.seller_search_agent.load_raw_items_cache") as cache, patch("Agent.seller_search_agent._run_tavily", new_callable=AsyncMock) as web:
                result = await run_seller_search_pipeline(query)
                self.assertEqual("no_results", result["search_status"])
                cache.assert_not_called()
                web.assert_not_called()

    async def test_cache_hit_skips_web_and_excludes_user_seller(self):
        with patch("Agent.seller_search_agent.load_raw_items_cache", return_value=[cache_row(), cache_row("soccerboom")]), patch("Agent.seller_search_agent._run_tavily", new_callable=AsyncMock) as web:
            result = await run_seller_search_pipeline("머큐리얼 베이퍼 판매처 exclude: 크레이지11")
        self.assertEqual(("ok", "raw_cache"), (result["search_status"], result["source"]))
        self.assertEqual(["사커붐"], [row["seller"] for row in result["candidates"]])
        web.assert_not_called()

    async def test_cache_miss_calls_web_and_preserves_partial_failure(self):
        candidates, _ = _normalize_candidates([web_row()], "머큐리얼 베이퍼", source="web_search")
        web_result = {"search_status": "partial_failure", "source": "web_search", "candidates": candidates, "failed_sellers": ["레드사커"], "rejection_summary": {}}
        with patch("Agent.seller_search_agent.load_raw_items_cache", return_value=None), patch("Agent.seller_search_agent._run_tavily", new=AsyncMock(return_value=web_result)) as web:
            result = await run_seller_search_pipeline("머큐리얼 베이퍼 판매처")
        self.assertEqual("partial_failure", result["search_status"])
        self.assertEqual(["레드사커"], result["failed_sellers"])
        self.assertIn("일부 판매처 검색 실패", result["answer"])
        web.assert_awaited_once()

    async def test_corrupt_cache_falls_back_and_records_diagnostic(self):
        web_result = {"search_status": "no_results", "source": "web_search", "candidates": [], "failed_sellers": [], "rejection_summary": {}}
        with patch("Agent.seller_search_agent.load_raw_items_cache", side_effect=ValueError("corrupt")), patch("Agent.seller_search_agent._run_tavily", new=AsyncMock(return_value=web_result)):
            result = await run_seller_search_pipeline("머큐리얼 베이퍼 판매처")
        self.assertEqual("no_results", result["search_status"])
        self.assertEqual(1, result["rejection_summary"]["cache_error"])

    async def test_all_sellers_excluded_does_not_search(self):
        query = "머큐리얼 베이퍼 exclude: 크레이지11, 사커붐, 레드사커, 카포스토어"
        with patch("Agent.seller_search_agent.load_raw_items_cache") as cache, patch("Agent.seller_search_agent._run_tavily", new_callable=AsyncMock) as web:
            result = await run_seller_search_pipeline(query)
        self.assertEqual("no_results", result["search_status"])
        cache.assert_not_called()
        web.assert_not_called()

    async def test_branch_statuses_distinguish_partial_no_results_and_error(self):
        success = {"seller": "크레이지11", "status": "ok", "results": [web_row(domain="crazy11.co.kr")]}
        empty = {"seller": "사커붐", "status": "ok", "results": []}
        failure = {"seller": "레드사커", "status": "error", "results": []}
        fourth = {"seller": "카포스토어", "status": "ok", "results": []}
        with patch("Agent.seller_search_agent._run_tavily_branch", new=AsyncMock(side_effect=[success, empty, failure, fourth])):
            partial = await _run_tavily("머큐리얼 베이퍼", 0, 9999999)
        self.assertEqual("partial_failure", partial["search_status"])
        self.assertEqual(["레드사커"], partial["failed_sellers"])
        self.assertEqual(1, len(partial["candidates"]))
        with patch("Agent.seller_search_agent._run_tavily_branch", new=AsyncMock(side_effect=[empty, empty, fourth, empty])):
            none = await _run_tavily("머큐리얼 베이퍼", 0, 9999999)
        self.assertEqual("no_results", none["search_status"])
        failures = [{"seller": seller, "status": "error", "results": []} for seller in ("크레이지11", "사커붐", "레드사커", "카포스토어")]
        with patch("Agent.seller_search_agent._run_tavily_branch", new=AsyncMock(side_effect=failures)):
            error = await _run_tavily("머큐리얼 베이퍼", 0, 9999999)
        self.assertEqual("error", error["search_status"])
        self.assertEqual([], error["candidates"])

    async def test_web_search_skips_excluded_seller_branch_and_reports_ok(self):
        branches = [
            {"seller": "크레이지11", "status": "ok", "results": [web_row(domain="crazy11.co.kr")]},
            {"seller": "레드사커", "status": "ok", "results": []},
            {"seller": "카포스토어", "status": "ok", "results": []},
        ]
        with patch("Agent.seller_search_agent._run_tavily_branch", new=AsyncMock(side_effect=branches)) as branch:
            result = await _run_tavily("머큐리얼 베이퍼", 0, 9999999, frozenset({"사커붐"}))
        self.assertEqual("ok", result["search_status"])
        self.assertEqual(3, branch.await_count)
        called_domains = [call.args[0] for call in branch.await_args_list]
        self.assertNotIn("soccerboom.co.kr", called_domains)

    async def test_failure_response_never_parses_as_seller_card(self):
        with patch("Agent.seller_search_agent.load_raw_items_cache", return_value=None), patch(
            "Agent.seller_search_agent._run_tavily",
            new=AsyncMock(return_value={"search_status": "error", "source": "web_search", "candidates": [], "failed_sellers": ["크레이지11"], "rejection_summary": {}}),
        ):
            answer = await search_sellers.ainvoke({"query": "머큐리얼 베이퍼"})
        self.assertTrue(is_no_seller_result_answer(answer))
        self.assertEqual([], parse_seller_markdown_table(answer))


if __name__ == "__main__":
    unittest.main()
