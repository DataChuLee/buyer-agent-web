import os
import sys
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.LangGraph_buyeragent_with_personalization as buyer_graph


class ProductSearchFollowupRoutingTest(unittest.IsolatedAsyncioTestCase):
    def test_extracts_surface_from_short_followup(self):
        conditions = buyer_graph._extract_explicit_product_conditions("그럼 TF는?")

        self.assertEqual(conditions, {"surface": "TF"})

    def test_extracts_size_from_followup_question(self):
        # 회귀: product_analysis 리뷰 카드 응답 중 "사이즈 265 있어?" 같은 후속 질문이 조건으로
        # 안 잡혀서 실제 RAG 재검색 없이 LLM이 카드 텍스트를 눈으로 훑고 답하다 오답하던 문제.
        self.assertEqual(
            buyer_graph._extract_explicit_product_conditions("사이즈가 265인 제품은 없어?"),
            {"size": "265"},
        )
        self.assertEqual(
            buyer_graph._extract_explicit_product_conditions("265사이즈로 볼 수 있어?"),
            {"size": "265"},
        )

    def test_extracts_hg_surface_and_puma_future_spelling(self):
        # 회귀(실험 4): HG가 지면 목록에 없어 새 검색 요청에서 LLM이 잡은 surface까지 지워져 되묻던 문제,
        # "퓨처" 표기가 시리즈로 인식되지 않아 상품명이 지워져 분석 요청을 되묻던 문제.
        self.assertEqual(
            buyer_graph._extract_explicit_product_conditions("미즈노 20만원 이하 HG 축구화 보여줘")["surface"],
            "HG",
        )
        self.assertEqual(
            buyer_graph._extract_explicit_product_conditions("퓨처 7 얼티밋 가격이랑 사이즈 비교 분석해줘")["product_name"],
            "퓨쳐",
        )

    def test_extracts_brand_budget_and_surface_from_new_request(self):
        conditions = buyer_graph._extract_explicit_product_conditions(
            "아디다스 10만원대 FG 축구화를 추천해줘"
        )

        self.assertEqual(
            conditions,
            {"brand": "아디다스", "budget": "10만원대", "surface": "FG"},
        )

    async def test_fresh_brand_budget_request_drops_stale_surface(self):
        class FakeExtractor:
            async def ainvoke(self, _messages):
                return buyer_graph.ExtractionResult(
                    intent="shopping",
                    requested_capabilities=["product_search"],
                    conditions=buyer_graph.ExtractedConditions(),
                )

        class FakeLlm:
            def with_structured_output(self, _schema):
                return FakeExtractor()

        state = {
            "messages": [HumanMessage(content="나이키 10만원대 축구화를 추천해줘")],
            "intent": "product_search",
            "user_conditions": {"brand": "나이키", "budget": "10만원대", "surface": "FG"},
            "user_profile": {},
        }

        with patch.object(buyer_graph, "llm", FakeLlm()):
            result = await buyer_graph.extract_conditions_and_intent(state)

        self.assertEqual(result["intent"], "product_search")
        self.assertEqual(result["past_steps"], [])
        self.assertEqual(result["user_conditions"], {"brand": "나이키", "budget": "10만원대"})

    async def test_multi_capability_extraction_prioritizes_product_search_first(self):
        """intent 자체는 조건 수집 게이트(check_conditions)의 우선순위 선택일 뿐이고,
        실제 실행 순서는 supervisor_node가 매 턴 재판단한다(orchestration_plan 없음)."""
        class FakeExtractor:
            async def ainvoke(self, _messages):
                return buyer_graph.ExtractionResult(
                    intent="shopping",
                    requested_capabilities=["seller_search", "product_search"],
                    conditions=buyer_graph.ExtractedConditions(),
                )

        class FakeLlm:
            def with_structured_output(self, _schema):
                return FakeExtractor()

        state = {
            "messages": [HumanMessage(content="나이키 10만원대 축구화 추천해주고 어디서 파는지도 알려줘")],
            "intent": "",
            "user_conditions": {},
            "user_profile": {},
        }

        with patch.object(buyer_graph, "llm", FakeLlm()):
            result = await buyer_graph.extract_conditions_and_intent(state)

        self.assertEqual(result["intent"], "product_search")
        self.assertEqual(result["requested_capabilities"], ["seller_search", "product_search"])

    async def test_bug_b_regression_purchase_phrase_routes_to_product_search(self):
        """'구매하려고'가 섞여도 재도입된 키워드 재스캔이 seller_search로 끌어가지 않는지 검증.

        구식 plan_orchestration_steps는 원문을 다시 정규식으로 훑어 "구매"를 seller_search
        신호로 오인했다. 새 planner는 LLM이 넘긴 requested_capabilities만 순서대로 조립하므로,
        원문에 "구매"가 있어도 LLM이 product_search만 요청했다면 결과는 product_search여야 한다.
        """

        class FakeExtractor:
            async def ainvoke(self, _messages):
                return buyer_graph.ExtractionResult(
                    intent="shopping",
                    requested_capabilities=["product_search"],
                    conditions=buyer_graph.ExtractedConditions(position="공격수"),
                )

        class FakeLlm:
            def with_structured_output(self, _schema):
                return FakeExtractor()

        state = {
            "messages": [HumanMessage(content="나이키 축구화를 구매하려고 하는데 어떤 게 좋을까? 공격수이거든")],
            "intent": "",
            "user_conditions": {"product_name": "나이키 머큐리얼 베이퍼"},
            "user_profile": {},
        }

        with patch.object(buyer_graph, "llm", FakeLlm()):
            result = await buyer_graph.extract_conditions_and_intent(state)

        self.assertEqual(result["intent"], "product_search")

    def test_product_search_requires_brand_budget_and_surface(self):
        state = {
            "intent": "product_search",
            "user_conditions": {"brand": "나이키", "budget": "10만원대"},
            "search_result": [],
        }

        result = buyer_graph.check_conditions(state)

        self.assertEqual(result["status"], "waiting_input")
        self.assertEqual(result["missing_conditions"], ["surface"])

    def test_missing_surface_question_uses_descriptive_options(self):
        state = {
            "intent": "product_search",
            "user_conditions": {"brand": "나이키", "budget": "10만원대"},
            "missing_conditions": ["surface"],
        }

        result = buyer_graph.ask_missing_node(state)

        self.assertEqual(result["status"], "waiting_input")
        self.assertEqual(result["question_sequence"][0]["key"], "surface")
        self.assertIsInstance(result["question_sequence"][0]["options"][0], dict)
        self.assertIn("description", result["question_sequence"][0]["options"][0])

    def test_product_search_does_not_ask_series_even_for_curated_brand(self):
        # 시리즈는 더 이상 카드로 수집하지 않는다 — product_search가 조건(brand/budget/surface)
        # 만으로 직접 검색해 추천하는 게 이 워커의 역할이므로, 사용자에게 시리즈를 먼저 고르게
        # 하면 그 역할이 무의미해진다.
        state = {
            "intent": "product_search",
            "user_conditions": {"brand": "나이키", "budget": "10만원대", "surface": "FG"},
        }

        result = buyer_graph.check_conditions(state)

        self.assertEqual(result["status"], "responding")
        self.assertEqual(result["missing_conditions"], [])

    def test_product_search_skips_series_for_brand_without_curated_series(self):
        state = {
            "intent": "product_search",
            "user_conditions": {"brand": "뉴발란스", "budget": "10만원대", "surface": "FG"},
        }

        result = buyer_graph.check_conditions(state)

        self.assertEqual(result["status"], "responding")
        self.assertEqual(result["missing_conditions"], [])

    def test_product_search_skips_series_when_already_chosen(self):
        state = {
            "intent": "product_search",
            "user_conditions": {
                "brand": "나이키",
                "budget": "10만원대",
                "surface": "FG",
                "product_name": "머큐리얼 베이퍼",
            },
        }

        result = buyer_graph.check_conditions(state)

        self.assertEqual(result["status"], "responding")
        self.assertEqual(result["missing_conditions"], [])

    def test_merge_drops_hallucinated_product_name_not_a_known_series(self):
        # 회귀: LLM 조건 추출기가 "TF" 같은 단답을 surface로 못 잡고 product_name="TF"로
        # 잘못 채우면, check_conditions의 시리즈 재질문 분기(product_name 미설정 조건)가
        # 조용히 스킵돼 캐시 없이 라이브 Tavily 검색으로 빠지는 문제가 있었다.
        merged = buyer_graph._merge_product_conditions(
            {"brand": "나이키", "budget": "10만원대"},
            {"product_name": "TF"},
            {"surface": "TF"},
            "TF",
        )

        self.assertEqual(
            merged,
            {"brand": "나이키", "budget": "10만원대", "surface": "TF"},
        )

    def test_merge_keeps_product_name_when_recognized_series(self):
        merged = buyer_graph._merge_product_conditions(
            {"brand": "나이키", "budget": "10만원대", "surface": "FG"},
            {"product_name": "머큐리얼 베이퍼"},
            {},
            "머큐리얼 베이퍼로 할래",
        )

        self.assertEqual(merged.get("product_name"), "머큐리얼 베이퍼")

    def test_extracts_series_name_from_explicit_message(self):
        conditions = buyer_graph._extract_explicit_product_conditions(
            "나이키 머큐리얼 베이퍼 10만원대 추천해줘"
        )

        self.assertEqual(
            conditions,
            {"brand": "나이키", "budget": "10만원대", "product_name": "머큐리얼 베이퍼"},
        )

    async def test_product_guide_intent_from_llm_produces_empty_plan(self):
        class FakeExtractor:
            async def ainvoke(self, _messages):
                return buyer_graph.ExtractionResult(
                    intent="product_guide",
                    conditions=buyer_graph.ExtractedConditions(),
                )

        class FakeLlm:
            def with_structured_output(self, _schema):
                return FakeExtractor()

        state = {
            "messages": [HumanMessage(content="포지션별로는 어떤 스터드를 사용하는 게 좋아?")],
            "intent": "",
            "user_conditions": {},
            "user_profile": {},
        }

        with patch.object(buyer_graph, "llm", FakeLlm()):
            result = await buyer_graph.extract_conditions_and_intent(state)

        self.assertEqual(result["intent"], "product_guide")
        self.assertEqual(result["requested_capabilities"], [])


if __name__ == "__main__":
    unittest.main()
