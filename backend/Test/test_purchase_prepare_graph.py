import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.messages import HumanMessage


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.LangGraph_buyeragent_with_personalization as buyer_graph


def _input_state(message: str) -> dict:
    return {
        "session_id": "session_purchase_test",
        "user_id": "user_purchase_test",
        "messages": [HumanMessage(content=message)],
        "intent": "",
        "active_agent": None,
        "missing_conditions": [],
        "status": "extracting",
        "error": None,
        "retry_count": 0,
        "question_options": None,
        "question_sequence": None,
    }


async def _fake_extract_conditions_and_intent(state):
    message = next(
        str(msg.content)
        for msg in reversed(state["messages"])
        if isinstance(msg, HumanMessage)
    )
    base = {
        "user_profile": state.get("user_profile") or {},
        "user_conditions": dict(state.get("user_conditions", {})),
        "status": "checking",
    }
    if "분석" in message:
        return {
            **base,
            "intent": "product_analysis",
            "user_conditions": {
                **base["user_conditions"],
                "product_name": "머큐리얼 베이퍼",
                "seller": "크레이지11",
            },
        }
    if any(token in message for token in ["살게", "270", "홍길동"]):
        return {**base, "intent": "purchase_prepare"}
    return {**base, "intent": "chitchat"}


async def _fake_parse_analysis(_text: str):
    return [
        {
            "name": "나이키 줌 머큐리얼 베이퍼 16 프로 TF",
            "seller": "크레이지11",
            "price": "109,000원",
            "size": "245, 250, 255, 260, 265, 270",
            "url": "https://www.crazy11.co.kr/shop/shopdetail.html?branduid=123",
        },
        {
            "name": "나이키 팬텀 GX 2 아카데미",
            "seller": "크레이지11",
            "price": "99,000원",
            "size": "250, 255, 260",
            "url": "https://www.crazy11.co.kr/shop/shopdetail.html?branduid=456",
        },
    ]


async def _fake_extract_purchase_fields(message: str, _analysis):
    if "첫 번째" in message:
        return buyer_graph.PurchaseExtractionResult(product_index=1)
    if "270" in message:
        return buyer_graph.PurchaseExtractionResult(size="270")
    if "홍길동" in message:
        return buyer_graph.PurchaseExtractionResult(
            recipient_name="홍길동",
            phone="010-1234-5678",
            address="서울시 강남구 테헤란로 1",
            detail_address="101동 202호",
        )
    return buyer_graph.PurchaseExtractionResult()


class PurchasePrepareGraphTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.profile_patch = patch.object(
            buyer_graph.profile_manager, "ainvoke", AsyncMock(return_value=None)
        )
        self.extract_patch = patch.object(
            buyer_graph,
            "extract_conditions_and_intent",
            side_effect=_fake_extract_conditions_and_intent,
        )
        self.analysis_agent_patch = patch.object(
            buyer_graph,
            "product_analysis_agent",
            AsyncMock(return_value="analysis response"),
        )
        self.parse_analysis_patch = patch.object(
            buyer_graph,
            "_parse_analysis",
            side_effect=_fake_parse_analysis,
        )
        self.build_analysis_cards_patch = patch.object(
            buyer_graph,
            "build_analysis_cards",
            return_value=[],
        )
        self.extract_purchase_patch = patch.object(
            buyer_graph,
            "_extract_purchase_fields",
            side_effect=_fake_extract_purchase_fields,
        )

        self.profile_patch.start()
        self.extract_patch.start()
        self.analysis_agent_patch.start()
        self.parse_analysis_patch.start()
        self.build_analysis_cards_patch.start()
        self.extract_purchase_patch.start()

        self.graph = buyer_graph._build_graph(MemorySaver(), InMemoryStore())
        self.config = {"configurable": {"thread_id": "purchase-graph-test"}}

    async def asyncTearDown(self):
        self.parse_analysis_patch.stop()
        self.build_analysis_cards_patch.stop()
        self.extract_purchase_patch.stop()
        self.analysis_agent_patch.stop()
        self.extract_patch.stop()
        self.profile_patch.stop()

    async def test_purchase_prepare_flow_creates_checkout_session(self):
        analysis_result = await self.graph.ainvoke(
            _input_state("크레이지11에서 머큐리얼 베이퍼 분석해줘"),
            config=self.config,
        )
        self.assertEqual(analysis_result["status"], "done")
        self.assertEqual(len(analysis_result["analysis"]), 2)
        self.assertEqual(
            analysis_result["analysis"][0]["product_url"],
            "https://www.crazy11.co.kr/shop/shopdetail.html?branduid=123",
        )

        select_result = await self.graph.ainvoke(
            _input_state("첫 번째 걸로 살게"),
            config=self.config,
        )
        self.assertEqual(select_result["status"], "waiting_input")
        self.assertEqual(select_result["purchase_status"], "awaiting_purchase_info")
        self.assertEqual(
            select_result["selected_product"]["product_key"],
            "https://www.crazy11.co.kr/shop/shopdetail.html?branduid=123",
        )
        self.assertEqual(
            select_result["purchase_missing_fields"],
            ["size", "recipient_name", "phone", "address", "detail_address"],
        )

        size_result = await self.graph.ainvoke(
            _input_state("270으로 해줘"),
            config=self.config,
        )
        self.assertEqual(size_result["status"], "waiting_input")
        self.assertEqual(size_result["selected_product"]["selected_size"], "270")
        self.assertEqual(
            size_result["purchase_missing_fields"],
            ["recipient_name", "phone", "address", "detail_address"],
        )

        checkout_result = await self.graph.ainvoke(
            _input_state("홍길동, 010-1234-5678, 서울시 강남구 테헤란로 1, 101동 202호"),
            config=self.config,
        )
        self.assertEqual(checkout_result["status"], "done")
        self.assertEqual(checkout_result["purchase_status"], "ready_for_checkout")
        self.assertEqual(checkout_result["purchase_missing_fields"], [])
        self.assertEqual(checkout_result["checkout_session"]["seller_code"], "crazy11")
        self.assertEqual(
            checkout_result["checkout_session"]["automation_mode"],
            "local_agent_browser",
        )
        self.assertEqual(
            checkout_result["checkout_session"]["approval_boundary"],
            "before_payment_submit",
        )
        self.assertEqual(checkout_result["checkout_session"]["product"]["size"], "270")
        self.assertEqual(
            checkout_result["checkout_session"]["shipping_info"]["recipient_name"],
            "홍길동",
        )


if __name__ == "__main__":
    unittest.main()
