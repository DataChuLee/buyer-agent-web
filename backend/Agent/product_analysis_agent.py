"""
Product analysis flow.

This module intentionally keeps the required real-time crawl and
metadata-filtered RAG search, but removes the extra AgentExecutor
round trips that only decided which two fixed tools to call.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any

from dotenv import load_dotenv
from langchain_core.documents import Document

load_dotenv()

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(AGENT_DIR, ".."))
TOOLS_DIR = os.path.join(BACKEND_DIR, "Tools")

if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

from langchain_core.messages import HumanMessage

from Agent.product_search_agent import _extract_requested_price_range
from Tools.crawl_and_index import crawl_and_index
from Tools.rag_search import (
    _generate_answer,
    answer_cites_only_docs,
    filter_non_shoe_docs,
    format_docs,
    RagRetrievalError,
    retrieve_analysis_documents_filtered,
    rewrite_analysis_query,
)
from Tools.seller_normalization import (
    find_seller_displays_in_query,
    normalize_seller_crawler,
    normalize_seller_display,
)

SUPPORTED_CRAWLER_SELLERS = ["crazy11", "soccerboom", "redsoccer", "cafostore"]
DEFAULT_PRICE_RANGE = (0, 999999)


@dataclass
class ProductAnalysisResult:
    answer: str
    docs: list[Document]


def _extract_price_range(text: str) -> tuple[int, int]:
    # product_search_agent의 파서를 재사용 — 두 파서가 따로 있으면 "10만원 이상" 같은 같은
    # 문구가 product_search/product_analysis에서 서로 다른 상한(999,999 vs 9,999,999)으로
    # 해석되어, 같은 요청인데 한쪽만 결과가 필터링되는 불일치가 생긴다.
    return _extract_requested_price_range(text) or DEFAULT_PRICE_RANGE


def _extract_sellers(query: str, conditions: dict[str, Any] | None = None) -> list[str]:
    sellers: list[str] = []

    def add_seller(value: Any) -> None:
        crawler = normalize_seller_crawler(str(value or ""))
        if crawler in SUPPORTED_CRAWLER_SELLERS and crawler not in sellers:
            sellers.append(crawler)

    conditions = conditions or {}
    # seller 조건이 "크레이지11, 사커붐"처럼 여러 곳일 수 있으므로 구분자로 분리해 각각 추가
    for token in re.split(
        r"[,/]|과|와|랑|이랑|하고|그리고", str(conditions.get("seller") or "")
    ):
        add_seller(token)

    for display in find_seller_displays_in_query(query):
        add_seller(display)

    return sellers or list(SUPPORTED_CRAWLER_SELLERS)


def _extract_product_keyword(
    query: str, conditions: dict[str, Any] | None = None
) -> str:
    conditions = conditions or {}
    for key in ("product_name", "brand"):
        value = str(conditions.get(key) or "").strip()
        if value:
            return value

    cleaned = str(query or "")
    # 영문/한글 셀러명 제거
    cleaned = re.sub(
        r"\b(crazy11|soccerboom|redsoccer|cafostore)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"(크레이지11|사커붐|레드사커|카포스토어)", " ", cleaned)
    cleaned = re.sub(r"\d+\s*만원\s*(?:대|이상|이하)?", " ", cleaned)
    # 2글자 이상 조사/동사만 안전하게 제거 — "이/가/은/는" 같은 1글자는 단어 내부와 충돌(예: "나이키" → "나 키")
    cleaned = re.sub(
        r"(에서|비교|분석|추천|해줘|해주세요|축구화|풋살화|이랑|하고|또는|그리고)",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "축구화"


_GROUND_TYPES = ["TF", "FG", "AG", "HG", "IC", "MG", "SG"]


def _extract_ground_type(
    text: str, conditions: dict[str, Any] | None = None
) -> str | None:
    """질의/조건에서 지면 종류(TF/FG/AG/HG/IC/MG/SG)를 추출. 없으면 None."""
    haystack = " ".join(
        [str(text or ""), *(str(v) for v in (conditions or {}).values())]
    ).upper()
    for ground in _GROUND_TYPES:
        # \b는 한글도 단어 문자로 봐서 "TF용"의 TF를 못 잡는다 → 영숫자만 경계로 본다
        if re.search(rf"(?<![A-Z0-9]){ground}(?![A-Z0-9])", haystack):
            return ground
    return None


def _extract_size(text: str, conditions: dict[str, Any] | None = None) -> str | None:
    """질의/조건에서 신발 사이즈(3자리 숫자)를 추출. 없으면 None."""
    size_condition = str((conditions or {}).get("size") or "").strip()
    if size_condition.isdigit():
        return size_condition
    if match := re.search(r"사이즈\s*(?:가|는|이)?\s*(\d{3})|(\d{3})\s*사이즈", str(text or "")):
        return match.group(1) or match.group(2)
    return None


def _format_price_range(min_price: int, max_price: int) -> str:
    if (min_price, max_price) == DEFAULT_PRICE_RANGE:
        return "가격 제한 없음"
    if min_price <= 0:
        return f"{max_price:,}원 이하"
    if max_price >= DEFAULT_PRICE_RANGE[1]:
        return f"{min_price:,}원 이상"
    return f"{min_price:,}~{max_price:,}원"


def _format_seller_names(sellers: list[str]) -> str:
    return ", ".join(normalize_seller_display(seller) for seller in sellers)


def _build_no_result_answer(
    product_keyword: str,
    sellers: list[str],
    min_price: int,
    max_price: int,
    ground_type: str | None,
    size: str | None = None,
    conditions: dict[str, Any] | None = None,
) -> str:
    conditions = conditions or {}
    filters = [
        f"상품 키워드: {product_keyword}",
        f"판매처: {_format_seller_names(sellers)}",
        f"판매가 범위: {_format_price_range(min_price, max_price)}",
    ]
    if ground_type:
        filters.append(f"지면: {ground_type}")
    if size:
        filters.append(f"사이즈: {size}")
    if conditions.get("age_group"):
        filters.append(f"연령대: {conditions['age_group']}")

    return (
        "요청하신 조건에 부합하는 축구화 정보를 찾을 수 없습니다.\n\n"
        f"확인한 조건은 {' / '.join(filters)}입니다. "
        "크롤링 캐시와 RAG 검색 결과에서 이 조건을 동시에 만족하는 상품 문서가 없었습니다. "
        "판매처를 넓히거나, 가격대를 완화하거나, 지면 조건을 빼고 다시 요청해 주세요."
    )


def _build_retrieval_unavailable_answer() -> str:
    """Keep a retrieval outage distinct from a valid no-product result."""
    return (
        "현재 상품 검색을 완료하지 못했습니다. 조건에 맞는 상품이 없다는 뜻은 아니며, "
        "잠시 후 다시 요청해 주세요."
    )


async def _crawl_and_search_seller(
    seller: str,
    product_keyword: str,
    min_price: int,
    max_price: int,
    base_query: str,
    ground_type: str | None = None,
    size: str | None = None,
    exclude_keys: set[str] | None = None,
) -> list[Document]:
    """단일 판매처: 크롤 완료 후 RAG 검색. 타 판매처와는 asyncio.gather로 병렬 실행.

    검색은 판매처/가격대/지면/사이즈 메타데이터를 명시적으로 필터링하고 상품명에 모델 키워드가
    실제 포함된 문서만 남긴다(엉뚱한 판매처/가격대/모델/사이즈 노출 차단)."""
    await crawl_and_index.ainvoke(
        {
            "sellers": [seller],
            "product_keyword": product_keyword,
            "min_price": min_price,
            "max_price": max_price,
        }
    )
    seller_display = normalize_seller_display(seller)
    return retrieve_analysis_documents_filtered(
        seller_display=seller_display,
        product_keyword=product_keyword,
        min_price=min_price,
        max_price=max_price,
        limit=3,
        ground_type=ground_type,
        size=size,
        exclude_keys=exclude_keys,
    )


def _merge_docs_round_robin(docs_per_seller: list[list[Document]]) -> list[Document]:
    """판매처별 결과를 라운드로빈으로 섞어 병합 + (seller, product_name) 기준 중복 제거."""
    seen: set[tuple[str, str] | str] = set()
    merged: list[Document] = []
    for round_docs in zip_longest(*docs_per_seller):
        for doc in round_docs:
            if doc is None:
                continue
            meta = doc.metadata or {}
            seller = str(meta.get("seller") or "").strip()
            name = str(meta.get("product_name") or "").strip()
            key: tuple[str, str] | str = (seller, name) if seller and name else (
                meta.get("product_url") or doc.page_content
            )
            if key not in seen:
                seen.add(key)
                merged.append(doc)
    return merged


async def product_analysis_agent(
    query: str,
    user_profile: dict | None = None,
    conditions: dict[str, Any] | None = None,
    return_result: bool = False,
    original_query: str | None = None,
    exclude_keys: set[str] | None = None,
) -> str | ProductAnalysisResult:
    del user_profile  # Profile use is handled by the outer graph state.

    search_query = original_query or query
    crawl_query_text = " ".join(
        str(value)
        for value in [search_query, *((conditions or {}).values())]
        if value is not None
    )
    min_price, max_price = _extract_price_range(crawl_query_text)
    sellers = _extract_sellers(search_query, conditions)
    product_keyword = _extract_product_keyword(search_query, conditions)
    ground_type = _extract_ground_type(search_query, conditions)
    size = _extract_size(search_query, conditions)

    # 후속 질문("다른 건 없어?")처럼 원문이 빈약해도 가격대/상품명이 RAG 검색에 실리도록
    # 조건을 병합한 검색용 base 쿼리를 구성. (search_query 는 답변 생성 컨텍스트용으로만 유지)
    condition_terms = " ".join(
        str((conditions or {}).get(key))
        for key in ("product_name", "brand", "budget", "age_group", "surface")
        if (conditions or {}).get(key)
    )
    retrieval_base = f"{product_keyword} {condition_terms}".strip() or search_query

    # 판매처별 [크롤 → RAG 검색] 파이프라인을 병렬 실행
    try:
        docs_per_seller: list[list[Document]] = await asyncio.gather(
            *[
                _crawl_and_search_seller(
                    seller,
                    product_keyword,
                    min_price,
                    max_price,
                    retrieval_base,
                    ground_type,
                    size=size,
                    exclude_keys=exclude_keys,
                )
                for seller in sellers
            ]
        )
    except RagRetrievalError:
        unavailable = ProductAnalysisResult(answer=_build_retrieval_unavailable_answer(), docs=[])
        return unavailable if return_result else unavailable.answer

    # 결과 병합 + 중복 제거. 판매처 순서대로 이어붙이면 한 판매처가 limit을 다 채워 나머지
    # 판매처가 카드에 등장하지 못하므로, 라운드로빈으로 섞어 하위 limit 절단이 공평하게 적용되게 한다.
    all_docs = _merge_docs_round_robin(docs_per_seller)

    # 제외(exclude_keys) 때문에 후보가 0건이면 = 이미 보여준 것 외엔 없음.
    # 불필요한 LLM 호출을 건너뛰고 빈 결과를 반환한다("더 이상 없음" 문구는 호출 노드에서 처리).
    if not all_docs and exclude_keys:
        empty = ProductAnalysisResult(answer="", docs=[])
        return empty if return_result else empty.answer

    def no_result() -> ProductAnalysisResult:
        return ProductAnalysisResult(
            answer=_build_no_result_answer(
                product_keyword=product_keyword,
                sellers=sellers,
                min_price=min_price,
                max_price=max_price,
                ground_type=ground_type,
                size=size,
                conditions=conditions,
            ),
            docs=[],
        )

    if not all_docs:
        result = no_result()
        return result if return_result else result.answer

    # 생성 전: 메타데이터 필터가 못 거르는 비축구화(장갑·축구공)를 뺀다. 전부 빠지면 질문을
    # 넓혀 재작성해 1회만 재크롤링/재검색한다(무한 루프 방지 — product_search_agent의
    # _run_surface_expanded_search와 동일한 "한 번만 재시도" 철학).
    graded_docs = filter_non_shoe_docs(all_docs)
    if not graded_docs:
        rewritten_query = await rewrite_analysis_query(search_query, conditions)
        try:
            docs_per_seller_retry = await asyncio.gather(
                *[
                    _crawl_and_search_seller(
                        seller,
                        product_keyword,
                        min_price,
                        max_price,
                        rewritten_query,
                        ground_type,
                        size=size,
                        exclude_keys=exclude_keys,
                    )
                    for seller in sellers
                ]
            )
        except RagRetrievalError:
            unavailable = ProductAnalysisResult(answer=_build_retrieval_unavailable_answer(), docs=[])
            return unavailable if return_result else unavailable.answer
        retry_docs = _merge_docs_round_robin(docs_per_seller_retry)
        graded_docs = filter_non_shoe_docs(retry_docs)
        if not graded_docs:
            result = no_result()
            return result if return_result else result.answer

    all_docs = graded_docs
    context = format_docs(all_docs)
    # LLM이 "10만원대"를 잘못 해석해 이미 필터를 통과한 문서를 버리고 "찾을 수 없습니다"로 답하던 문제 →
    # 파싱해 둔 가격 범위를 숫자로 함께 준다.
    generation_query = (
        search_query
        if (min_price, max_price) == DEFAULT_PRICE_RANGE
        else f"{search_query}\n(가격 조건: {min_price:,}~{max_price:,}원)"
    )
    answer = await _generate_answer(context, [HumanMessage(content=generation_query)])

    # 생성 후: 답변의 가격·URL이 문서에 없거나, 문서가 있는데 "찾을 수 없습니다"로 답하면 강화된 지시로
    # 1회만 재생성한다(LLM 채점 대신 코드 검사 — 근거: backend/prompts/analysis_answer.yaml changelog).
    if not answer_cites_only_docs(answer, all_docs) or "찾을 수 없습니다" in answer:
        answer = await _generate_answer(
            context,
            [
                HumanMessage(
                    content=f"{generation_query}\n\n"
                    "(주의: Context에 없는 가격/스펙/기능은 절대 언급하지 마세요.)"
                )
            ],
        )

    result = ProductAnalysisResult(answer=answer, docs=all_docs)
    return result if return_result else result.answer


if __name__ == "__main__":

    async def test():
        result = await product_analysis_agent(
            "크레이지11에서 머큐리얼 베이퍼 성인용 TF 사이즈 270 10만원대 추천해줘"
        )
        print(result)

    asyncio.run(test())
