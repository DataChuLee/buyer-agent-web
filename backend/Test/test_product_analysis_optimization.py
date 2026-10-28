import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.documents import Document


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGSMITH_TRACING", "false")

import Agent.product_analysis_agent as analysis_agent
import Tools.rag_search as rag_search
from Agent.product_analysis_agent import ProductAnalysisResult


def _product_doc(product_url: str = "https://example.test/product") -> Document:
    return Document(
        page_content=(
            "상품명: 머큐리얼 베이퍼\n"
            "판매자: 크레이지11\n"
            "카테고리: 축구화\n"
            "연령대: 성인용\n"
            "지면: TF\n"
            "가격: 109000원\n"
            "사이즈: 260, 265, 270"
        ),
        metadata={
            "seller": "크레이지11",
            "product_name": "머큐리얼 베이퍼",
            "product_price": 109000,
            "size_text": "260,265,270",
            "product_category": "축구화",
            "age_group": "성인용",
            "ground_type": "TF",
            "image_url": "https://example.test/image.jpg",
            "product_url": product_url,
        },
    )


class ProductAnalysisOptimizationTest(unittest.IsolatedAsyncioTestCase):
    def test_extract_price_range_handles_supported_budget_phrases(self):
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼 10만원대"), (100000, 199999))
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼 15만원대"), (150000, 159999))
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼 20만원대"), (200000, 299999))
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼 10만원 이상"), (100000, 9999999))
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼 10만원 이하"), (0, 100000))
        self.assertEqual(analysis_agent._extract_price_range("머큐리얼"), (0, 999999))

    def test_extract_size_reads_condition_or_text(self):
        self.assertEqual(analysis_agent._extract_size("아무 텍스트", {"size": "265"}), "265")
        self.assertEqual(analysis_agent._extract_size("사이즈가 265인 제품은 없어?"), "265")
        self.assertIsNone(analysis_agent._extract_size("머큐리얼 베이퍼 비교"))

    def test_extract_sellers_defaults_to_all_supported_sellers(self):
        self.assertEqual(
            analysis_agent._extract_sellers("머큐리얼 베이퍼 비교", {}),
            ["crazy11", "soccerboom", "redsoccer", "cafostore"],
        )

    def test_extract_sellers_uses_explicit_seller(self):
        self.assertEqual(
            analysis_agent._extract_sellers("crazy11에서 머큐리얼 비교", {}),
            ["crazy11"],
        )

    async def test_product_analysis_agent_calls_crawl_then_fast_rag(self):
        doc = _product_doc()
        with (
            patch.object(
                analysis_agent,
                "_crawl_and_search_seller",
                new=AsyncMock(return_value=[doc]),
            ) as crawl_search,
            patch.object(analysis_agent, "_generate_answer", new=AsyncMock(return_value="analysis answer")) as generate_answer,
            patch.object(analysis_agent, "grade_docs_relevance", new=AsyncMock(side_effect=lambda q, docs: docs)),
            patch.object(analysis_agent, "grade_answer_groundedness", new=AsyncMock(return_value=True)),
        ):
            result = await analysis_agent.product_analysis_agent(
                "crazy11에서 머큐리얼 10만원대 비교 분석",
                conditions={
                    "seller": "crazy11",
                    "product_name": "머큐리얼",
                    "budget": "10만원대",
                },
                return_result=True,
            )

        crawl_search.assert_awaited_once_with(
            "crazy11",
            "머큐리얼",
            100000,
            199999,
            "머큐리얼 머큐리얼 10만원대",
            None,
            size=None,
            exclude_keys=None,
        )
        generate_answer.assert_awaited_once()
        self.assertIsInstance(result, ProductAnalysisResult)
        self.assertEqual(result.answer, "analysis answer")
        self.assertEqual(result.docs, [doc])

    async def test_product_analysis_agent_interleaves_results_across_sellers(self):
        """한 판매처가 문서를 많이 갖고 있어도(예: crazy11 3건) 다른 판매처(각 1건)가
        하위 limit 절단에서 밀려나지 않도록 판매처별 결과를 라운드로빈으로 섞어야 한다."""

        def _seller_doc(seller_display: str, index: int) -> Document:
            doc = _product_doc(f"https://example.test/{seller_display}/{index}")
            doc.metadata = {**doc.metadata, "seller": seller_display}
            return doc

        seller_counts = {
            "crazy11": ("크레이지11", 3),
            "soccerboom": ("사커붐", 1),
            "redsoccer": ("레드사커", 1),
            "cafostore": ("카포스토어", 1),
        }

        async def fake_crawl_and_search_seller(seller, *_args, **_kwargs):
            display, count = seller_counts[seller]
            return [_seller_doc(display, i) for i in range(count)]

        with (
            patch.object(
                analysis_agent,
                "_crawl_and_search_seller",
                new=AsyncMock(side_effect=fake_crawl_and_search_seller),
            ),
            patch.object(analysis_agent, "_generate_answer", new=AsyncMock(return_value="analysis answer")),
            patch.object(analysis_agent, "grade_docs_relevance", new=AsyncMock(side_effect=lambda q, docs: docs)),
            patch.object(analysis_agent, "grade_answer_groundedness", new=AsyncMock(return_value=True)),
        ):
            result = await analysis_agent.product_analysis_agent(
                "축구화 비교", conditions={}, return_result=True,
            )

        first_four_sellers = [doc.metadata["seller"] for doc in result.docs[:4]]
        self.assertEqual(len(set(first_four_sellers)), 4)

    async def test_product_analysis_agent_explains_no_matching_rag_documents(self):
        with (
            patch.object(
                analysis_agent,
                "_crawl_and_search_seller",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(analysis_agent, "_generate_answer", new=AsyncMock()) as generate_answer,
        ):
            result = await analysis_agent.product_analysis_agent(
                "크레이지11에서 머큐리얼 10만원대 TF 비교",
                conditions={
                    "seller": "크레이지11",
                    "product_name": "머큐리얼",
                    "budget": "10만원대",
                    "surface": "TF",
                },
                return_result=True,
            )

        generate_answer.assert_not_called()
        self.assertIsInstance(result, ProductAnalysisResult)
        self.assertEqual(result.docs, [])
        self.assertIn("머큐리얼", result.answer)
        self.assertIn("크레이지11", result.answer)
        self.assertIn("100,000~199,999원", result.answer)
        self.assertIn("TF", result.answer)

    async def test_product_analysis_agent_does_not_mislabel_retrieval_failure_as_no_result(self):
        with patch.object(
            analysis_agent,
            "_crawl_and_search_seller",
            new=AsyncMock(side_effect=rag_search.RagRetrievalError("search failed")),
        ):
            result = await analysis_agent.product_analysis_agent(
                "크레이지11에서 머큐리얼 비교",
                conditions={"seller": "crazy11", "product_name": "머큐리얼"},
                return_result=True,
            )

        self.assertEqual(result.docs, [])
        self.assertIn("검색을 완료하지 못했습니다", result.answer)
        self.assertNotIn("조건을 만족하는 축구화 정보를 찾을 수 없습니다", result.answer)

    async def test_product_analysis_agent_retries_once_when_docs_all_irrelevant(self):
        doc = _product_doc()
        with (
            patch.object(
                analysis_agent,
                "_crawl_and_search_seller",
                new=AsyncMock(return_value=[doc]),
            ) as crawl_search,
            patch.object(analysis_agent, "_generate_answer", new=AsyncMock()) as generate_answer,
            patch.object(analysis_agent, "grade_docs_relevance", new=AsyncMock(return_value=[])),
            patch.object(analysis_agent, "rewrite_analysis_query", new=AsyncMock(return_value="넓힌 검색어")),
        ):
            result = await analysis_agent.product_analysis_agent(
                "크레이지11에서 머큐리얼 10만원대 비교",
                conditions={"seller": "crazy11", "product_name": "머큐리얼"},
                return_result=True,
            )

        generate_answer.assert_not_called()
        self.assertEqual(result.docs, [])
        self.assertIn("찾을 수 없습니다", result.answer)
        self.assertEqual(crawl_search.await_count, 2)  # 1차 시도 + 재작성 후 1회 재시도

    async def test_product_analysis_agent_regenerates_once_on_hallucination(self):
        doc = _product_doc()
        with (
            patch.object(
                analysis_agent,
                "_crawl_and_search_seller",
                new=AsyncMock(return_value=[doc]),
            ),
            patch.object(
                analysis_agent, "_generate_answer", new=AsyncMock(side_effect=["첫 답변", "재생성된 답변"])
            ) as generate_answer,
            patch.object(analysis_agent, "grade_docs_relevance", new=AsyncMock(side_effect=lambda q, docs: docs)),
            patch.object(analysis_agent, "grade_answer_groundedness", new=AsyncMock(return_value=False)),
        ):
            result = await analysis_agent.product_analysis_agent(
                "크레이지11에서 머큐리얼 10만원대 비교",
                conditions={"seller": "crazy11", "product_name": "머큐리얼"},
                return_result=True,
            )

        self.assertEqual(generate_answer.call_count, 2)
        self.assertEqual(result.answer, "재생성된 답변")

    async def test_product_analysis_agent_passes_size_condition_to_search(self):
        # 회귀: "사이즈가 265인 제품은 없어?" 같은 후속 질문이 필터링 기반 RAG 재검색으로
        # 이어지는지(카드 텍스트를 LLM이 눈으로 훑고 답하는 대신) 검증.
        doc = _product_doc()
        with (
            patch.object(analysis_agent, "_crawl_and_search_seller", new=AsyncMock(return_value=[doc])) as crawl_search,
            patch.object(analysis_agent, "_generate_answer", new=AsyncMock(return_value="analysis answer")),
            patch.object(analysis_agent, "grade_docs_relevance", new=AsyncMock(side_effect=lambda q, docs: docs)),
            patch.object(analysis_agent, "grade_answer_groundedness", new=AsyncMock(return_value=True)),
        ):
            await analysis_agent.product_analysis_agent(
                "크레이지11에서 머큐리얼 사이즈 265 있어?",
                conditions={"seller": "crazy11", "product_name": "머큐리얼", "size": "265"},
                return_result=True,
            )

        self.assertEqual(crawl_search.await_args.kwargs["size"], "265")

    def test_build_analysis_cards_from_docs_preserves_product_metadata(self):
        cards = rag_search.build_analysis_cards_from_docs([_product_doc()], limit=5)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["name"], "머큐리얼 베이퍼")
        self.assertEqual(cards[0]["seller"], "크레이지11")
        self.assertEqual(cards[0]["price"], "109,000원")
        self.assertEqual(cards[0]["size"], "260, 265, 270")
        self.assertEqual(cards[0]["image"], "https://example.test/image.jpg")
        self.assertEqual(cards[0]["url"], "https://example.test/product")

    def test_build_analysis_cards_from_docs_groups_by_seller_with_per_seller_cap(self):
        # 회귀: limit이 전역 절단선이면 라운드로빈 병합 순서 그대로 노출돼 판매처별로 카드가
        # 묶이지 않고 뒤섞여 보였다(실사용 재현: 크레이지11/카포스토어/크레이지11/크레이지11
        # 순서로 표시). limit은 이제 판매처당 최대 개수이고, 출력은 판매처별로 묶여야 한다.
        def doc(seller: str, name: str) -> Document:
            return Document(
                page_content="",
                metadata={"seller": seller, "product_name": name, "product_url": f"https://x.test/{seller}-{name}"},
            )

        docs = [
            doc("크레이지11", "A"),
            doc("카포스토어", "B"),
            doc("크레이지11", "C"),
            doc("크레이지11", "D"),
            doc("크레이지11", "E"),
        ]

        cards = rag_search.build_analysis_cards_from_docs(docs, limit=3)

        self.assertEqual(
            [(c["seller"], c["name"]) for c in cards],
            [("크레이지11", "A"), ("크레이지11", "C"), ("크레이지11", "D"), ("카포스토어", "B")],
        )

    def test_retrieve_analysis_documents_filtered_applies_size_range_filter(self):
        captured = {}

        def fake_similarity_search(query, k, filter):
            captured["filter"] = filter
            return [_product_doc()]

        with patch.object(rag_search.vectorstore, "similarity_search", side_effect=fake_similarity_search):
            docs = rag_search.retrieve_analysis_documents_filtered(
                seller_display="크레이지11", product_keyword="머큐리얼",
                min_price=0, max_price=999999, size="265",
            )

        self.assertIn({"size_min": {"$lte": 265}}, captured["filter"]["$and"])
        self.assertIn({"size_max": {"$gte": 265}}, captured["filter"]["$and"])
        self.assertEqual(len(docs), 1)  # size_text "260,265,270" 에 265 포함

    def test_retrieve_analysis_documents_filtered_excludes_size_mismatch(self):
        # size_min/size_max 범위(260~270)엔 걸려도 실제 size_text(콤마 목록)에 없는 사이즈는 걸러야
        # 한다(중간에 빠진 사이즈까지 있다고 오답하지 않도록).
        with patch.object(
            rag_search.vectorstore, "similarity_search", side_effect=lambda query, k, filter: [_product_doc()]
        ):
            docs = rag_search.retrieve_analysis_documents_filtered(
                seller_display="크레이지11", product_keyword="머큐리얼",
                min_price=0, max_price=999999, size="299",
            )

        self.assertEqual(docs, [])

    def test_retrieve_analysis_documents_filtered_raises_on_search_failure(self):
        with patch.object(rag_search.vectorstore, "similarity_search", side_effect=RuntimeError("network failed")):
            with self.assertRaises(rag_search.RagRetrievalError):
                rag_search.retrieve_analysis_documents_filtered(
                    seller_display="크레이지11", product_keyword="머큐리얼", min_price=0, max_price=999999
                )


if __name__ == "__main__":
    unittest.main()
