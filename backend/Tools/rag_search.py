"""
rag_search.py
=============
test_0312.ipynb의 LangGraph를 .py로 분리한 파일.

- vectorstore: crawl_and_index 도구와 공유하는 Chroma 인스턴스
- rag_search : LangGraph(graph)를 호출하는 LangChain Tool
"""

import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Any, Literal

from dotenv import load_dotenv
from langchain_classic.chains.query_constructor.base import (
    StructuredQueryOutputParser,
    get_query_constructor_prompt,
)
from langchain_classic.chains.query_constructor.schema import AttributeInfo
from langchain_classic.retrievers.self_query.base import SelfQueryRetriever
from langchain_community.query_constructors.chroma import ChromaTranslator
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

try:
    from Tools.seller_normalization import (
        find_seller_displays_in_query,
        replace_seller_aliases_in_query,
    )
except ImportError:
    from seller_normalization import (
        find_seller_displays_in_query,
        replace_seller_aliases_in_query,
    )

load_dotenv()

# ── 모델 & 임베딩 ───────────────────────────────────────────
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ── Shared Vectorstore (crawl_and_index 도구가 upsert, graph가 검색) ──
# singleton 모듈에서 가져와 import 경로 차이로 인한 인스턴스 분리 방지
try:
    from Tools.vectorstore_singleton import vectorstore
except ImportError:
    from vectorstore_singleton import vectorstore

# ── SelfQueryRetriever 설정 ─────────────────────────────────
metadata_info = [
    AttributeInfo(name="seller", description="제품 판매처명", type="string"),
    AttributeInfo(
        name="product_price", description="판매 가격 (원 단위 정수)", type="integer"
    ),
    AttributeInfo(
        name="product_category", description="축구화 또는 풋살화", type="string"
    ),
    AttributeInfo(name="age_group", description="성인용 또는 유소년용", type="string"),
    AttributeInfo(
        name="ground_type", description="FG, AG, HG, TF 등 지면 종류", type="string"
    ),
]

query_constructor = (
    get_query_constructor_prompt(
        """
        여러 판매처에서 수집한 축구화 제품 문서
        1. 가격 표현 해석:
           - 10만원대 = 100000 이상 200000 미만
           - 10만원 이상 = 100000 이상
           - 10만원 이하 = 100000 이하
        2. 카테고리: 축구화 or 풋살화
        """,
        metadata_info,
    )
    | model
    | StructuredQueryOutputParser.from_components()
)

retriever = SelfQueryRetriever(
    query_constructor=query_constructor,
    vectorstore=vectorstore,
    structured_query_translator=ChromaTranslator(),
)

# ── 판매자 키워드 & 병렬 검색 ───────────────────────────────
SELLER_KEYWORDS = {
    "크레이지11": "크레이지11",
    "크레이지 11": "크레이지11",
    "crazy11": "크레이지11",
    "사커붐": "사커붐",
    "soccerboom": "사커붐",
    "레드사커": "레드사커",
    "redsoccer": "레드사커",
    "카포스토어": "카포스토어",
    "cafostore": "카포스토어",
}


def extract_sellers_from_query(query: str) -> list[str]:
    found = []
    for keyword, seller in SELLER_KEYWORDS.items():
        if keyword in query and seller not in found:
            found.append(seller)
    return found


def parallel_retrieve(query: str) -> list[Document]:
    sellers = extract_sellers_from_query(query)
    if len(sellers) <= 1:
        return retriever.invoke(query)

    def search_per_seller(seller: str) -> list[Document]:
        sub_query = f"{seller}에서 " + re.sub(
            r"([\w가-힣]+(?:과|와|,)\s*)+[\w가-힣]+에서\s*", "", query
        )
        return retriever.invoke(sub_query)

    seen_ids: set[str] = set()
    results: list[Document] = []
    with ThreadPoolExecutor(max_workers=len(sellers)) as executor:
        futures = {executor.submit(search_per_seller, s): s for s in sellers}
        for future in as_completed(futures):
            for doc in future.result():
                key = doc.metadata.get("product_url", doc.id or "")
                if key not in seen_ids:
                    seen_ids.add(key)
                    results.append(doc)
    return results


def extract_sellers_from_query(query: str) -> list[str]:
    return find_seller_displays_in_query(query)


def parallel_retrieve(query: str) -> list[Document]:
    normalized_query = replace_seller_aliases_in_query(query)
    sellers = find_seller_displays_in_query(normalized_query)
    if len(sellers) <= 1:
        return retriever.invoke(normalized_query)

    def search_per_seller(seller: str) -> list[Document]:
        sub_query = f"{seller}에서 " + re.sub(
            r"([\w가-힣]+(?:과|와|,)\s*)+[\w가-힣]+\s*에서\s*",
            "",
            normalized_query,
        )
        return retriever.invoke(sub_query)

    seen_ids: set[str] = set()
    results: list[Document] = []
    with ThreadPoolExecutor(max_workers=len(sellers)) as executor:
        futures = {executor.submit(search_per_seller, s): s for s in sellers}
        for future in as_completed(futures):
            for doc in future.result():
                key = doc.metadata.get("product_url", doc.id or "")
                if key not in seen_ids:
                    seen_ids.add(key)
                    results.append(doc)
    return results


def retrieve_analysis_documents(query: str, limit: int = 5) -> list[Document]:
    try:
        docs = parallel_retrieve(query)
    except Exception:
        docs = []

    if not docs:
        docs = vectorstore.similarity_search(query, k=limit)

    seen_keys: set[str] = set()
    unique_docs: list[Document] = []
    for doc in docs:
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


def retrieve_analysis_documents(query: str, limit: int = 5) -> list[Document]:
    normalized_query = replace_seller_aliases_in_query(query)

    try:
        docs = parallel_retrieve(normalized_query)
    except Exception:
        docs = []

    if not docs:
        docs = vectorstore.similarity_search(normalized_query, k=limit)

    seen_keys: set[str] = set()
    unique_docs: list[Document] = []
    for doc in docs:
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


def build_analysis_cards(query: str, limit: int = 5) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    for doc in retrieve_analysis_documents(query, limit=limit):
        metadata = doc.metadata
        cards.append(
            {
                "name": metadata.get("product_name") or "상품 정보 없음",
                "seller": metadata.get("seller") or None,
                "price": _format_price_text(metadata.get("product_price")),
                "size": _format_size_text(metadata.get("size_text")),
                "features": _build_default_features(metadata),
                "image": metadata.get("image_url") or None,
                "url": metadata.get("product_url") or None,
            }
        )

    return cards


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


# ── LangGraph ───────────────────────────────────────────────
class State(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    refined_query: str
    context: str
    doc_grade: str


def classify_intent(state: State) -> dict:
    last_msg = state["messages"][-1].content
    history = state["messages"][:-1]

    classifier = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """사용자 메시지의 의도를 분류하세요. 반드시 아래 중 하나만 출력하세요.
- search   : 축구화/풋살화 신규 검색 요청
- refine   : 이전 검색 결과에 조건 변경/추가 요청
- chitchat : 검색과 무관한 대화

의도만 출력하세요. 설명 없이.""",
                ),
                MessagesPlaceholder("history"),
                ("human", "{question}"),
            ]
        )
        | model
        | StrOutputParser()
    )

    intent = (
        classifier.invoke({"history": history, "question": last_msg}).strip().lower()
    )
    if intent not in ("search", "refine", "chitchat"):
        intent = "search"
    return {"intent": intent}


def rewrite_query(state: State) -> dict:
    last_msg = state["messages"][-1].content
    if state["intent"] == "search":
        return {"refined_query": last_msg}

    rewriter = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """당신은 검색 쿼리 최적화 전문가입니다.
대화 히스토리에서 기존 검색 조건을 파악하고, 사용자의 새 요청을 반영해
완전한 단일 검색 쿼리로 재작성하세요.
규칙: 이전 조건 유지, 변경된 조건만 업데이트, 한국어 1줄만 출력.""",
                ),
                MessagesPlaceholder("history"),
                ("human", "새 요청: {question}"),
            ]
        )
        | model
        | StrOutputParser()
    )

    refined = rewriter.invoke({"history": state["messages"][:-1], "question": last_msg})
    return {"refined_query": refined.strip()}


def retrieve_node(state: State) -> dict:
    try:
        docs = parallel_retrieve(state["refined_query"])
    except Exception:
        docs = []
    if not docs:
        docs = vectorstore.similarity_search(state["refined_query"], k=4)
    return {"context": format_docs(docs)}


def retrieve_node(state: State) -> dict:
    normalized_query = replace_seller_aliases_in_query(state["refined_query"])
    try:
        docs = parallel_retrieve(normalized_query)
    except Exception:
        docs = []
    if not docs:
        docs = vectorstore.similarity_search(normalized_query, k=4)
    return {"context": format_docs(docs)}


def grade_docs(state: State) -> dict:
    grade = "relevant" if state["context"].strip() else "irrelevant"
    return {"doc_grade": grade}


def generate_node(state: State) -> dict:
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
    answer = gen_prompt.invoke(
        {"context": state["context"], "messages": state["messages"]}
    )
    return {"messages": [AIMessage(content=answer)]}


def respond_directly(state: State) -> dict:
    resp = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "당신은 축구화 쇼핑 어시스턴트입니다. 친절하게 응답하고, 자연스럽게 축구화 검색으로 유도하세요.",
                ),
                MessagesPlaceholder("messages"),
            ]
        )
        | model
        | StrOutputParser()
    )
    answer = resp.invoke({"messages": state["messages"]})
    return {"messages": [AIMessage(content=answer)]}


def ask_clarification(state: State) -> dict:
    answer = (
        f"죄송합니다. **'{state['refined_query']}'** 조건으로는 적합한 제품을 찾지 못했습니다.\n\n"
        "아래 조건을 조정해보시겠어요?\n"
        "- 💰 가격대 변경\n- 👟 사이즈 범위 확대\n- 🏪 판매처 추가\n- ⚽ 지면 종류 변경 (FG/AG/TF)"
    )
    return {"messages": [AIMessage(content=answer)]}


def route_by_intent(state: State) -> Literal["rewrite_query", "respond_directly"]:
    return (
        "rewrite_query"
        if state["intent"] in ("search", "refine")
        else "respond_directly"
    )


def route_by_grade(state: State) -> Literal["generate", "ask_clarification"]:
    return "generate" if state["doc_grade"] == "relevant" else "ask_clarification"


# ── Graph 빌드 ─────────────────────────────────────────────
builder = StateGraph(State)
builder.add_node("classify_intent", classify_intent)
builder.add_node("rewrite_query", rewrite_query)
builder.add_node("retrieve", retrieve_node)
builder.add_node("grade_docs", grade_docs)
builder.add_node("generate", generate_node)
builder.add_node("respond_directly", respond_directly)
builder.add_node("ask_clarification", ask_clarification)

builder.add_edge(START, "classify_intent")
builder.add_conditional_edges("classify_intent", route_by_intent)
builder.add_edge("rewrite_query", "retrieve")
builder.add_edge("retrieve", "grade_docs")
builder.add_conditional_edges("grade_docs", route_by_grade)
builder.add_edge("generate", END)
builder.add_edge("respond_directly", END)
builder.add_edge("ask_clarification", END)

memory = MemorySaver()
graph = builder.compile(checkpointer=memory)


# ── Tool 정의 ───────────────────────────────────────────────
@tool
async def rag_search(query: str) -> str:
    """
    인덱싱된 축구화 데이터에서 사용자 쿼리에 맞는 제품을 검색하고 비교표를 생성합니다.
    반드시 crawl_and_index 호출 이후에 사용하세요.

    Args:
        query: 사용자 검색 쿼리 원문
    """
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=query)]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    import asyncio

    async def test():
        # 테스트: 벡터스토어가 비어있으므로 ask_clarification 응답 예상
        result = await rag_search.ainvoke(
            {"query": "사커붐에서 머큐리얼 FG 성인용 추천해줘"}
        )
        print(result)

    asyncio.run(test())
