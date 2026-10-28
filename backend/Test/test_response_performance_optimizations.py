import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.LangGraph_buyeragent_with_personalization as buyer_graph
from FastAPI.main import _extract_stream_chunk
from Tools import crawl_and_index


class ResponsePerformanceOptimizationTest(unittest.IsolatedAsyncioTestCase):
    def test_extract_stream_chunk_allows_user_facing_node_streaming(self):
        event = {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "chitchat_node"},
            "data": {"chunk": SimpleNamespace(content="partial answer")},
        }

        self.assertEqual(_extract_stream_chunk(event), "partial answer")

    def test_extract_stream_chunk_ignores_non_user_facing_nodes(self):
        event = {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "extract_conditions_and_intent"},
            "data": {"chunk": SimpleNamespace(content="internal")},
        }

        self.assertIsNone(_extract_stream_chunk(event))

    def test_add_new_documents_deduplicates_batch_and_upserts_existing_ids(self):
        docs = [
            Document(
                page_content="first",
                metadata={"seller": "사커붐", "product_name": "제품 1"},
            ),
            Document(
                page_content="first duplicate",
                metadata={"seller": "사커붐", "product_name": "제품 1"},
            ),
            Document(
                page_content="second",
                metadata={"seller": "사커붐", "product_name": "제품 2"},
            ),
        ]

        class FakeCollection:
            def __init__(self):
                self.deleted_ids = []

            def get(self, ids):
                return {"ids": [ids[-1]]}

            def delete(self, ids):
                self.deleted_ids.extend(ids)

        class FakeVectorStore:
            def __init__(self):
                self._collection = FakeCollection()
                self.added_docs = []
                self.added_ids = []

            def add_documents(self, docs, ids):
                self.added_docs.extend(docs)
                self.added_ids.extend(ids)

        fake_store = FakeVectorStore()

        added_count = crawl_and_index._add_new_documents(docs, fake_store)

        self.assertEqual(added_count, 2)
        self.assertEqual(
            [doc.page_content for doc in fake_store.added_docs],
            ["first", "second"],
        )
        self.assertEqual(fake_store._collection.deleted_ids, [fake_store.added_ids[-1]])

    async def test_queue_user_memory_save_schedules_background_task(self):
        scheduled = []

        async def fake_save_user_memory(_state, _store):
            return {"user_profile": {"brand": "nike"}}

        def fake_create_task(coro):
            scheduled.append(coro)
            coro.close()
            return MagicMock()

        with (
            patch.object(buyer_graph, "save_user_memory", side_effect=fake_save_user_memory),
            patch.object(buyer_graph.asyncio, "create_task", side_effect=fake_create_task),
        ):
            result = await buyer_graph.queue_user_memory_save({"messages": []}, object())

        self.assertEqual(result, {})
        self.assertEqual(len(scheduled), 1)


if __name__ == "__main__":
    unittest.main()
