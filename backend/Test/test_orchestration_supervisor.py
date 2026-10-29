import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import HumanMessage

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.orchestration.supervisor as supervisor
from Agent.orchestration.supervisor import SupervisorDecision, wants_all_comparison


class WantsAllComparisonTest(unittest.TestCase):
    def test_wants_all_comparison_detects_keyword(self):
        self.assertTrue(wants_all_comparison("모든 판매처에서 비교해줘"))
        self.assertFalse(wants_all_comparison("크레이지11에서 비교해줘"))


class SupervisorNodeRequestedCapabilityGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_overrides_llm_pick_outside_requested_capabilities(self):
        """회귀: 실제 배포 서버 테스트에서 product_search만 요청했는데도 LLM supervisor가
        seller_search를 먼저 고르는 오판이 관측됨 — 아직 처리 안 된 요청 capability가 남아있으면
        LLM이 뭘 고르든 그걸 우선하는 결정론적 안전장치가 동작하는지 검증."""
        fake_decision = SupervisorDecision(next="seller_search")
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="나이키 10만원대 FG 축구화 추천해줘")],
                    "requested_capabilities": ["product_search"],
                    "past_steps": [],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.goto, "product_search_worker_node")

    async def test_finishes_once_all_requested_capabilities_done_with_no_new_request(self):
        """회귀: PS 단독 요청에서 product_search를 마친 뒤에도 LLM supervisor가 요청하지 않은
        seller_search로 계속 진행하는 오판이 관측됨(카드 선택 "1"은 새 메시지로 반영되지 않으므로
        마지막 사용자 메시지는 여전히 원래 요청 그대로임) — 요청된 capability를 이미 다 실행했으면
        LLM이 뭘 고르든 FINISH로 강제되는지 검증."""
        fake_decision = SupervisorDecision(next="seller_search")
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="나이키 10만원대 FG 축구화 추천해줘")],
                    "requested_capabilities": ["product_search"],
                    "past_steps": ["product_search"],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.update["status"], "done")

    async def test_continues_to_remaining_request_even_when_llm_repeats_a_past_step(self):
        """회귀: SS->PA 요청에서 seller_search를 마친 뒤 LLM이 seller_search를 다시 고르는 경우
        (past_steps에 있으니 반복 방지 규칙에 걸려) FINISH로 잘못 끝나버리던 버그. "이미 실행한
        단계는 반복하지 않는다"보다 "아직 처리 안 된 명시적 요청을 끝까지 한다"가 우선해야 한다."""
        fake_decision = SupervisorDecision(next="seller_search")
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="나이키 머큐리얼 베이퍼 어디서 파는지 알려주고 상세 분석도 해줘")],
                    "requested_capabilities": ["seller_search", "product_analysis"],
                    "past_steps": ["seller_search"],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.goto, "product_analysis_worker_node")

    async def test_remaining_order_overrides_out_of_order_next_pick(self):
        """회귀(버그 B): product_search와 seller_search가 함께 남아있을 때 LLM이 순서를 건너뛰고
        seller_search를 콕 집어도(next), replan 결과인 remaining_order가 product_search를 먼저
        두면 그 순서를 따라야 한다(원본 Plan-and-Execute의 replan_step처럼 매번 전체 순서를
        다시 판단 — execute 단계는 그 첫 번째만 기계적으로 집행)."""
        fake_decision = SupervisorDecision(
            next="seller_search", remaining_order=["product_search", "seller_search"]
        )
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="나이키 머큐리얼 베이퍼 10만원대 추천해주고 판매하는 곳도 알려줘")],
                    "requested_capabilities": ["product_search", "seller_search"],
                    "past_steps": [],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.goto, "product_search_worker_node")

    async def test_product_search_runs_first_when_no_product_is_known(self):
        """회귀(실험 5): '추천하고 그중 하나 분석해줘'에서 LLM이 remaining_order에 분석을 먼저 두면
        상품도 없이 분석부터 실행됐다. 상품 맥락이 없으면 product_search가 항상 먼저여야 한다."""
        fake_decision = SupervisorDecision(
            next="product_analysis", remaining_order=["product_analysis", "product_search"]
        )
        state = {
            "messages": [HumanMessage(content="아디다스 10만원대 FG 골라주고 그중에 하나 자세히 분석해줘")],
            "requested_capabilities": ["product_search", "product_analysis"],
            "past_steps": [],
            "user_conditions": {},
        }
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(state)
            self.assertEqual(command.goto, "product_search_worker_node")
            # 이전 검색 결과(상품 맥락)가 있으면 LLM 순서를 그대로 존중한다
            command = await supervisor.supervisor_node({**state, "last_products": [{"name": "프레데터"}]})
            self.assertEqual(command.goto, "product_analysis_worker_node")

    async def test_empty_remaining_order_falls_back_to_requested_list_order(self):
        """remaining_order를 LLM이 채우지 않은 경우, 기존 requested_capabilities 리스트 순서로
        정상 폴백해야 한다(하위 호환)."""
        fake_decision = SupervisorDecision(next="seller_search", remaining_order=[])
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="나이키 머큐리얼 베이퍼 10만원대 추천해주고 판매하는 곳도 알려줘")],
                    "requested_capabilities": ["product_search", "seller_search"],
                    "past_steps": [],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.goto, "product_search_worker_node")

    async def test_allows_llm_pick_after_reset_clears_requested_capabilities(self):
        # reset(workers._reset_fields)은 requested_capabilities도 함께 비우므로, 그 이후에는
        # LLM이 새 메시지를 보고 자유롭게 다음 capability를 고를 수 있어야 한다.
        fake_decision = SupervisorDecision(next="seller_search")
        with patch.object(supervisor, "_get_supervisor_classifier", return_value=AsyncMock(ainvoke=AsyncMock(return_value=fake_decision))):
            command = await supervisor.supervisor_node(
                {
                    "messages": [HumanMessage(content="아 됐고 판매처도 검색해줘")],
                    "requested_capabilities": [],
                    "past_steps": [],
                    "user_conditions": {},
                }
            )
        self.assertEqual(command.goto, "seller_search_worker_node")


if __name__ == "__main__":
    unittest.main()
