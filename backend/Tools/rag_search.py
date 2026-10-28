"""
rag_search.py
=============
product_analysis_agent 전용 RAG 검색 + CRAG/Self-RAG 채점 헬퍼.

- vectorstore: crawl_and_index 도구와 공유하는 Chroma 인스턴스
- retrieve_analysis_documents_filtered: 판매처/가격대/지면 메타데이터로 명시적 필터링하는 검색
- build_analysis_cards_from_docs: 검색 문서 → 응답 카드 변환
- grade_docs_relevance / rewrite_analysis_query / grade_answer_groundedness: CRAG/Self-RAG 채점
"""

import re
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

load_dotenv()

# ── 모델 & 임베딩 ───────────────────────────────────────────
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ── Shared Vectorstore (crawl_and_index 도구가 upsert, graph가 검색) ──
# singleton 모듈에서 가져와 import 경로 차이로 인한 인스턴스 분리 방지
try:
    from Tools.vectorstore_singleton import vectorstore
except ImportError:
    from vectorstore_singleton import vectorstore


_GENERIC_KEYWORD_TOKENS = {"축구화", "풋살화", "축구", "풋살", "신발", "추천", "비교", "분석"}


class RagRetrievalError(RuntimeError):
    """Raised when retrieval infrastructure fails before a result can be judged empty.

    An empty result is a business fact (no indexed document matches the request).
    An embedding/vector-store exception is an operational failure.  They must not
    share the same ``[]`` return value, otherwise the API tells the user that no
    product exists when the search never completed.
    """


def _keyword_tokens(product_keyword: str) -> list[str]:
    """상품 키워드에서 모델 식별에 쓸 유의미 토큰만 추출(브랜드/모델명). 1글자·일반어 제외."""
    tokens = []
    for raw in re.split(r"\s+", str(product_keyword or "")):
        token = raw.strip()
        if len(token) >= 2 and token not in _GENERIC_KEYWORD_TOKENS:
            tokens.append(token)
    return tokens


def retrieve_analysis_documents_filtered(
    seller_display: str,
    product_keyword: str,
    min_price: int,
    max_price: int,
    limit: int = 6,
    ground_type: str | None = None,
    size: str | None = None,
    exclude_keys: set[str] | None = None,
) -> list[Document]:
    """판매처/가격대/지면/사이즈 메타데이터로 ChromaDB 를 '명시적으로' 필터링하고, 상품명에
    모델 키워드가 실제로 포함된 문서만 남긴다.

    SelfQueryRetriever(LLM 파싱)에 의존하면 실패 시 필터 없는 similarity_search 로 떨어져,
    판매처·가격대·모델 조건을 무시한 엉뚱한 상품을 반환하는 문제가 있다. 분석 경로는 호출
    시점에 이미 판매처·가격대·키워드를 확정적으로 알고 있으므로 LLM 추론 없이 직접 필터링한다.
    """
    conditions: list[dict[str, Any]] = []
    if seller_display:
        conditions.append({"seller": {"$eq": seller_display}})
    # min/max 가 기본 전체범위(0~999999)면 가격 필터는 사실상 무제한 → 그래도 안전하게 포함
    conditions.append({"product_price": {"$gte": int(min_price)}})
    conditions.append({"product_price": {"$lte": int(max_price)}})
    if ground_type:
        conditions.append({"ground_type": {"$eq": ground_type}})
    size_value: int | None = None
    if size and str(size).strip().isdigit():
        size_value = int(size)
        # size_min/size_max 는 상품의 전체 사이즈 범위라 사이 값이 비어 있어도(예: 245/270만
        # 판매) 통과할 수 있다 — 아래 size_matches()가 size_text 콤마 목록으로 정확히 재확인한다.
        conditions.append({"size_min": {"$lte": size_value}})
        conditions.append({"size_max": {"$gte": size_value}})

    where: dict[str, Any] = {"$and": conditions} if len(conditions) > 1 else conditions[0]

    # 후속 질문("다른 건 없어?")으로 이미 보여준 제품을 제외할 때, 제외분만큼 후보를 더 끌어와
    # 새 후보가 limit 만큼 남도록 k 를 비례 확대한다. (similarity_search 는 결정론적이라
    # k 만 넓히고 제외하지 않으면 같은 상위 prefix 가 반복된다.)
    candidate_count = limit + len(exclude_keys or ())
    try:
        raw_docs = vectorstore.similarity_search(
            product_keyword or "축구화", k=max(candidate_count * 5, 20), filter=where
        )
    except Exception as exc:
        raise RagRetrievalError("Chroma retrieval did not complete.") from exc

    tokens = _keyword_tokens(product_keyword)

    def name_matches(doc: Document) -> bool:
        if not tokens:
            return True
        name = str(doc.metadata.get("product_name") or "").replace(" ", "")
        return all(token.replace(" ", "") in name for token in tokens)

    def size_matches(doc: Document) -> bool:
        if size_value is None:
            return True
        available = {part.strip() for part in str(doc.metadata.get("size_text") or "").split(",")}
        return str(size_value) in available

    seen_keys: set[str] = set()
    unique_docs: list[Document] = []
    for doc in raw_docs:
        if not name_matches(doc) or not size_matches(doc):
            continue
        # 이미 보여준 제품 제외(턴 간 추적). 카드/병합 dedup 과 동일한 (seller, name) 복합 키 사용.
        if exclude_keys:
            seller = str(doc.metadata.get("seller") or "").strip()
            name = str(doc.metadata.get("product_name") or "").strip()
            if f"{seller}|{name}" in exclude_keys:
                continue
        key = (
            doc.metadata.get("product_url")
            or doc.metadata.get("product_name")
            or doc.page_content
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_docs.append(doc)
        if len(unique_docs) >= limit:
            break

    return unique_docs


def _format_price_text(price: Any) -> str | None:
    digits = re.sub(r"[^\d]", "", str(price or ""))
    if not digits:
        return None

    amount = int(digits)
    if amount <= 0:
        return None

    return f"{amount:,}원"


def _format_size_text(size_text: Any) -> str | None:
    if not size_text:
        return None

    parts = [part.strip() for part in str(size_text).split(",") if part.strip()]
    return ", ".join(parts) if parts else None


def _clean_product_url(url: Any) -> str | None:
    """저장된 URL을 정리:
    1) EUC-KR 검색 파라미터가 깨진 채 들어간 경우 ASCII-only key=value 만 유지.
    2) 빈 value 파라미터(`sort=`) 제거.
    3) 레드사커 `/shopdetail.html` 경로는 정답 `/shop/shopdetail.html` 로 교정 (기존 인덱스 보호).
    """
    if not url:
        return None
    raw = str(url).strip()
    if not raw:
        return None

    # 레드사커: 크롤 시 /shop/ 누락된 채 저장된 기존 데이터 fix
    if "redsoccer.co.kr/shopdetail.html" in raw and "redsoccer.co.kr/shop/shopdetail.html" not in raw:
        raw = raw.replace("redsoccer.co.kr/shopdetail.html", "redsoccer.co.kr/shop/shopdetail.html")

    if "?" not in raw:
        return raw
    base, _, query = raw.partition("?")
    kept: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        key, eq, value = pair.partition("=")
        if not key or not eq or not value:
            continue
        if all(ord(c) < 128 for c in key) and all(ord(c) < 128 for c in value):
            kept.append(f"{key}={value}")
    return f"{base}?{'&'.join(kept)}" if kept else base


def _build_default_features(metadata: dict[str, Any]) -> list[str]:
    features: list[str] = []

    ground_type = str(metadata.get("ground_type") or "").strip().upper()
    if ground_type and ground_type != "UNKNOWN":
        features.append(f"{ground_type} 지면에 적합")

    age_group = str(metadata.get("age_group") or "").strip()
    if age_group:
        features.append(f"{age_group}용 모델")

    product_category = str(metadata.get("product_category") or "").strip()
    if product_category:
        features.append(f"{product_category} 카테고리")

    return features


def build_analysis_cards_from_docs(
    docs: list[Document], limit: int = 5
) -> list[dict[str, Any]]:
    """RAG 문서를 카드로 변환한다.

    `limit`은 전체 카드 개수가 아니라 "판매처당 최대 개수"다 — 예전엔 병합된 docs 순서(라운드로빈
    인터리빙)에서 앞에서부터 limit개만 자르는 전역 제한이라, 판매처마다 남은 후보 수가 다르면 그
    절단선 안에서도 특정 판매처 카드가 몰리거나 다른 판매처가 아예 안 보이는 경우가 있었다(카드가
    판매처별로 묶이지 않고 뒤섞여 보이던 원인). 판매처별로 캡을 걸고, 첫 등장 순서대로 판매처를 묶어
    반환한다.
    """
    # (seller, product_name) 기준 중복 제거 — 같은 셀러가 색상/옵션 URL 다르게 노출하는 경우 대응
    seen: set[tuple[str, str]] = set()
    cards_by_seller: dict[str, list[dict[str, Any]]] = {}
    seller_order: list[str] = []

    for doc in docs:
        metadata = doc.metadata
        name = metadata.get("product_name") or "상품 정보 없음"
        seller = metadata.get("seller") or ""
        key = (str(seller).strip(), str(name).strip())
        if key in seen:
            continue
        bucket = cards_by_seller.setdefault(seller, [])
        if len(bucket) >= limit:
            continue
        seen.add(key)
        if seller not in seller_order:
            seller_order.append(seller)
        bucket.append(
            {
                "name": name,
                "seller": seller or None,
                "price": _format_price_text(metadata.get("product_price")),
                "size": _format_size_text(metadata.get("size_text")),
                "features": _build_default_features(metadata),
                "image": metadata.get("image_url") or None,
                "url": _clean_product_url(metadata.get("product_url")),
            }
        )

    return [card for seller in seller_order for card in cards_by_seller[seller]]


def format_docs(docs: list[Document]) -> str:
    items = []
    for doc in docs:
        item = doc.page_content
        if url := doc.metadata.get("product_url", ""):
            item += f"\n상품 URL: {url}"
        if image := doc.metadata.get("image_url", ""):
            item += f"\n이미지 URL: {image}"
        items.append(item)
    return "\n\n".join(items)


# ── CRAG grading / Self-RAG groundedness (product_analysis_agent 전용) ──────
class _DocRelevance(BaseModel):
    relevant_indices: list[int] = Field(
        description="질문에 실제로 답이 되는 문서의 0-based 인덱스 목록"
    )


async def grade_docs_relevance(query: str, docs: list[Document]) -> list[Document]:
    """CRAG 스타일: 생성 전에 검색된 문서가 질문과 실제로 관련 있는지 채점."""
    if not docs:
        return []
    summary = "\n".join(
        f"{i}: {doc.metadata.get('product_name', '')} / {doc.metadata.get('seller', '')} / {doc.page_content[:150]}"
        for i, doc in enumerate(docs)
    )
    grader = model.with_structured_output(_DocRelevance)
    result = await grader.ainvoke(
        f"질문: {query}\n\n문서 목록:\n{summary}\n\n질문에 실제로 답이 되는 문서의 인덱스만 골라주세요."
    )
    return [docs[i] for i in result.relevant_indices if 0 <= i < len(docs)]


async def rewrite_analysis_query(query: str, conditions: dict[str, Any] | None = None) -> str:
    """CRAG 스타일: 관련 문서가 하나도 없을 때 재검색용으로 질문을 넓혀 재작성."""
    condition_text = ", ".join(f"{k}={v}" for k, v in (conditions or {}).items() if v)
    rewriter = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "검색 결과가 없었던 축구화 쇼핑 질문을, 조건(브랜드/가격/지면 등)은 유지하되 "
                    "더 넓은 검색어로 한국어 1줄로 재작성하세요. 설명 없이 재작성된 질문만 출력하세요.",
                ),
                ("human", "질문: {query}\n기존 조건: {conditions}"),
            ]
        )
        | model
        | StrOutputParser()
    )
    result = await rewriter.ainvoke(
        {"query": query, "conditions": condition_text or "없음"}
    )
    return result.strip()


class _Groundedness(BaseModel):
    grounded: bool = Field(
        description="답변의 가격/스펙 등 핵심 주장이 문서 내용에 실제로 있으면 true"
    )


async def grade_answer_groundedness(answer: str, docs: list[Document]) -> bool:
    """Self-RAG 스타일: 생성된 답변이 실제로 문서에 근거하는지(hallucination 여부) 채점."""
    if not docs:
        return True
    checker = model.with_structured_output(_Groundedness)
    result = await checker.ainvoke(
        f"문서:\n{format_docs(docs)}\n\n답변:\n{answer}\n\n"
        "답변에 나온 가격/스펙 등 핵심 주장이 문서에 실제로 있는지 확인하세요."
    )
    return result.grounded


async def _generate_answer(context: str, messages: list) -> str:
    gen_prompt = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """You are a soccer shoe recommendation assistant.
Context에 있는 정보만 사용해 답변하세요.

## Product Context
{context}

## Output Format
- Context에 있는 **모든 제품**을 Markdown table로 표시하세요.
- 표 컬럼: 판매처 | 상품명 | 가격 | 사이즈 | 주요 특징 | 이미지 | 링크
- 가격: ₩ 단위
- 사이즈: size_text에 있는 전체 사이즈 목록 표시. 사용자가 요청한 사이즈가 포함되면 **굵게** 강조
- 주요 특징: ground_type 해석 + age_group + 기능 키워드 2개↑
- 이미지: ![이미지](이미지URL)
- 링크: [🔗 제품 상세보기](상품URL)
- Context가 완전히 비어있을 때만: "요청하신 조건에 부합하는 축구화 정보를 찾을 수 없습니다."
- 절대 임의로 정보 생성 금지""",
                ),
                MessagesPlaceholder("messages"),
            ]
        )
        | model
        | StrOutputParser()
    )
    return await gen_prompt.ainvoke({"context": context, "messages": messages})
