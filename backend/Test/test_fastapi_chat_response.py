import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from FastAPI.main import _build_chat_response


class BuildChatResponseTest(unittest.TestCase):
    def test_preserves_checkout_session_automation_metadata(self):
        result = {
            "user_id": "user-1",
            "session_id": "session-1",
            "status": "done",
            "messages": [],
            "purchase_status": "ready_for_checkout",
            "purchase_missing_fields": [],
            "checkout_session": {
                "id": "checkout-1",
                "seller_code": "crazy11",
                "automation_mode": "local_agent_browser",
                "approval_boundary": "before_payment_submit",
            },
        }

        response = _build_chat_response(result)

        self.assertEqual(response.purchase_status, "ready_for_checkout")
        self.assertIsNotNone(response.checkout_session)
        self.assertEqual(
            response.checkout_session["automation_mode"],
            "local_agent_browser",
        )
        self.assertEqual(
            response.checkout_session["approval_boundary"],
            "before_payment_submit",
        )


if __name__ == "__main__":
    unittest.main()
