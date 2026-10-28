import asyncio
import os
import sys
import unittest
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


from Agent.product_search_agent import (
    BRAND_RULES,
    PRODUCT_SEARCH_DOMAINS,
    PRODUCT_SEARCH_DOMAIN_LABELS,
    SERIES_BRAND,
    SERIES_DESCRIPTIONS,
    SERIES_PATTERNS,
    build_product_search_pipeline_result,
    build_product_search_query,
    build_product_search_fallback_answer,
    build_tavily_product_search_query,
    build_recommendation_reason,
    collect_product_filter_diagnostics,
    dedupe_extracted_series,
    extract_product_items,
    extract_series_name,
    filter_normalized_products,
    filter_tavily_candidates,
    format_tavily_price_diagnostics,
    format_unfiltered_tavily_results,
    is_no_result_answer,
    parse_product_markdown_table,
    run_product_search_pipeline,
    _raw_cache_search_items,
    _raw_cache_search_keyword,
    _raw_cache_search_keywords,
)


class ProductSearchAgentModuleTest(unittest.TestCase):
    def test_supported_sellers_use_capostore_domain(self):
        self.assertEqual(
            PRODUCT_SEARCH_DOMAINS,
            [
                "crazy11.co.kr",
                "soccerboom.co.kr",
                "redsoccer.co.kr",
                "capostore.co.kr",
            ],
        )
        self.assertEqual(PRODUCT_SEARCH_DOMAIN_LABELS["capostore.co.kr"], "카포스토어")
        self.assertNotIn("cafostore.co.kr", PRODUCT_SEARCH_DOMAINS)

    def test_build_product_search_query_keeps_series_search_terms(self):
        query = build_product_search_query(
            {
                "brand": "나이키",
                "budget": "10만원대",
                "surface": "FG",
                "position": "공격수",
            },
            rejected_series=["티엠포"],
        )

        self.assertIn("나이키", query)
        self.assertIn("10만원대", query)
        self.assertIn("FG", query)
        self.assertIn("축구화 풋살화 시리즈 추천", query)
        self.assertIn("티엠포 제외", query)
        self.assertNotIn("270", query)

    def test_tavily_query_does_not_force_price_when_budget_missing(self):
        query = build_tavily_product_search_query("발볼 넓은 나이키 축구화 추천")

        self.assertIn("시리즈 추천", query)
        self.assertNotIn("판매가", query)
        self.assertNotIn("가격 필터", query)

    def test_candidate_filter_uses_score_threshold_and_url_drop_list(self):
        parallel_result = {
            "soccerboom": {
                "seller": "사커붐",
                "domain": "soccerboom.co.kr",
                "ok": True,
                "results": [
                    {
                        "title": "축구화,풋살화 | 나이키",
                        "url": "https://soccerboom.co.kr/category/nike",
                        "content": "상품명 : 나이키 팬텀 6 FG/MG + 판매가 : 150,000원",
                        "score": 0.7,
                        "domain_ok": True,
                    },
                    {
                        "title": "이벤트",
                        "url": "https://soccerboom.co.kr/board/event",
                        "content": "상품명 : 나이키 팬텀",
                        "score": 0.9,
                        "domain_ok": True,
                    },
                    {
                        "title": "낮은 점수",
                        "url": "https://soccerboom.co.kr/category/low",
                        "content": "상품명 : 나이키 머큐리얼",
                        "score": 0.34,
                        "domain_ok": True,
                    },
                ],
            },
            "outside": {
                "seller": "외부",
                "domain": "example.com",
                "ok": True,
                "results": [
                    {
                        "title": "외부",
                        "url": "https://example.net/item",
                        "content": "상품명 : 나이키 팬텀",
                        "score": 0.99,
                        "domain_ok": False,
                    }
                ],
            },
        }

        candidates = filter_tavily_candidates(parallel_result)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["seller"], "사커붐")
        self.assertEqual(candidates[0]["keep_reason"], "score_threshold")

    def test_product_item_extraction_pairs_product_name_and_sale_price(self):
        candidate = {
            "seller": "사커붐",
            "seller_key": "soccerboom",
            "url": "https://soccerboom.co.kr/category/test",
            "title": "축구화,풋살화 | 나이키",
            "rank": 1,
            "score": 0.77,
            "content": (
                "상품명 : 나이키 ACG 타월(FJ2366-012) + 제조사 : 나이키 + "
                "소비자가 : 100,000원 + 판매가 : 54,900원 + "
                "상품명 : 줌 머큐리얼 베이퍼 16 엘리트 AG-PRO(IU3519-850) + "
                "제조사 : 나이키 + 소비자가 : 339,000원 + 판매가 : 186,000원"
            ),
        }

        items = extract_product_items([candidate])

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["raw_name"], "나이키 ACG 타월(FJ2366-012)")
        self.assertEqual(items[0]["sale_price"], 54900)
        self.assertEqual(items[1]["raw_name"], "줌 머큐리얼 베이퍼 16 엘리트 AG-PRO(IU3519-850)")
        self.assertEqual(items[1]["consumer_price"], 339000)
        self.assertEqual(items[1]["sale_price"], 186000)

    def test_rule_based_filter_applies_brand_budget_and_surface(self):
        items = [
            {
                "raw_name": "나이키 ACG 타월(FJ2366-012)",
                "brand": "나이키",
                "sale_price": 54900,
                "consumer_price": 100000,
                "source_url": "https://soccerboom.co.kr/towel",
                "search_score": 0.9,
            },
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800)",
                "brand": "나이키",
                "sale_price": 150000,
                "consumer_price": 179000,
                "source_url": "https://redsoccer.co.kr/phantom",
                "search_score": 0.8,
            },
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 TF(HQ2032-446)",
                "brand": "나이키",
                "sale_price": 150000,
                "consumer_price": 179000,
                "source_url": "https://soccerboom.co.kr/phantom-tf",
                "search_score": 0.7,
            },
            {
                "raw_name": "아디다스 F50 아카데미 FG(JH1234)",
                "brand": "아디다스",
                "sale_price": 150000,
                "consumer_price": 179000,
                "source_url": "https://capostore.co.kr/f50",
                "search_score": 0.7,
            },
        ]

        filtered = filter_normalized_products(items, "나이키 10만원대 FG 축구화 추천")

        self.assertEqual(len(filtered), 1)
        # 세대 번호(6)는 시리즈명에서 일부러 뺀다 — 시리즈 추천은 SKU 단위가 아니라 라인업 단위.
        self.assertEqual(filtered[0]["series_name"], "팬텀")
        self.assertEqual(filtered[0]["surface"], "FG/MG")
        self.assertEqual(filtered[0]["sale_price"], 150000)

    def test_retry_exclude_clause_filters_out_rejected_series_but_keeps_others(self):
        # 회귀: workers.py가 retry("다른 거 없어?") 시 쿼리에 붙이는 "exclude: A, B" 절이 그대로
        # classify_product_item()의 _requested_series_name()에 흘러가면, 제외 대상 시리즈명이
        # 오히려 "요청된 시리즈"로 오인식돼 그 시리즈만 통과시키고 다른 시리즈는 전부 걸러버렸다
        # (실사용 재현: "다른 거 없어?"가 방금 거절한 것과 같은/유사한 시리즈만 다시 보여줌).
        items = [
            {
                "raw_name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF(FQ8687-300)",
                "brand": "나이키",
                "sale_price": 109000,
                "source_url": "https://crazy11.co.kr/vapor",
                "search_score": 0.9,
            },
            {
                "raw_name": "나이키 팬텀 GX2 엘리트 TF",
                "brand": "나이키",
                "sale_price": 115000,
                "source_url": "https://soccerboom.co.kr/phantom",
                "search_score": 0.8,
            },
        ]
        query = "나이키 10만원대 TF exclude: 머큐리얼 베이퍼 축구화 추천"

        accepted, rejected, summary = collect_product_filter_diagnostics(items, query)

        self.assertEqual([item["series_name"] for item in accepted], ["팬텀"])
        self.assertEqual(summary.get("excluded_series"), 1)

    def test_price_filter_uses_sale_price_before_consumer_price_for_budget(self):
        items = [
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800)",
                "brand": "나이키",
                "sale_price": 85000,
                "consumer_price": 109000,
                "source_url": "https://redsoccer.co.kr/phantom",
                "search_score": 0.8,
            }
        ]

        filtered = filter_normalized_products(items, "나이키 10만원대 FG 축구화 추천")

        self.assertEqual(filtered, [])

    def test_price_filter_falls_back_to_consumer_price_only_when_sale_price_is_missing(self):
        items = [
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800)",
                "brand": "나이키",
                "sale_price": None,
                "consumer_price": 109000,
                "source_url": "https://redsoccer.co.kr/phantom",
                "search_score": 0.8,
            }
        ]

        filtered = filter_normalized_products(items, "나이키 10만원대 FG 축구화 추천")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["price_match_source"], "consumer_price")
        self.assertEqual(filtered[0]["price_match_value"], 109000)

    def test_pipeline_returns_rejection_diagnostics_when_strict_filters_remove_all_items(self):
        parallel_result = {
            "soccerboom": {
                "seller": "사커붐",
                "domain": "soccerboom.co.kr",
                "ok": True,
                "results": [
                    {
                        "title": "축구화,풋살화 | 나이키",
                        "url": "https://soccerboom.co.kr/category/nike",
                        "score": 0.7,
                        "domain_ok": True,
                        "content": (
                            "상품명 : 나이키 팬텀 6 로우 아카데미 TF(HQ2032-446) + "
                            "제조사 : 나이키 + 소비자가 : 109,000원 + 판매가 : 80,700원"
                        ),
                    }
                ],
            }
        }

        result = build_product_search_pipeline_result(
            "나이키 10만원대 FG 축구화 추천",
            parallel_result,
        )

        self.assertEqual(result["deduped_series"], [])
        self.assertEqual(result["rejection_summary"]["price_mismatch"], 1)
        self.assertEqual(result["rejected_products"][0]["reject_reason"], "price_mismatch")

    def test_pipeline_result_builds_parseable_series_table(self):
        parallel_result = {
            "redsoccer": {
                "seller": "레드사커",
                "domain": "redsoccer.co.kr",
                "ok": True,
                "results": [
                    {
                        "title": "대한민국 축구 전문 쇼핑몰 레드사커",
                        "url": "https://www.redsoccer.co.kr/m/product_list.html?xcode=030&type=Y",
                        "score": 0.67,
                        "domain_ok": True,
                        "content": (
                            "상품명 : 나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800) + "
                            "제조사 : 나이키 + 소비자가 : 179,000원 + 판매가 : 150,000원 + "
                            "상품명 : 나이키 팬텀 6 로우 아카데미 TF(HQ2032-446) + "
                            "제조사 : 나이키 + 소비자가 : 109,000원 + 판매가 : 80,700원"
                        ),
                    }
                ],
            }
        }

        result = build_product_search_pipeline_result(
            "나이키 10만원대 FG 축구화 추천",
            parallel_result,
        )
        cards = parse_product_markdown_table(result["answer"])

        self.assertEqual(len(result["filtered_candidates"]), 1)
        self.assertEqual(len(result["product_items"]), 2)
        self.assertEqual(len(result["deduped_series"]), 1)
        # 사용자 노출 텍스트는 시리즈명 + 추천 이유만 담는다 — 가격/URL은 내부 파이프라인
        # 데이터(deduped_series)에는 남아있지만 더 이상 표시 텍스트로 파싱되지 않는다.
        self.assertEqual(result["deduped_series"][0]["sale_price"], 150000)
        self.assertEqual(cards[0]["name"], "팬텀")
        self.assertIn("예산", cards[0]["recommendation"])
        self.assertIn("지면", cards[0]["recommendation"])

    def test_recommendation_reason_uses_structured_match_context(self):
        reason = build_recommendation_reason(
            {
                "brand": "나이키",
                "series_name": "팬텀 6",
                "surface": "TF",
                "sale_price": 139800,
                "price_match_source": "sale_price",
            },
            "나이키 10만원대 TF 축구화 추천",
        )

        self.assertIn("나이키", reason)
        self.assertIn("10만원대", reason)
        self.assertIn("TF", reason)

    def test_fallback_answer_does_not_create_unverified_seller_or_price(self):
        answer = build_product_search_fallback_answer(
            "나이키 10만원대 축구화 추천",
            {"price_mismatch": 3},
        )

        self.assertIn("판매처 검색에서는", answer)
        self.assertIn("일반적인 시리즈 기준", answer)
        self.assertNotIn("139,000원", answer)
        self.assertNotIn("https://", answer)

    def test_dedupe_prefers_higher_search_score_for_same_series(self):
        rows = [
            {
                "brand": "나이키",
                "series_name": "팬텀 6",
                "surface": "FG/MG",
                "sale_price": 150000,
                "seller": "레드사커",
                "search_score": 0.5,
            },
            {
                "brand": "나이키",
                "series_name": "팬텀 6",
                "surface": "FG/MG",
                "sale_price": 150000,
                "seller": "레드사커",
                "search_score": 0.8,
            },
        ]

        deduped = dedupe_extracted_series(rows)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["search_score"], 0.8)

    def test_dedupe_keeps_only_cheapest_across_different_sellers_and_prices(self):
        """회귀: 같은 시리즈+지면이 가격/판매처만 다르게 여러 행으로 쪼개져 보이던 버그.
        "시리즈 추천"은 SKU 단위가 아니라 시리즈 단위여야 하므로 최저가 1개만 남아야 한다."""
        rows = [
            {"brand": "나이키", "series_name": "머큐리얼 베이퍼", "surface": "TF", "sale_price": 149000, "seller": "크레이지11"},
            {"brand": "나이키", "series_name": "머큐리얼 베이퍼", "surface": "TF", "sale_price": 109000, "seller": "크레이지11"},
            {"brand": "나이키", "series_name": "머큐리얼 베이퍼", "surface": "TF", "sale_price": 139000, "seller": "사커붐"},
        ]

        deduped = dedupe_extracted_series(rows)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["sale_price"], 109000)

    def test_extract_series_name_drops_generation_number(self):
        self.assertEqual(extract_series_name("나이키 줌 머큐리얼 베이퍼 16 프로 TF"), "머큐리얼 베이퍼")
        self.assertEqual(extract_series_name("나이키 줌 머큐리얼 수퍼플라이 10 아카데미"), "머큐리얼 수퍼플라이")

    def test_recommendation_reason_includes_curated_series_description(self):
        reason = build_recommendation_reason(
            {"brand": "나이키", "series_name": "머큐리얼 베이퍼", "surface": "TF", "sale_price": 109000},
            "나이키 10만원대 TF 축구화 추천",
        )
        self.assertIn(SERIES_DESCRIPTIONS["머큐리얼 베이퍼"], reason)

    def test_unfiltered_and_diagnostic_formatters_keep_debug_views(self):
        raw = format_unfiltered_tavily_results(
            [
                {
                    "title": "나이키 머큐리얼 베이퍼",
                    "url": "https://soccerboom.co.kr/item",
                    "content": "시리즈 소개",
                }
            ]
        )
        diagnostics = format_tavily_price_diagnostics(
            "나이키 10만원대 FG 축구화 추천",
            [
                {
                    "title": "나이키 팬텀 FG",
                    "url": "https://redsoccer.co.kr/item",
                    "content": "판매가 : 150,000원",
                },
                {
                    "title": "나이키 머큐리얼 AG",
                    "url": "https://soccerboom.co.kr/item",
                    "content": "판매가 : 250,000원",
                },
            ],
        )

        self.assertIn("가격 필터를 적용하지 않은 Tavily 원본 결과", raw)
        self.assertIn("RAW: 아무 필터도 적용하지 않은 Tavily 원본", diagnostics)
        self.assertIn("PRICE_FILTERED: 요청 가격대 통과 결과", diagnostics)
        filtered_section = diagnostics.split("PRICE_FILTERED: 요청 가격대 통과 결과", 1)[1]
        self.assertIn("나이키 팬텀 FG", filtered_section)
        self.assertNotIn("나이키 머큐리얼 AG", filtered_section)

    def test_series_filter_rejects_sibling_series_when_series_requested(self):
        items = [
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800)",
                "brand": "나이키",
                "sale_price": 100000,
                "source_url": "https://redsoccer.co.kr/phantom",
                "search_score": 0.8,
            }
        ]

        filtered = filter_normalized_products(items, "나이키 머큐리얼 10만원대 FG 축구화 추천")

        self.assertEqual(filtered, [])

    def test_series_filter_allows_item_when_no_series_requested(self):
        items = [
            {
                "raw_name": "나이키 팬텀 6 로우 아카데미 FG/MG(HQ2032-800)",
                "brand": "나이키",
                "sale_price": 100000,
                "source_url": "https://redsoccer.co.kr/phantom",
                "search_score": 0.8,
            }
        ]

        filtered = filter_normalized_products(items, "나이키 10만원대 FG 축구화 추천")

        self.assertEqual(len(filtered), 1)

    def test_series_filter_allows_matching_series_regardless_of_lineup(self):
        items = [
            {
                "raw_name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
                "brand": "나이키",
                "sale_price": 109000,
                "source_url": "https://crazy11.co.kr/goods/1",
                "search_score": 0.8,
            }
        ]

        filtered = filter_normalized_products(items, "나이키 머큐리얼 10만원대 TF 축구화 추천")

        self.assertEqual(len(filtered), 1)

    def test_raw_cache_search_keyword_extracts_series_from_query(self):
        self.assertEqual(
            _raw_cache_search_keyword("나이키 10만원대 TF 머큐리얼 축구화 추천"),
            "머큐리얼",
        )
        self.assertIsNone(_raw_cache_search_keyword("나이키 10만원대 축구화 추천"))

    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_raw_cache_search_items_maps_cache_items_to_internal_schema(self, mock_load_cache):
        mock_load_cache.return_value = [
            {
                "seller": "crazy11",
                "product_name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
                "product_price": 109000,
                "product_url": "https://crazy11.co.kr/goods/1",
            }
        ]

        items = _raw_cache_search_items("나이키 10만원대 TF 머큐리얼 축구화 추천")

        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["raw_name"],
            "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
        )
        self.assertEqual(items[0]["sale_price"], 109000)
        self.assertEqual(items[0]["source_url"], "https://crazy11.co.kr/goods/1")
        self.assertEqual(items[0]["seller"], "crazy11")

        mock_load_cache.assert_called_once()
        called_keyword, called_min, called_max = mock_load_cache.call_args[0]
        self.assertEqual(called_keyword, "머큐리얼")
        self.assertEqual((called_min, called_max), (100000, 199999))

    def test_raw_cache_search_keywords_falls_back_to_brand_curated_series(self):
        # 회귀: 시리즈를 안 골라도(브랜드만 있으면) 그 브랜드의 큐레이션 시리즈 전체를 캐시에서
        # 조회해야 한다 — 안 그러면 캐시에 데이터가 있어도 매번 라이브 Tavily로 빠져 결과가
        # 호출마다 들쭉날쭉해졌다(실사용 재현: "나이키 축구화 10만원대 추천해줘" -> "TF").
        keywords = _raw_cache_search_keywords("나이키 10만원대 TF 축구화 추천")

        self.assertIn("머큐리얼 베이퍼", keywords)
        self.assertIn("팬텀", keywords)
        self.assertNotIn("프레데터", keywords)  # 아디다스 시리즈는 안 섞여야 함

    def test_raw_cache_search_keywords_returns_empty_without_brand_or_series(self):
        self.assertEqual(_raw_cache_search_keywords("10만원대 TF 축구화 추천"), [])

    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_raw_cache_search_items_merges_hits_across_brand_curated_series(self, mock_load_cache):
        def fake_load_cache(keyword, min_price, max_price):
            if keyword == "머큐리얼 베이퍼":
                return [
                    {
                        "seller": "crazy11",
                        "product_name": "나이키 머큐리얼 베이퍼 16 TF",
                        "product_price": 109000,
                        "product_url": "https://crazy11.co.kr/goods/1",
                    }
                ]
            if keyword == "팬텀":
                return [
                    {
                        "seller": "soccerboom",
                        "product_name": "나이키 팬텀 GX TF",
                        "product_price": 119000,
                        "product_url": "https://soccerboom.co.kr/goods/2",
                    }
                ]
            return None

        mock_load_cache.side_effect = fake_load_cache

        items = _raw_cache_search_items("나이키 10만원대 TF 축구화 추천")

        self.assertEqual({item["raw_name"] for item in items}, {"나이키 머큐리얼 베이퍼 16 TF", "나이키 팬텀 GX TF"})
        self.assertGreater(mock_load_cache.call_count, 1)

    @patch("Agent.product_search_agent.run_parallel_tavily_product_search")
    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_pipeline_uses_cache_only_and_skips_tavily_when_cache_hits(
        self, mock_load_cache, mock_tavily
    ):
        # 회귀: 캐시에 매칭 상품이 있어도 매 턴 라이브 Tavily 검색을 먼저 돌리고 캐시는 덧붙이기만
        # 해서, 실제로는 같은 조건이어도 그날 Tavily 응답 편차에 그대로 노출돼 "됐다가 안됐다가"
        # 하는 문제가 있었다. 캐시가 있으면 Tavily를 아예 호출하지 않아야 한다(seller_search와 동일 순서).
        mock_load_cache.return_value = [
            {
                "seller": "crazy11",
                "product_name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
                "product_price": 109000,
                "product_url": "https://crazy11.co.kr/goods/1",
            }
        ]

        result = asyncio.run(
            run_product_search_pipeline("나이키 10만원대 TF 머큐리얼 축구화 추천")
        )

        mock_tavily.assert_not_called()
        self.assertEqual(len(result["deduped_series"]), 1)
        self.assertEqual(result["deduped_series"][0]["sale_price"], 109000)
        self.assertEqual(result["source"], "raw_cache")
        self.assertEqual(result["search_status"], "ok")

    @patch("Agent.product_search_agent.run_parallel_tavily_product_search")
    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_pipeline_falls_back_to_tavily_when_cache_misses(self, mock_load_cache, mock_tavily):
        mock_load_cache.return_value = None
        mock_tavily.return_value = {}

        result = asyncio.run(
            run_product_search_pipeline("나이키 10만원대 TF 머큐리얼 축구화 추천")
        )

        mock_tavily.assert_called_once()
        self.assertEqual(result["deduped_series"], [])
        self.assertEqual(result["source"], "web_search")
        self.assertEqual(result["search_status"], "no_results")

    def test_unverified_or_malformed_price_is_rejected_without_budget(self):
        items = [
            {
                "raw_name": "나이키 팬텀 GX TF 풋살화",
                "brand": "나이키",
                "sale_price": None,
                "consumer_price": None,
                "source_url": "https://soccerboom.co.kr/phantom-1",
            },
            {
                "raw_name": "나이키 팬텀 GX TF 풋살화",
                "brand": "나이키",
                "sale_price": "가격 문의",
                "consumer_price": "미정",
                "source_url": "https://soccerboom.co.kr/phantom-2",
            },
        ]

        accepted, _, summary = collect_product_filter_diagnostics(
            items, "나이키 TF 축구화 추천"
        )

        self.assertEqual(accepted, [])
        self.assertEqual(summary.get("unverified_price"), 2)

    def test_raw_or_direct_candidate_from_unsupported_seller_is_rejected(self):
        items = [
            {
                "raw_name": "나이키 팬텀 GX TF 풋살화",
                "brand": "나이키",
                "sale_price": 109000,
                "source_url": "https://unsupported.example/phantom",
            }
        ]

        accepted, _, summary = collect_product_filter_diagnostics(
            items, "나이키 10만원대 TF 축구화 추천"
        )

        self.assertEqual(accepted, [])
        self.assertEqual(summary.get("unsupported_seller"), 1)

    def test_null_and_incomplete_product_items_are_rejected_without_crashing(self):
        items = [
            None,
            "not-a-product",
            {},
            {
                "raw_name": "나이키 팬텀 GX TF 풋살화",
                "sale_price": 109000,
                "source_url": "",
            },
        ]

        accepted, rejected, summary = collect_product_filter_diagnostics(
            items, "나이키 10만원대 TF 축구화 추천"
        )

        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 4)
        self.assertEqual(summary.get("invalid_item"), 2)
        self.assertEqual(summary.get("not_boot_or_missing_series"), 1)
        self.assertEqual(summary.get("missing_url"), 1)

    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_raw_cache_ignores_null_and_incomplete_rows(self, mock_load_cache):
        mock_load_cache.return_value = [None, "invalid", {}, {"product_name": None}]

        items = _raw_cache_search_items("나이키 머큐리얼 10만원대 TF 축구화 추천")

        self.assertEqual(items, [])

    def test_specific_exclusion_does_not_remove_sibling_series(self):
        items = [
            {
                "raw_name": "나이키 머큐리얼 베이퍼 16 TF 풋살화",
                "brand": "나이키",
                "sale_price": 109000,
                "source_url": "https://crazy11.co.kr/vapor",
            },
            {
                "raw_name": "나이키 머큐리얼 수퍼플라이 10 TF 풋살화",
                "brand": "나이키",
                "sale_price": 119000,
                "source_url": "https://crazy11.co.kr/superfly",
            },
        ]

        accepted, _, summary = collect_product_filter_diagnostics(
            items,
            "나이키 10만원대 TF exclude: 머큐리얼 베이퍼 축구화 추천",
        )

        self.assertEqual([item["series_name"] for item in accepted], ["머큐리얼 수퍼플라이"])
        self.assertEqual(summary.get("excluded_series"), 1)

    @patch("Agent.product_search_agent.run_parallel_tavily_product_search")
    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_external_search_exception_is_distinct_from_no_results_and_creates_no_products(
        self, mock_load_cache, mock_tavily
    ):
        mock_load_cache.return_value = None
        mock_tavily.side_effect = RuntimeError("search unavailable")

        result = asyncio.run(
            run_product_search_pipeline("나이키 머큐리얼 10만원대 TF 축구화 추천")
        )

        self.assertEqual(result["search_status"], "error")
        self.assertEqual(result["source"], "web_search")
        self.assertEqual(result["deduped_series"], [])
        self.assertIn("외부 검색 서비스를 사용할 수 없어", result["answer"])
        self.assertIn("검증되지 않은 상품이나 가격은 대신 생성하지 않았습니다", result["answer"])
        self.assertTrue(is_no_result_answer(result["answer"]))
        self.assertEqual(parse_product_markdown_table(result["answer"]), [])

    @patch("Agent.product_search_agent.run_parallel_tavily_product_search")
    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_all_seller_failures_are_reported_as_search_error(
        self, mock_load_cache, mock_tavily
    ):
        mock_load_cache.return_value = None
        mock_tavily.return_value = {
            "crazy11": {
                "seller": "크레이지11",
                "domain": "crazy11.co.kr",
                "ok": False,
                "results": [],
                "error": "timeout",
            },
            "soccerboom": {
                "seller": "사커붐",
                "domain": "soccerboom.co.kr",
                "ok": False,
                "results": [],
                "error": "timeout",
            },
        }

        result = asyncio.run(
            run_product_search_pipeline("나이키 머큐리얼 10만원대 TF 축구화 추천")
        )

        self.assertEqual(result["search_status"], "error")
        self.assertEqual(result["failed_sellers"], ["크레이지11", "사커붐"])
        self.assertEqual(result["deduped_series"], [])

    @patch("Agent.product_search_agent.run_parallel_tavily_product_search")
    @patch("Agent.product_search_agent.load_raw_items_cache")
    def test_successful_empty_search_is_reported_as_no_results(
        self, mock_load_cache, mock_tavily
    ):
        mock_load_cache.return_value = None
        mock_tavily.return_value = {
            "crazy11": {
                "seller": "크레이지11",
                "domain": "crazy11.co.kr",
                "ok": True,
                "results": [],
                "error": None,
            }
        }

        result = asyncio.run(
            run_product_search_pipeline("나이키 머큐리얼 10만원대 TF 축구화 추천")
        )

        self.assertEqual(result["search_status"], "no_results")
        self.assertEqual(result["deduped_series"], [])
        self.assertIn("요청 조건에 맞는 실제 판매 상품을 찾지 못했습니다", result["answer"])
        self.assertNotIn("외부 검색 서비스를 사용할 수 없어", result["answer"])

    def test_pipeline_result_merges_extra_cache_items_through_existing_filters(self):
        empty_parallel_result = {
            "soccerboom": {
                "seller": "사커붐",
                "domain": "soccerboom.co.kr",
                "ok": True,
                "results": [],
            }
        }
        cache_items = [
            {
                "input_index": None,
                "seller": "crazy11",
                "seller_key": "crazy11",
                "source_url": "https://crazy11.co.kr/goods/1",
                "source_title": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
                "source_rank": None,
                "search_score": 0.9,
                "local_index": 1,
                "raw_name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
                "brand": None,
                "consumer_price": None,
                "sale_price": 109000,
                "price_source": "raw_items_cache",
                "evidence_text": "나이키 줌 머큐리얼 베이퍼 16 프로 TF (FQ8687-300) 풋살화 #",
            }
        ]

        result = build_product_search_pipeline_result(
            "나이키 머큐리얼 10만원대 TF 축구화 추천",
            empty_parallel_result,
            extra_items=cache_items,
        )

        self.assertEqual(len(result["deduped_series"]), 1)
        self.assertEqual(result["deduped_series"][0]["sale_price"], 109000)
        self.assertIn("crazy11.co.kr", result["deduped_series"][0]["product_url"])

    def test_pipeline_result_still_rejects_cache_items_of_other_brands(self):
        empty_parallel_result = {
            "soccerboom": {
                "seller": "사커붐",
                "domain": "soccerboom.co.kr",
                "ok": True,
                "results": [],
            }
        }
        cache_items = [
            {
                "input_index": None,
                "seller": "crazy11",
                "seller_key": "crazy11",
                "source_url": "https://crazy11.co.kr/goods/2",
                "source_title": "아디다스 프레데터 엘리트 FG",
                "source_rank": None,
                "search_score": 0.9,
                "local_index": 1,
                "raw_name": "아디다스 프레데터 엘리트 FG",
                "brand": None,
                "consumer_price": None,
                "sale_price": 109000,
                "price_source": "raw_items_cache",
                "evidence_text": "아디다스 프레데터 엘리트 FG",
            }
        ]

        result = build_product_search_pipeline_result(
            "나이키 머큐리얼 10만원대 TF 축구화 추천",
            empty_parallel_result,
            extra_items=cache_items,
        )

        self.assertEqual(result["deduped_series"], [])
        self.assertEqual(result["rejection_summary"].get("brand_mismatch"), 1)

    def test_pipeline_result_infers_brand_from_series_for_unlabeled_cache_items(self):
        # 회귀: redsoccer/cafostore류 실제 캐시 상품은 스크랩된 제목에 "나이키"가 없는 경우가
        # 많다(예: "줌 머큐리얼 베이퍼 16 프로 TF..."). brand=None인 캐시 상품이 시리즈명(머큐리얼)
        # 만으로 나이키임을 추론하지 못하면 brand_mismatch로 잘못 거부된다.
        empty_parallel_result = {
            "redsoccer": {
                "seller": "레드사커",
                "domain": "redsoccer.co.kr",
                "ok": True,
                "results": [],
            }
        }
        cache_items = [
            {
                "input_index": None,
                "seller": "redsoccer",
                "seller_key": "redsoccer",
                "source_url": "https://redsoccer.co.kr/goods/1",
                "source_title": "줌 머큐리얼 베이퍼 16 프로 TF 풋살화(FQ8687-002)(FQ8687002) 230~255",
                "source_rank": None,
                "search_score": 0.9,
                "local_index": 1,
                "raw_name": "줌 머큐리얼 베이퍼 16 프로 TF 풋살화(FQ8687-002)(FQ8687002) 230~255",
                "brand": None,
                "consumer_price": None,
                "sale_price": 109500,
                "price_source": "raw_items_cache",
                "evidence_text": "줌 머큐리얼 베이퍼 16 프로 TF 풋살화(FQ8687-002)(FQ8687002) 230~255",
            }
        ]

        result = build_product_search_pipeline_result(
            "나이키 머큐리얼 10만원대 TF 축구화 추천",
            empty_parallel_result,
            extra_items=cache_items,
        )

        self.assertEqual(len(result["deduped_series"]), 1)
        self.assertEqual(result["deduped_series"][0]["brand"], "나이키")

    def test_series_brand_covers_every_series_pattern(self):
        series_names = {name for name, _ in SERIES_PATTERNS}
        self.assertEqual(set(SERIES_BRAND), series_names)
        for brand in SERIES_BRAND.values():
            self.assertIn(brand, BRAND_RULES)


if __name__ == "__main__":
    unittest.main()
