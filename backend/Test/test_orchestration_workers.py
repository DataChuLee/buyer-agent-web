import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.orchestration.workers as workers
from Agent.product_analysis_agent import ProductAnalysisResult
from Agent.product_search_agent import (
    build_product_search_fallback_answer,
    format_product_search_results,
    is_no_result_answer,
)
from State.AgentState_personalization import BuyerAgentStateV2


def _noop(_state):
    return {}


def _build_worker_graph(node_name: str, node_fn):
    """review가 필요한 워커는 interrupt() 로 멈추므로, 실제 LangGraph 실행 컨텍스트
    (체크포인터 + Command(resume=...) 재개) 안에서만 온전히 테스트할 수 있다."""
    builder = StateGraph(BuyerAgentStateV2)
    builder.add_node(node_name, node_fn)
    builder.add_node("supervisor_node", _noop)
    builder.add_node("purchase_prepare_node", _noop)
    builder.add_edge(START, node_name)
    builder.add_edge("supervisor_node", END)
    builder.add_edge("purchase_prepare_node", END)
    return builder.compile(checkpointer=MemorySaver())


class ProductSearchWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_review_then_selects_by_ordinal(self):
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return "1. 나이키 머큐리얼\n2. 아디다스 프레데터"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(
                workers,
                "_parse_products",
                AsyncMock(return_value=[{"name": "나이키 머큐리얼"}, {"name": "아디다스 프레데터"}]),
            ),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            config = {"configurable": {"thread_id": "ps-1"}}
            first = await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {"budget": "10만원대"}, "past_steps": []},
                config=config,
            )
            self.assertIn("__interrupt__", first)
            self.assertEqual(first["__interrupt__"][0].value["type"], "ps_review")

            second = await graph.ainvoke(Command(resume="1"), config=config)
            self.assertEqual(second["selected_series"], "나이키 머큐리얼")
            self.assertEqual(second["past_steps"], ["product_search"])
            # 회귀: select 분기가 messages를 안 남기면, 이후 아무 단계도 이어지지 않는 경우
            # (예: PS 단독 요청) 최종 응답이 완전히 비어 FastAPI가 500을 반환하던 버그가 있었다.
            self.assertTrue(second["messages"])
            self.assertTrue(str(second["messages"][-1].content).strip())

    async def test_no_candidates_returns_done_without_interrupt(self):
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return "요청 조건에 맞는 후보를 찾지 못했습니다."

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(workers, "_parse_products", AsyncMock(return_value=[])),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            result = await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {}, "past_steps": []},
                config={"configurable": {"thread_id": "ps-2"}},
            )
            self.assertNotIn("__interrupt__", result)
            self.assertEqual(result["status"], "done")

    async def test_multi_candidate_reference_keeps_brand_when_message_narrows(self):
        """회귀: "저 중에서"류 표현이 있어도 이번 메시지가 budget/surface로 조건을 좁히면
        (예: "저 중에서 10만원대이고 공격수에게 적합한 시리즈는 뭐야") 시리즈명도 없는 채로
        brand까지 지워버리면 캐시를 못 타고 매번 라이브 Tavily 검색이라 결과가 들쭉날쭉했다."""
        captured_queries: list[str] = []

        async def fake_product_search_agent(query, user_profile=None, config=None):
            captured_queries.append(query)
            return "1. 나이키 머큐리얼 베이퍼"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(workers, "_parse_products", AsyncMock(return_value=[])),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="저 중에서 10만원대이고 공격수에게 적합한 시리즈는 뭐야")],
                    "user_profile": {},
                    "user_conditions": {"brand": "나이키", "budget": "10만원대", "surface": "TF"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "ps-narrow"}},
            )

        self.assertIn("나이키", captured_queries[0])

    async def test_multi_candidate_reference_drops_brand_without_narrowing(self):
        """기존 동작 유지: "저 중에서" 뒤에 별다른 좁히는 조건이 없으면(예: "다른 거 없어?")
        여전히 brand를 지워 더 넓은 후보 풀에서 재검색한다."""
        captured_queries: list[str] = []

        async def fake_product_search_agent(query, user_profile=None, config=None):
            captured_queries.append(query)
            return "1. 아디다스 프레데터"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(workers, "_parse_products", AsyncMock(return_value=[])),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="저 중에서 다른 거 없어?")],
                    "user_profile": {},
                    "user_conditions": {"brand": "나이키", "budget": "10만원대", "surface": "TF"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "ps-widen"}},
            )

        self.assertNotIn("나이키", captured_queries[0])

    async def test_select_with_embedded_followup_request_queues_next_capability(self):
        """회귀: "머큐리얼 수퍼플라이로 할게 이걸 판매하는 곳은 어디야"처럼 선택과 새 요청이 한
        메시지에 섞여 있으면, 선택 확정과 함께 그 새 요청(seller_search)이 requested_capabilities에
        큐잉되어야 한다(기존엔 select 분기가 이걸 감지하지 않아 그냥 사라졌음)."""
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return "1. 나이키 머큐리얼 수퍼플라이\n2. 아디다스 프레데터"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(
                workers, "_parse_products",
                AsyncMock(return_value=[{"name": "나이키 머큐리얼 수퍼플라이"}, {"name": "아디다스 프레데터"}]),
            ),
            patch.object(
                workers, "_resolve_resume",
                AsyncMock(return_value=workers.PendingResolution(
                    action="select", selected_indices=[0], followup_capabilities=["seller_search"],
                )),
            ),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            config = {"configurable": {"thread_id": "ps-followup"}}
            await graph.ainvoke(
                {
                    "messages": [], "user_profile": {}, "user_conditions": {},
                    "requested_capabilities": ["product_search"], "past_steps": [],
                },
                config=config,
            )
            second = await graph.ainvoke(
                Command(resume="머큐리얼 수퍼플라이로 할게 이걸 판매하는 곳은 어디야"), config=config
            )

            self.assertEqual(second["requested_capabilities"], ["product_search", "seller_search"])

    async def test_ungrounded_question_answer_is_replaced_with_fallback(self):
        """회귀: 카드에 없는 정보(판매처 등)를 묻는 질문에 분류기가 지어낸 답(grounded=False)을
        그대로 내보내지 않고, 정해진 안내 문구로 대체해야 한다(할루시네이션 방지)."""
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return "1. 나이키 머큐리얼 수퍼플라이\n2. 아디다스 프레데터"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(
                workers, "_parse_products",
                AsyncMock(return_value=[{"name": "나이키 머큐리얼 수퍼플라이"}, {"name": "아디다스 프레데터"}]),
            ),
            patch.object(
                workers, "_resolve_resume",
                AsyncMock(return_value=workers.PendingResolution(
                    action="question", message="머큐리얼 수퍼플라이를 판매하는 곳은 '머큐리얼 수퍼플라이'입니다.",
                    grounded=False,
                )),
            ),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            config = {"configurable": {"thread_id": "ps-ungrounded"}}
            await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {}, "past_steps": []}, config=config
            )
            second = await graph.ainvoke(Command(resume="이걸 판매하는 곳은 어디야"), config=config)

            self.assertEqual(second["__interrupt__"][0].value["answer"], workers._UNGROUNDED_QUESTION_FALLBACK)

    async def test_reset_clears_state_and_forwards_message_to_supervisor(self):
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return "1. 나이키 머큐리얼"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(workers, "_parse_products", AsyncMock(return_value=[{"name": "나이키 머큐리얼"}])),
            patch.object(
                workers, "_resolve_resume", AsyncMock(return_value=workers.PendingResolution(action="reset"))
            ),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            config = {"configurable": {"thread_id": "ps-3"}}
            await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {}, "past_steps": []}, config=config
            )
            result = await graph.ainvoke(Command(resume="아 됐고 판매처 검색해줘"), config=config)

            self.assertEqual(result["past_steps"], [])
            self.assertIsNone(result["selected_series"])
            last_message = result["messages"][-1]
            self.assertEqual(last_message.content, "아 됐고 판매처 검색해줘")


class SellerSearchWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_query_includes_budget_and_surface_conditions(self):
        captured_queries = []

        async def fake_seller_search_agent(query, user_profile=None, config=None):
            captured_queries.append(query)
            return "seller answer"

        with (
            patch.object(workers, "seller_search_agent", fake_seller_search_agent),
            patch.object(workers, "_parse_sellers", AsyncMock(return_value=None)),
        ):
            graph = _build_worker_graph("seller_search_worker_node", workers.seller_search_worker_node)
            await graph.ainvoke(
                {
                    "messages": [],
                    "user_profile": {},
                    "user_conditions": {"product_name": "머큐리얼", "budget": "10만원대", "surface": "TF"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "ss-budget-1"}},
            )

        self.assertIn("10만원대", captured_queries[0])
        self.assertIn("TF", captured_queries[0])

    async def test_waits_for_review_then_selects_seller_payload(self):
        async def fake_seller_search_agent(query, user_profile=None, config=None):
            return "seller answer"

        with (
            patch.object(workers, "seller_search_agent", fake_seller_search_agent),
            patch.object(
                workers,
                "_parse_sellers",
                AsyncMock(return_value=[{"name": "크레이지11"}, {"name": "사커붐"}]),
            ),
        ):
            graph = _build_worker_graph("seller_search_worker_node", workers.seller_search_worker_node)
            config = {"configurable": {"thread_id": "ss-1"}}
            first = await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {}, "past_steps": []}, config=config
            )
            self.assertEqual(first["__interrupt__"][0].value["type"], "ss_review")

            second = await graph.ainvoke(Command(resume="1"), config=config)
            self.assertEqual(second["selected_seller"]["crawler_code"], "crazy11")
            self.assertEqual(second["past_steps"], ["seller_search"])
            self.assertTrue(second["messages"])
            self.assertTrue(str(second["messages"][-1].content).strip())

    async def test_skips_review_when_comparing_all_sellers(self):
        async def fake_seller_search_agent(query, user_profile=None, config=None):
            return "seller answer"

        with (
            patch.object(workers, "seller_search_agent", fake_seller_search_agent),
            patch.object(
                workers,
                "_parse_sellers",
                AsyncMock(return_value=[{"name": "크레이지11"}, {"name": "사커붐"}]),
            ),
        ):
            graph = _build_worker_graph("seller_search_worker_node", workers.seller_search_worker_node)
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="모든 판매처에서 비교해줘")],
                    "user_profile": {},
                    "user_conditions": {},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "ss-2"}},
            )
            self.assertNotIn("__interrupt__", result)
            self.assertEqual(result["status"], "done")

    async def test_condition_update_with_all_comparison_does_not_reinterrupt(self):
        """회귀(버그 A): 리뷰 카드 응답 중 "4개 모든 판매처에서 비교해줘"가 condition_update로
        분류돼도(_RESOLUTION_SYSTEM few-shot이 그렇게 유도함) 무한히 같은 카드를 재표시하지 않고
        바로 확정되어야 한다."""
        async def fake_seller_search_agent(query, user_profile=None, config=None):
            return "seller answer"

        with (
            patch.object(workers, "seller_search_agent", fake_seller_search_agent),
            patch.object(
                workers,
                "_parse_sellers",
                AsyncMock(return_value=[{"name": "크레이지11"}, {"name": "사커붐"}]),
            ),
            patch.object(
                workers, "_resolve_resume",
                AsyncMock(return_value=workers.PendingResolution(action="condition_update")),
            ),
            patch.object(
                workers, "_apply_condition_update",
                AsyncMock(return_value={"product_name": "머큐리얼 베이퍼"}),
            ),
        ):
            graph = _build_worker_graph("seller_search_worker_node", workers.seller_search_worker_node)
            config = {"configurable": {"thread_id": "ss-condupdate-all"}}
            first = await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {}, "past_steps": []}, config=config
            )
            self.assertEqual(first["__interrupt__"][0].value["type"], "ss_review")

            second = await graph.ainvoke(Command(resume="4개 모든 판매처에서 비교해줘"), config=config)

            self.assertNotIn("__interrupt__", second)
            self.assertEqual(second["status"], "done")
            self.assertEqual(second["past_steps"], ["seller_search"])

    async def test_selecting_seller_appends_product_analysis_to_requested_capabilities(self):
        """회귀(버그 B): 판매처 선택이 끝나면 supervisor가 이어서 product_analysis를 판단할 수
        있도록 requested_capabilities에 product_analysis가 추가되어야 한다(기존 값 유지, 중복 없이)."""
        async def fake_seller_search_agent(query, user_profile=None, config=None):
            return "seller answer"

        with (
            patch.object(workers, "seller_search_agent", fake_seller_search_agent),
            patch.object(
                workers,
                "_parse_sellers",
                AsyncMock(return_value=[{"name": "크레이지11"}, {"name": "사커붐"}]),
            ),
        ):
            graph = _build_worker_graph("seller_search_worker_node", workers.seller_search_worker_node)
            config = {"configurable": {"thread_id": "ss-append-pa"}}
            await graph.ainvoke(
                {
                    "messages": [], "user_profile": {}, "user_conditions": {},
                    "requested_capabilities": ["seller_search"], "past_steps": [],
                },
                config=config,
            )
            second = await graph.ainvoke(Command(resume="1"), config=config)

            self.assertEqual(second["requested_capabilities"], ["seller_search", "product_analysis"])


class ProductAnalysisWorkerTest(unittest.IsolatedAsyncioTestCase):
    async def test_select_routes_to_purchase_prepare(self):
        doc_card = {"name": "머큐리얼 상품", "seller": "사커붐", "url": "https://example.test/item"}

        async def fake_product_analysis_agent(query, **kwargs):
            return ProductAnalysisResult(answer="analysis answer", docs=["fake-doc"])

        with (
            patch.object(workers, "product_analysis_agent", fake_product_analysis_agent),
            patch.object(workers, "build_analysis_cards_from_docs", return_value=[doc_card]),
        ):
            graph = _build_worker_graph("product_analysis_worker_node", workers.product_analysis_worker_node)
            config = {"configurable": {"thread_id": "pa-1"}}
            first = await graph.ainvoke(
                {"messages": [], "user_profile": {}, "user_conditions": {"budget": "10만원대"}, "past_steps": []},
                config=config,
            )
            self.assertEqual(first["__interrupt__"][0].value["type"], "pa_review")

            second = await graph.ainvoke(Command(resume="1"), config=config)
            self.assertEqual(second["selected_product"], doc_card)
            self.assertEqual(second["active_agent"], "purchase_prepare")
            self.assertEqual(second["status"], "waiting_input")

    async def test_reuses_real_rag_docs_for_cards(self):
        # build_analysis_cards_from_docs를 목킹하지 않고 실제 Document 메타데이터에서
        # 카드(특히 url)가 정확히 재사용되는지 확인한다.
        doc = Document(
            page_content="상품명: 머큐리얼 베이퍼\n판매자: 크레이지11",
            metadata={
                "seller": "크레이지11",
                "product_name": "머큐리얼 베이퍼",
                "product_price": 109000,
                "product_url": "https://example.test/reused",
            },
        )

        async def fake_product_analysis_agent(query, **kwargs):
            return ProductAnalysisResult(answer="analysis answer", docs=[doc])

        with patch.object(workers, "product_analysis_agent", fake_product_analysis_agent):
            graph = _build_worker_graph("product_analysis_worker_node", workers.product_analysis_worker_node)
            result = await graph.ainvoke(
                {
                    "messages": [],
                    "user_profile": {},
                    "user_conditions": {"seller": "crazy11", "product_name": "머큐리얼", "budget": "10만원대"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "pa-3"}},
            )
            payload = result["__interrupt__"][0].value
            self.assertEqual(payload["answer"], "analysis answer")
            self.assertEqual(payload["cards"][0]["url"], "https://example.test/reused")

    async def test_skips_review_when_comparing_all_sellers(self):
        async def fake_product_analysis_agent(query, **kwargs):
            return ProductAnalysisResult(answer="4곳 비교 결과", docs=["fake-doc"])

        with (
            patch.object(workers, "product_analysis_agent", fake_product_analysis_agent),
            patch.object(
                workers,
                "build_analysis_cards_from_docs",
                return_value=[
                    {"name": "나이키 머큐리얼 수퍼플라이 10 TF", "seller": "크레이지11"},
                    {"name": "나이키 머큐리얼 수퍼플라이 10 TF", "seller": "사커붐"},
                ],
            ),
        ):
            graph = _build_worker_graph("product_analysis_worker_node", workers.product_analysis_worker_node)
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="그럼 판매자 4곳 모두에서 비교해줘 저 제품을")],
                    "user_profile": {},
                    "user_conditions": {"product_name": "나이키 머큐리얼 수퍼플라이 10 TF"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "pa-2"}},
            )
            self.assertNotIn("__interrupt__", result)
            self.assertEqual(result["status"], "done")

    async def test_condition_update_preserves_seller_scope_when_update_omits_it(self):
        """회귀: 메인 그래프의 의도 추출 LLM이 판매처명을 엉뚱한 필드로 오분류하면
        user_conditions에 seller가 안 남는다. 이 상태에서 "사이즈 265 있어?"처럼 판매처와 무관한
        condition_update가 오면, _apply_condition_update가 seller를 못 채워도 이번 노드 진입 시점에
        _analysis_conditions()가 메시지에서 재추론해둔 seller(크레이지11)가 조용히 사라지면 안 된다."""
        calls = []

        async def fake_product_analysis_agent(query, **kwargs):
            calls.append(kwargs.get("conditions"))
            return ProductAnalysisResult(answer="분석 결과", docs=["fake-doc"])

        with (
            patch.object(workers, "product_analysis_agent", fake_product_analysis_agent),
            patch.object(
                workers, "build_analysis_cards_from_docs",
                return_value=[{"name": "머큐리얼 베이퍼", "seller": "크레이지11"}],
            ),
            patch.object(
                workers, "_resolve_resume",
                AsyncMock(return_value=workers.PendingResolution(action="condition_update")),
            ),
            patch.object(workers, "_apply_condition_update", AsyncMock(return_value={"size": "265"})),
        ):
            graph = _build_worker_graph("product_analysis_worker_node", workers.product_analysis_worker_node)
            config = {"configurable": {"thread_id": "pa-seller-preserve"}}
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="크레이지11에서 머큐리얼 베이퍼 비교해줘")],
                    "user_profile": {}, "user_conditions": {}, "past_steps": [],
                },
                config=config,
            )
            await graph.ainvoke(Command(resume="사이즈 265 있어?"), config=config)

        self.assertEqual(calls[0]["seller"], "crazy11")
        self.assertEqual(calls[1]["seller"], "crazy11")

    async def test_all_comparison_request_ignores_previously_selected_seller(self):
        """회귀: SS에서 크레이지11을 선택한 뒤 "4곳 모두 비교해줘"라고 요청해도, 쿼리 텍스트에
        "크레이지11에서"가 다시 박혀 들어가 실제로는 크레이지11만 분석되던 버그."""
        calls = {}

        async def fake_product_analysis_agent(query, **kwargs):
            calls["query"] = query
            return ProductAnalysisResult(answer="4곳 비교 결과", docs=["fake-doc"])

        with (
            patch.object(workers, "product_analysis_agent", fake_product_analysis_agent),
            patch.object(
                workers,
                "build_analysis_cards_from_docs",
                return_value=[
                    {"name": "나이키 머큐리얼 베이퍼", "seller": "크레이지11"},
                    {"name": "나이키 머큐리얼 베이퍼", "seller": "사커붐"},
                ],
            ),
        ):
            graph = _build_worker_graph("product_analysis_worker_node", workers.product_analysis_worker_node)
            await graph.ainvoke(
                {
                    "messages": [HumanMessage(content="4곳 판매처 모두에서 비교해줘")],
                    "user_profile": {},
                    "user_conditions": {"product_name": "나이키 머큐리얼 베이퍼"},
                    "selected_seller": {"display_name": "크레이지11", "crawler_code": "crazy11"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "pa-all-comparison"}},
            )

        self.assertNotIn("크레이지11", calls["query"])


class SellerExclusionTest(unittest.TestCase):
    def test_extract_excluded_sellers_finds_named_seller(self):
        self.assertEqual(workers._extract_excluded_sellers("크레이지11 말고 나머지 판매처에서"), ["crazy11"])
        self.assertEqual(workers._extract_excluded_sellers("사커붐 빼고"), ["soccerboom"])
        self.assertEqual(workers._extract_excluded_sellers("그냥 다 보여줘"), [])

    def test_analysis_conditions_excludes_named_seller_on_fresh_entry(self):
        """회귀: PA 워커가 리뷰 interrupt 없이 새 턴으로 진입할 때도(직전 턴이 이미 status=done으로
        끝난 경우) "크레이지11 말고 나머지 판매처에서"의 "크레이지11"이 _latest_message_seller_crawlers에
        의해 포함 조건으로 오인되지 않고 여집합으로 처리되는지 확인."""
        state = {
            "user_conditions": {"seller": "crazy11", "product_name": "머큐리얼 베이퍼"},
            "messages": [HumanMessage(content="크레이지11 말고 나머지 판매처에서 비교해줘")],
        }
        conditions = workers._analysis_conditions(state)
        sellers = {s.strip() for s in conditions["seller"].split(",")}
        self.assertEqual(sellers, {"soccerboom", "redsoccer", "cafostore"})


class ApplyConditionUpdateSellerExclusionTest(unittest.IsolatedAsyncioTestCase):
    async def test_condition_update_sets_seller_to_complement_when_excluded(self):
        """회귀: "크레이지11 말고 나머지 판매처에서"는 seller 필드가 표현 못하는 '제외' 의미라
        기존에는 무시됐다 — 나머지 3개 판매처로 채워지는지 검증."""
        import Agent.LangGraph_buyeragent_with_personalization as buyer_graph

        class FakeExtractor:
            async def ainvoke(self, _messages):
                return buyer_graph.ExtractionResult(
                    intent="shopping",
                    requested_capabilities=[],
                    conditions=buyer_graph.ExtractedConditions(),
                )

        class FakeLlm:
            def with_structured_output(self, _schema):
                return FakeExtractor()

        with patch.object(buyer_graph, "llm", FakeLlm()):
            updated = await workers._apply_condition_update(
                {"user_conditions": {"seller": "crazy11", "product_name": "머큐리얼 베이퍼"}},
                "크레이지11 말고 나머지 판매처에서 비교해줘",
            )

        sellers = {s.strip() for s in updated["seller"].split(",")}
        self.assertEqual(sellers, {"soccerboom", "redsoccer", "cafostore"})


class ParseProductsNoResultGuardTest(unittest.IsolatedAsyncioTestCase):
    def test_is_no_result_answer_is_false_for_a_real_success_table(self):
        # 회귀: 성공 응답도 실패 응답과 같은 접두어("지원 판매처 4곳의 Tavily 검색 결과에서")로
        # 시작하므로, 짧은 공통 substring만 보면 성공 응답까지 "결과 없음"으로 오판된다.
        text = format_product_search_results(
            [{"series_name": "머큐리얼 베이퍼", "brand": "나이키", "surface": "FG", "sale_price": 125800, "seller": "크레이지11"}],
            "나이키 10만원대 FG 축구화 추천",
        )
        self.assertFalse(is_no_result_answer(text))

    async def test_parse_products_extracts_cards_from_a_real_success_table(self):
        text = format_product_search_results(
            [{"series_name": "머큐리얼 베이퍼", "brand": "나이키", "surface": "FG", "sale_price": 125800, "seller": "크레이지11"}],
            "나이키 10만원대 FG 축구화 추천",
        )
        cards = await workers._parse_products(text)
        self.assertTrue(cards)
        self.assertEqual(cards[0]["name"], "머큐리얼 베이퍼")

    async def test_parse_products_returns_empty_for_fallback_guidance_text(self):
        text = build_product_search_fallback_answer("나이키 10만원대 축구화 추천", {"price_mismatch": 3})
        self.assertEqual(await workers._parse_products(text), [])

    async def test_parse_products_returns_empty_for_no_candidates_message(self):
        text = format_product_search_results([], "나이키 10만원대 축구화 추천")
        self.assertEqual(await workers._parse_products(text), [])

    async def test_product_search_worker_does_not_create_cards_from_fallback_guidance(self):
        async def fake_product_search_agent(query, user_profile=None, config=None):
            return build_product_search_fallback_answer(query, {"brand_mismatch": 2})

        with patch.object(workers, "product_search_agent", fake_product_search_agent):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            result = await graph.ainvoke(
                {
                    "messages": [],
                    "user_profile": {},
                    "user_conditions": {"brand": "나이키", "budget": "10만원대", "product_name": "머큐리얼"},
                    "past_steps": [],
                },
                config={"configurable": {"thread_id": "ps-guard-1"}},
            )
            self.assertIsNone(result["products"])


class RunSearchTaskFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def test_falls_back_to_direct_call_when_task_resolves_to_none(self):
        # langgraph @task가 astream_events + interrupt() 재개 조합에서 이전에 스케줄된 task 기록에
        # RETURN 값이 없으면 None으로 resolve하는 내부 엣지케이스를 재현(langgraph/pregel/_runner.py
        # _acall_impl). _run_search가 이 경우 원본 함수(task_fn.func)로 직접 재실행해 우회해야 한다.
        # 재실행은 mute=True로 넘겨받아야 한다(스트리밍 중복 방지).
        async def _underlying(rejected, mute=False):
            return ["card"], "response", mute

        task_fn = AsyncMock(return_value=None)
        task_fn.func = _underlying

        cards, response, mute = await workers._run_search(task_fn, [])

        self.assertEqual(cards, ["card"])
        self.assertEqual(response, "response")
        self.assertTrue(mute)
        task_fn.assert_awaited_once_with([])

    async def test_uses_task_result_when_not_none(self):
        task_fn = AsyncMock(return_value=(["card"], "response"))
        task_fn.func = AsyncMock(side_effect=AssertionError("should not fall back"))

        cards, response = await workers._run_search(task_fn, [])

        self.assertEqual(cards, ["card"])


class SearchMuteConfigTest(unittest.IsolatedAsyncioTestCase):
    async def test_product_search_always_calls_agent_with_empty_callbacks(self):
        # 실사용 재현 버그: create_react_agent 내부 LLM이 스트리밍되면(astream_events가 "agent"
        # 노드를 허용) gpt-4o-mini가 (심지어 "완료" 한 마디만 답하라고 시켜도) 자기 출력을 반복
        # 생성하는 문제가 확인됐다. product_search_agent()가 이제 모델 텍스트 대신 도구
        # (ToolMessage) 원문을 쓰므로 모델의 스트리밍 자체가 필요 없어졌다 — 재시도 여부와 무관하게
        # 항상 config={"callbacks": []}로 호출해 astream_events에 아예 잡히지 않게 한다.
        captured_configs: list = []

        async def fake_product_search_agent(query, user_profile=None, config=None):
            captured_configs.append(config)
            return "1. 나이키 머큐리얼\n2. 아디다스 프레데터"

        with (
            patch.object(workers, "product_search_agent", fake_product_search_agent),
            patch.object(
                workers, "_parse_products",
                AsyncMock(return_value=[{"name": "나이키 머큐리얼"}, {"name": "아디다스 프레데터"}]),
            ),
        ):
            graph = _build_worker_graph("product_search_worker_node", workers.product_search_worker_node)
            await graph.ainvoke(
                {
                    "messages": [], "user_profile": {}, "user_conditions": {"brand": "나이키"},
                    "requested_capabilities": ["product_search"], "past_steps": [],
                },
                config={"configurable": {"thread_id": "ps-mute-1"}},
            )

        self.assertEqual(captured_configs, [{"callbacks": []}])


class ReferenceResolutionHelperTest(unittest.TestCase):
    def test_resolve_product_reference_by_ordinal(self):
        state = {
            "messages": [HumanMessage(content="첫 번째 제품 판매하는 곳 알려줘")],
            "last_products": [{"name": "나이키 머큐리얼 베이퍼"}, {"name": "아디다스 프레데터"}],
        }
        self.assertEqual(workers._resolve_product_reference(state)["name"], "나이키 머큐리얼 베이퍼")

    def test_normalize_product_cards_fills_blank_fields_and_link(self):
        cards = workers._normalize_product_cards(
            [{"name": "나이키 머큐리얼 베이퍼", "features": None, "recommendation": None, "price": None, "url": None}]
        )
        card = cards[0]
        self.assertEqual(card["features"], "")
        self.assertIn("search.naver.com", card["url"])

    def test_cards_summary_includes_size(self):
        # 회귀: 사이즈 질문("265 사이즈 있어?")을 판단하는 리뷰 응답 분류기가 카드에 실제로
        # 있는 사이즈 정보를 요약에서 보지 못해 항상 "근거 없음"으로 오판하던 버그.
        summary = workers._cards_summary(
            [{"name": "베이퍼", "seller": "크레이지11", "price": "109,000원", "size": "245, 265, 270"}]
        )
        self.assertIn("265", summary)


if __name__ == "__main__":
    unittest.main()
