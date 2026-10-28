import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

from FastAPI.main import _build_progress_payload


class FastApiProgressEventsTest(unittest.TestCase):
    def test_product_search_progress_payload_has_agent_and_step(self):
        payload = _build_progress_payload("product_search_worker_node")

        self.assertEqual(payload["type"], "progress")
        self.assertEqual(payload["agent"], "product_search")
        self.assertEqual(payload["step"], "searching_products")
        self.assertIn("축구화", payload["message"])

    def test_product_guide_progress_payload_has_guide_step(self):
        payload = _build_progress_payload("product_guide_node")

        self.assertEqual(payload["agent"], "product_guide")
        self.assertEqual(payload["step"], "generating_guide")


if __name__ == "__main__":
    unittest.main()
