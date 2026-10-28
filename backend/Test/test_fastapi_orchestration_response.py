import os
import sys
import unittest
from types import SimpleNamespace


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")


from FastAPI.main import _build_chat_response


class FastApiOrchestrationResponseTest(unittest.TestCase):
    def test_build_chat_response_surfaces_interrupt_as_pending_action(self):
        # 워커 노드가 interrupt()로 멈춘 턴은 result["products"/"status"/...]가 아직
        # 커밋되지 않았으므로, __interrupt__ payload에서 카드/메시지를 가져와야 한다.
        pending_action = {
            "type": "ps_review",
            "message": "추천 후보 중 하나를 골라주세요.",
            "cards": [{"name": "나이키 머큐리얼"}],
            "options": ["나이키 머큐리얼"],
            "resume_mode": "natural_language",
        }
        response = _build_chat_response(
            {
                "user_id": "user-1",
                "session_id": "session-1",
                "request_id": "req-1",
                "__interrupt__": [SimpleNamespace(value=pending_action)],
            }
        )

        self.assertEqual(response.status, "waiting_input")
        self.assertEqual(response.active_agent, "product_search")
        self.assertEqual(response.request_id, "req-1")
        self.assertEqual(response.response, "추천 후보 중 하나를 골라주세요.")
        self.assertEqual(response.pending_action["type"], "ps_review")
        self.assertEqual(response.products[0]["name"], "나이키 머큐리얼")

    def test_build_chat_response_has_no_pending_action_when_not_interrupted(self):
        from langchain_core.messages import AIMessage

        response = _build_chat_response(
            {
                "user_id": "user-1",
                "session_id": "session-1",
                "status": "done",
                "active_agent": "chitchat",
                "messages": [AIMessage(content="안녕하세요")],
            }
        )

        self.assertIsNone(response.pending_action)
        self.assertEqual(response.response, "안녕하세요")


if __name__ == "__main__":
    unittest.main()
