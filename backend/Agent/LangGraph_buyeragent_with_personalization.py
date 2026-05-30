from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langmem import create_memory_store_manager
from pydantic import BaseModel, Field

from Agent.product_analysis_agent import product_analysis_agent
from Agent.sub_agent_0310 import product_search_agent, seller_search_agent
from State.AgentState_personalization import BuyerAgentStateV2, SearchResultItem, UserProfile
from Tools.checkout_adapter import (
    SUPPORTED_CHECKOUT_SELLERS,
    build_checkout_session_payload,
    get_checkout_adapter,
)
from Tools.condition_sanitization import sanitize_condition_map, sanitize_optional_text
from Tools.rag_search import build_analysis_cards
from Tools.seller_normalization import normalize_seller_display

load_dotenv()

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

_CONDITION_QUESTIONS: dict[str, dict] = {
    "budget": {
        "question": "예산대를 알려주세요.",
        "options": ["10만원 이하", "20만원 이하", "30만원 이하", "30만원 초과"],
    },
    "surface": {
        "question": "주로 어떤 구장에서 신으시나요?",
        "options": ["천연잔디(FG)", "인조잔디(AG/TF)", "실내화(IC/IN)", "상관없음"],
    },
    "brand": {
        "question": "선호 브랜드가 있나요?",
        "options": ["나이키", "아디다스", "푸마", "미즈노", "상관없음"],
    },
    "position": {
        "question": "주 포지션을 알려주세요.",
        "options": ["공격수", "미드필더", "수비수", "골키퍼", "상관없음"],
    },
}
_CONDITION_PRIORITY = ["budget", "surface", "brand", "position"]
_PURCHASE_REQUIRED_FIELDS = [
    "size",
    "recipient_name",
    "phone",
    "address",
    "detail_address",
]


class ExtractedConditions(BaseModel):
    brand: str | None = Field(None)
    budget: str | None = Field(None)
    surface: str | None = Field(None)
    position: str | None = Field(None)
    age_group: str | None = Field(None)
    product_name: str | None = Field(None)
    seller: str | None = Field(None)


class ExtractionResult(BaseModel):
    intent: Literal["product_search", "seller_search", "product_analysis", "chitchat"]
    conditions: ExtractedConditions


class ProductItem(BaseModel):
    name: str
    features: str | None = None
    recommendation: str | None = None
    price: str | None = None
    url: str | None = None


class ParsedProducts(BaseModel):
    products: list[ProductItem]


class SellerItem(BaseModel):
    name: str
    description: str | None = None
    why_recommended: str | None = None  # 이 판매처를 추천하는 이유
    url: str | None = None


class ParsedSellers(BaseModel):
    sellers: list[SellerItem]


class AnalysisItem(BaseModel):
    name: str
    seller: str | None = None
    price: str | None = None
    size: str | None = None
    image: str | None = None
    url: str | None = None


class ParsedAnalysis(BaseModel):
    analysis: list[AnalysisItem]


class PurchaseExtractionResult(BaseModel):
    product_index: int | None = None
    product_name: str | None = None
    product_url: str | None = None
    size: str | None = None
    recipient_name: str | None = None
    phone: str | None = None
    address: str | None = None
    detail_address: str | None = None


_products_parser = llm.with_structured_output(ParsedProducts)
_sellers_parser = llm.with_structured_output(ParsedSellers)
_analysis_parser = llm.with_structured_output(ParsedAnalysis)
_purchase_parser = llm.with_structured_output(PurchaseExtractionResult)

profile_manager = create_memory_store_manager(
    "openai:gpt-4o-mini",
    namespace=("users", "{user_id}", "profile"),
    schemas=[UserProfile],
    enable_inserts=False,
)


def _extract_profile_content(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw.get("content", raw)
    return {}


def _normalize_profile(profile: dict) -> dict:
    normalized = dict(profile or {})
    for key in ["brand", "budget", "surface", "position", "age_group", "product_name", "seller"]:
        value = sanitize_optional_text(normalized.get(key))
        if value is None:
            normalized.pop(key, None)
        else:
            normalized[key] = value
    return normalized


async def load_user_memory(state: BuyerAgentStateV2, store: BaseStore) -> dict:
    if state.get("user_profile") is not None:
        return {}

    namespace = ("users", state["user_id"], "profile")
    results = await store.asearch(namespace)
    profile = _normalize_profile(_extract_profile_content(results[0].value) if results else {})
    profile_as_conditions = {
        key: profile[key]
        for key in ["brand", "budget", "surface", "position", "age_group", "product_name", "seller"]
        if profile.get(key)
    }
    merged_conditions = {**profile_as_conditions, **sanitize_condition_map(state.get("user_conditions", {}))}
    return {"user_profile": profile, "user_conditions": merged_conditions}


def _message_contains_purchase_pii(text: str) -> bool:
    normalized = str(text or "")
    return bool(
        re.search(r"\d{2,4}-?\d{3,4}-?\d{4}", normalized)
        or any(keyword in normalized for keyword in ["주소", "상세주소", "배송지", "받는", "수령인"])
    )


def _sanitize_messages_for_memory(messages: list) -> list:
    sanitized = []
    for message in messages:
        if isinstance(message, HumanMessage) and _message_contains_purchase_pii(str(message.content)):
            sanitized.append(HumanMessage(content="[purchase pii omitted]"))
        else:
            sanitized.append(message)
    return sanitized


async def save_user_memory(state: BuyerAgentStateV2, store: BaseStore) -> dict:
    try:
        await profile_manager.ainvoke(
            {"messages": _sanitize_messages_for_memory(state.get("messages", []))},
            config={"configurable": {"user_id": state["user_id"]}, "store": store},
        )
        namespace = ("users", state["user_id"], "profile")
        results = await store.asearch(namespace)
        if results:
            return {"user_profile": _normalize_profile(_extract_profile_content(results[0].value))}
    except Exception:
        return {}
    return {}


def _last_user_message(state: BuyerAgentStateV2) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content).strip()
    return ""


def _looks_like_purchase_intent(message: str) -> bool:
    patterns = [
        r"이걸로\s*살게",
        r"이거로\s*살게",
        r"구매해줘",
        r"주문해줘",
        r"결제\s*직전",
        r"주문\s*진행",
        r"살게",
    ]
    return any(re.search(pattern, message) for pattern in patterns)


def _should_continue_purchase(state: BuyerAgentStateV2, message: str) -> bool:
    return state.get("purchase_status") in {"awaiting_product_selection", "awaiting_purchase_info"}


async def extract_conditions_and_intent(state: BuyerAgentStateV2) -> dict:
    previous_intent = state.get("intent", "")
    user_profile = _normalize_profile(dict(state.get("user_profile") or {}))
    structured_items = [f"{k}: {user_profile[k]}" for k in user_profile if user_profile.get(k)]

    system_prompt = (
        "You are a Korean shopping intent classifier for soccer shoes.\n"
        f"Current intent: {previous_intent or 'none'}\n"
        f"Known profile: {', '.join(structured_items) if structured_items else 'none'}\n"
        "Classify intent as one of product_search, seller_search, product_analysis, chitchat.\n"
        "Extract only conditions explicitly stated in the latest user request."
    )
    extractor = llm.with_structured_output(ExtractionResult)
    result: ExtractionResult = await extractor.ainvoke(
        [SystemMessage(content=system_prompt)] + state["messages"]
    )

    new_conditions = sanitize_condition_map(result.conditions.model_dump())
    updated_conditions = sanitize_condition_map({**state.get("user_conditions", {}), **new_conditions})
    latest = _last_user_message(state)
    intent = result.intent
    if _looks_like_purchase_intent(latest) or _should_continue_purchase(state, latest):
        intent = "purchase_prepare"

    return {
        "intent": intent,
        "user_profile": user_profile,
        "user_conditions": updated_conditions,
        "status": "checking",
    }


def check_conditions(state: BuyerAgentStateV2) -> dict:
    intent = state["intent"]
    conditions = state.get("user_conditions", {})
    search_result = state.get("search_result", [])
    missing = []

    if intent == "product_search":
        if not conditions:
            missing.append("brand, budget, surface 중 하나 이상")
    elif intent == "seller_search":
        if not (search_result or conditions.get("product_name")):
            missing.append("상품명 또는 이전 검색 결과")
    elif intent == "product_analysis":
        if not (search_result or conditions.get("product_name")):
            missing.append("비교할 상품명 또는 이전 검색 결과")

    return {
        "missing_conditions": missing,
        "status": "waiting_input" if missing else "responding",
    }


def route_after_check(state: BuyerAgentStateV2) -> str:
    if state["missing_conditions"]:
        return "ask_missing_node"
    return {
        "product_search": "product_search_node",
        "seller_search": "seller_search_node",
        "product_analysis": "product_analysis_node",
        "purchase_prepare": "purchase_prepare_node",
        "chitchat": "chitchat_node",
    }.get(state["intent"], "chitchat_node")


def ask_missing_node(state: BuyerAgentStateV2) -> dict:
    if state.get("intent") == "product_search":
        conditions = state.get("user_conditions", {})
        remaining = [key for key in _CONDITION_PRIORITY if key not in conditions]
        if remaining:
            sequence = [
                {
                    "key": key,
                    "question": _CONDITION_QUESTIONS[key]["question"],
                    "options": _CONDITION_QUESTIONS[key]["options"],
                }
                for key in remaining
            ]
            first = sequence[0]
            return {
                "messages": [AIMessage(content=first["question"])],
                "status": "waiting_input",
                "question_options": first["options"],
                "question_sequence": sequence,
            }

    missing = ", ".join(state.get("missing_conditions", []))
    return {
        "messages": [AIMessage(content=f"추가로 필요한 정보가 있어요: {missing}")],
        "status": "waiting_input",
        "question_options": None,
        "question_sequence": None,
    }


async def _parse_products(text: str) -> list[dict] | None:
    try:
        result: ParsedProducts = await _products_parser.ainvoke(
            [
                SystemMessage(content=(
                    "Extract recommended football shoe SERIES/MODEL cards from the text. "
                    "Each card must represent a series or model line (e.g. '나이키 머큐리얼 베이퍼 시리즈'), "
                    "NOT individual SKUs, specific colorways, or size variants. "
                    "The 'name' field must be a series/model name only — strip out any size numbers, "
                    "edition suffixes, or colorway names."
                )),
                HumanMessage(content=text),
            ]
        )
        return [item.model_dump() for item in result.products]
    except Exception:
        return None


async def _parse_sellers(text: str) -> list[dict] | None:
    try:
        # reasoning 섹션 제외 — "추천 목록" 이후 텍스트만 파싱해 중복 방지
        list_section = text
        marker_idx = text.find("추천 목록")
        if marker_idx != -1:
            list_section = text[marker_idx:]

        result: ParsedSellers = await _sellers_parser.ainvoke(
            [
                SystemMessage(content=(
                    "Extract seller cards from the '추천 목록' section only. "
                    "Each numbered entry is one seller. "
                    "Fields: name (판매처 이름), description (설명 field content), "
                    "why_recommended (추천 이유 field content), url (링크 field URL). "
                    "Each seller name must appear EXACTLY ONCE — "
                    "if the same name appears multiple times, keep only the first occurrence."
                )),
                HumanMessage(content=list_section),
            ]
        )
        # 파싱 결과 name 기준 중복 제거
        seen: set[str] = set()
        unique: list[dict] = []
        for item in result.sellers:
            key = item.name.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(item.model_dump())
        return unique or None
    except Exception:
        return None


async def _parse_analysis(text: str) -> list[dict] | None:
    try:
        result: ParsedAnalysis = await _analysis_parser.ainvoke(
            [
                SystemMessage(
                    content="Extract product analysis cards with seller, price, size and url from the text."
                ),
                HumanMessage(content=text),
            ]
        )
        return [item.model_dump() for item in result.analysis]
    except Exception:
        return None


def _normalize_purchase_product(item: dict | None) -> dict | None:
    if not item:
        return None
    product_url = sanitize_optional_text(item.get("url") or item.get("product_url"))
    if not product_url:
        return None
    return {
        "product_key": product_url,
        "product_url": product_url,
        "url": product_url,
        "name": sanitize_optional_text(item.get("name")),
        "seller": normalize_seller_display(item.get("seller", "")) or None,
        "price": sanitize_optional_text(item.get("price")),
        "size": sanitize_optional_text(item.get("size")),
        "available_size": sanitize_optional_text(item.get("size") or item.get("available_size")),
        "selected_size": sanitize_optional_text(item.get("selected_size")),
        "quantity": 1,
    }


def _normalize_analysis_key(value: str | None) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").lower())


async def product_search_node(state: BuyerAgentStateV2) -> dict:
    conditions = state.get("user_conditions", {})
    query_parts = [
        conditions[key]
        for key in ["brand", "budget", "surface", "position", "age_group", "product_name"]
        if conditions.get(key)
    ]
    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 축구화 추천"
    response = await product_search_agent(query, user_profile=state.get("user_profile") or {})
    products = await _parse_products(response)
    return {
        "messages": [AIMessage(content=response)],
        "search_result": [
            {
                "name": conditions.get("product_name", base),
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_search",
            }
        ],
        "products": products,
        "active_agent": "product_search",
        "status": "done",
        "retry_count": 0,
        "error": None,
    }


async def seller_search_node(state: BuyerAgentStateV2) -> dict:
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})
    if state.get("active_agent") == "product_search" and search_result:
        base = search_result[0].get("name", "")
    else:
        base = conditions.get("product_name") or conditions.get("brand") or "축구화"
    query = f"{base} 판매처 추천"
    response = await seller_search_agent(query, user_profile=state.get("user_profile") or {})
    sellers = await _parse_sellers(response)

    # 안전망: regex 정규화 기반 2차 중복 제거
    if sellers:
        seen: set[str] = set()
        deduped: list[dict] = []
        for s in sellers:
            key = re.sub(r"[\W_]+", "", str(s.get("name", "")).lower())
            if key and key not in seen:
                seen.add(key)
                deduped.append(s)
        sellers = deduped or None

    return {
        "messages": [AIMessage(content=response)],
        "search_result": [
            {"name": query, "description": response, "price": "", "url": "", "source": "seller_search"}
        ],
        "sellers": sellers,
        "active_agent": "seller_search",
        "status": "done",
        "retry_count": 0,
        "error": None,
    }


async def product_analysis_node(state: BuyerAgentStateV2) -> dict:
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})
    query_parts = []
    if conditions.get("seller"):
        query_parts.append(f"{normalize_seller_display(conditions['seller'])}에서")
    product_name = conditions.get("product_name")
    if not product_name and state.get("active_agent") == "product_search" and search_result:
        product_name = search_result[0].get("name", "")
    if product_name:
        query_parts.append(product_name)
    for key in ["brand", "budget", "age_group", "surface", "position"]:
        if conditions.get(key) and conditions.get(key) not in query_parts:
            query_parts.append(conditions[key])
    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 비교 분석"
    response = await product_analysis_agent(query, user_profile=state.get("user_profile") or {})
    # ChromaDB에서 직접 이미지 URL 포함 구조화 데이터 추출 (crawl_and_index 이후 최신 데이터 보장)
    analysis = build_analysis_cards(base, limit=5)
    if not analysis:
        # fallback: LLM 텍스트 파싱 방식
        analysis = [_normalize_purchase_product(item) or item for item in (await _parse_analysis(response) or [])]
    return {
        "messages": [AIMessage(content=response)],
        "search_result": [
            {
                "name": product_name or base,
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_analysis",
            }
        ],
        "analysis": analysis or None,
        "selected_product": None,
        "purchase_status": None,
        "purchase_missing_fields": [],
        "shipping_info": None,
        "checkout_session": None,
        "active_agent": "product_analysis",
        "status": "done",
        "retry_count": 0,
        "error": None,
    }


async def _extract_purchase_fields(message: str, analysis: list[dict] | None) -> PurchaseExtractionResult:
    product_lines = [
        f"{idx}. {item.get('name')} / seller={item.get('seller')} / url={item.get('product_url') or item.get('url')}"
        for idx, item in enumerate(analysis or [], start=1)
    ]
    return await _purchase_parser.ainvoke(
        [
            SystemMessage(
                content=(
                    "Extract purchase preparation fields from the latest Korean user message. "
                    "Use product_index only when the user refers to first, second, nth item."
                )
            ),
            HumanMessage(content=f"[Products]\n{chr(10).join(product_lines)}\n\n[Message]\n{message}"),
        ]
    )


def _resolve_selected_product(
    analysis: list[dict] | None, existing: dict | None, extracted: PurchaseExtractionResult
) -> dict | None:
    normalized_existing = _normalize_purchase_product(existing)
    if normalized_existing:
        return normalized_existing
    items = analysis or []
    if extracted.product_url:
        for item in items:
            if (item.get("product_url") or item.get("url")) == extracted.product_url:
                return _normalize_purchase_product(item)
    if extracted.product_name:
        target = _normalize_analysis_key(extracted.product_name)
        for item in items:
            if _normalize_analysis_key(item.get("name")) == target:
                return _normalize_purchase_product(item)
    if extracted.product_index and 1 <= extracted.product_index <= len(items):
        return _normalize_purchase_product(items[extracted.product_index - 1])
    if len(items) == 1:
        return _normalize_purchase_product(items[0])
    return None


def _merge_shipping_info(existing: dict | None, extracted: PurchaseExtractionResult) -> dict:
    shipping_info = dict(existing or {})
    for key in ["recipient_name", "phone", "address", "detail_address"]:
        value = sanitize_optional_text(getattr(extracted, key))
        if value:
            shipping_info[key] = value
    return shipping_info


def _compute_purchase_missing_fields(selected_product: dict | None, shipping_info: dict | None) -> list[str]:
    if not selected_product:
        return ["selected_product"]
    missing = []
    if not sanitize_optional_text(selected_product.get("selected_size")):
        missing.append("size")
    shipping_info = shipping_info or {}
    for key in ["recipient_name", "phone", "address", "detail_address"]:
        if not sanitize_optional_text(shipping_info.get(key)):
            missing.append(key)
    return missing


def _purchase_followup_question(missing_fields: list[str], analysis: list[dict] | None) -> str:
    first = missing_fields[0]
    if first == "selected_product":
        options = "\n".join(
            f"{idx}. {item.get('name')}" for idx, item in enumerate(analysis or [], start=1)
        )
        return (
            "구매할 상품을 먼저 확정할게요. 몇 번째 상품으로 진행할지 알려주세요."
            if not options
            else f"구매할 상품을 먼저 확정할게요. 몇 번째 상품으로 진행할지 알려주세요.\n\n{options}"
        )
    prompts = {
        "size": "주문할 사이즈를 알려주세요.",
        "recipient_name": "받는 분 성함을 알려주세요.",
        "phone": "연락처를 알려주세요.",
        "address": "배송지 주소를 알려주세요.",
        "detail_address": "상세 주소를 알려주세요.",
    }
    return prompts[first]


async def purchase_prepare_node(state: BuyerAgentStateV2) -> dict:
    latest_message = _last_user_message(state)
    analysis = state.get("analysis") or []
    extracted = await _extract_purchase_fields(latest_message, analysis)
    selected_product = _resolve_selected_product(analysis, state.get("selected_product"), extracted)
    shipping_info = _merge_shipping_info(state.get("shipping_info"), extracted)

    if selected_product and sanitize_optional_text(extracted.size):
        selected_product["selected_size"] = sanitize_optional_text(extracted.size)

    missing_fields = _compute_purchase_missing_fields(selected_product, shipping_info)

    if "selected_product" in missing_fields and not analysis:
        return {
            "messages": [AIMessage(content="구매할 상품을 찾지 못했어요. 먼저 분석 결과에서 상품을 골라주세요.")],
            "active_agent": "purchase_prepare",
            "status": "waiting_input",
            "purchase_status": "awaiting_product_selection",
            "purchase_missing_fields": ["selected_product"],
            "selected_product": None,
            "shipping_info": shipping_info or None,
            "checkout_session": None,
        }

    if selected_product and not selected_product.get("product_url"):
        return {
            "messages": [AIMessage(content="선택한 상품에 product_url이 없어 주문 준비를 진행할 수 없어요.")],
            "active_agent": "purchase_prepare",
            "status": "error",
            "purchase_status": "missing_product_url",
            "purchase_missing_fields": ["selected_product"],
            "selected_product": selected_product,
            "shipping_info": shipping_info or None,
            "checkout_session": None,
            "error": "missing_product_url",
        }

    if selected_product and selected_product.get("seller") not in SUPPORTED_CHECKOUT_SELLERS:
        seller = selected_product.get("seller") or "선택한 판매처"
        return {
            "messages": [AIMessage(content=f"{seller} 판매처는 아직 자동 주문 준비를 지원하지 않아요.")],
            "active_agent": "purchase_prepare",
            "status": "done",
            "purchase_status": "unsupported_seller",
            "purchase_missing_fields": [],
            "selected_product": selected_product,
            "shipping_info": shipping_info or None,
            "checkout_session": None,
        }

    if missing_fields:
        return {
            "messages": [AIMessage(content=_purchase_followup_question(missing_fields, analysis))],
            "active_agent": "purchase_prepare",
            "status": "waiting_input",
            "purchase_status": (
                "awaiting_product_selection"
                if missing_fields[0] == "selected_product"
                else "awaiting_purchase_info"
            ),
            "purchase_missing_fields": missing_fields,
            "selected_product": selected_product,
            "shipping_info": shipping_info or None,
            "checkout_session": None,
        }

    adapter = get_checkout_adapter(selected_product["seller"])
    checkout_session = build_checkout_session_payload(
        adapter=adapter,
        selected_product=selected_product,
        shipping_info=shipping_info,
        session_id=state["session_id"],
        user_id=state["user_id"],
        session_token=str(uuid4()),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return {
        "messages": [
            AIMessage(
                content="주문 직전 단계까지 준비됐어요. 프론트에서 checkout_session으로 브라우저 자동화를 실행하면 됩니다."
            )
        ],
        "active_agent": "purchase_prepare",
        "status": "done",
        "purchase_status": "ready_for_checkout",
        "purchase_missing_fields": [],
        "selected_product": selected_product,
        "shipping_info": shipping_info,
        "checkout_session": checkout_session,
        "error": None,
    }


async def chitchat_node(state: BuyerAgentStateV2) -> dict:
    response = await llm.ainvoke(
        [SystemMessage(content="당신은 축구화 구매를 돕는 한국어 챗봇입니다.")] + state["messages"]
    )
    return {"messages": [AIMessage(content=response.content)], "active_agent": None, "status": "done"}


def _build_graph(checkpointer, store: BaseStore):
    builder = StateGraph(BuyerAgentStateV2)
    builder.add_node("load_user_memory", load_user_memory)
    builder.add_node("extract_conditions_and_intent", extract_conditions_and_intent)
    builder.add_node("check_conditions", check_conditions)
    builder.add_node("ask_missing_node", ask_missing_node)
    builder.add_node("product_search_node", product_search_node)
    builder.add_node("seller_search_node", seller_search_node)
    builder.add_node("product_analysis_node", product_analysis_node)
    builder.add_node("purchase_prepare_node", purchase_prepare_node)
    builder.add_node("chitchat_node", chitchat_node)
    builder.add_node("save_user_memory", save_user_memory)

    builder.add_edge(START, "load_user_memory")
    builder.add_edge("load_user_memory", "extract_conditions_and_intent")
    builder.add_edge("extract_conditions_and_intent", "check_conditions")
    builder.add_conditional_edges(
        "check_conditions",
        route_after_check,
        {
            "ask_missing_node": "ask_missing_node",
            "product_search_node": "product_search_node",
            "seller_search_node": "seller_search_node",
            "product_analysis_node": "product_analysis_node",
            "purchase_prepare_node": "purchase_prepare_node",
            "chitchat_node": "chitchat_node",
        },
    )

    builder.add_edge("ask_missing_node", END)
    builder.add_edge("purchase_prepare_node", END)
    builder.add_edge("chitchat_node", "save_user_memory")
    builder.add_edge("product_search_node", "save_user_memory")
    builder.add_edge("seller_search_node", "save_user_memory")
    builder.add_edge("product_analysis_node", "save_user_memory")
    builder.add_edge("save_user_memory", END)
    return builder.compile(checkpointer=checkpointer, store=store)


async def build_graph():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore

        conn = await psycopg.AsyncConnection.connect(db_url, autocommit=True)
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()

        store = AsyncPostgresStore(await psycopg.AsyncConnection.connect(db_url, autocommit=True))
        await store.setup()
    else:
        checkpointer = MemorySaver()
        store = InMemoryStore()

    return _build_graph(checkpointer, store)


graph = None
