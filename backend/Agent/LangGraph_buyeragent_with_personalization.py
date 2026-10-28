from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from pydantic import BaseModel, Field

from Agent.product_search_agent import (
    BOOT_SURFACE_KEYWORDS,
    BRAND_RULES,
    _requested_series_name,
)
from Agent.orchestration import (
    product_analysis_worker_node,
    product_search_worker_node,
    seller_search_worker_node,
    supervisor_node,
)
from State.AgentState_personalization import BuyerAgentStateV2, SearchResultItem, UserProfile
from Tools.checkout_adapter import (
    SUPPORTED_CHECKOUT_SELLERS,
    build_checkout_session_payload,
    get_checkout_adapter,
)
from Tools.condition_sanitization import sanitize_condition_map, sanitize_optional_text
from Tools.seller_normalization import normalize_seller_display

load_dotenv()

if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

_chitchat_chain = ChatPromptTemplate.from_messages([
    ("system", "{system}"),
    MessagesPlaceholder("messages"),
]) | llm

_PRODUCT_GUIDE_SYSTEM = (
    "당신은 축구화 구매 가이드 전문가입니다. "
    "FG/AG/TF/IC 지면 선택, 포지션별 추천, 브랜드 특징, 스터드 종류 등 "
    "일반적인 구매 가이드를 안내합니다. "
    "실제 재고·가격은 알 수 없으므로 상품 검색은 하지 않습니다. "
    "한국어로 답하세요."
)

_product_guide_chain = ChatPromptTemplate.from_messages([
    ("system", _PRODUCT_GUIDE_SYSTEM),
    MessagesPlaceholder("messages"),
]) | llm

_CONDITION_QUESTIONS: dict[str, dict] = {
    "budget": {
        "question": "예산대를 알려주세요.",
        "options": [
            {"label": "10만원대", "value": "10만원대", "description": "100,000원부터 199,999원 사이"},
            {"label": "20만원 이하", "value": "20만원 이하", "description": "가격을 넓혀 후보를 더 찾습니다"},
            {"label": "30만원 이하", "value": "30만원 이하", "description": "엘리트급 모델까지 확인합니다"},
            {"label": "가격 무관", "value": "가격 무관", "description": "가격 필터를 적용하지 않습니다"},
        ],
    },
    "surface": {
        "question": "주로 어떤 구장에서 신으시나요?",
        "options": [
            {"label": "FG", "value": "FG", "description": "천연잔디용 스터드"},
            {"label": "AG", "value": "AG", "description": "긴 인조잔디용 스터드"},
            {"label": "TF", "value": "TF", "description": "풋살장/짧은 인조잔디용"},
            {"label": "IC", "value": "IC", "description": "실내 코트용"},
            {"label": "잘 모르겠어요", "value": "지면 모름", "description": "여러 지면 조건으로 넓혀 찾습니다"},
        ],
    },
    "brand": {
        "question": "선호 브랜드가 있나요?",
        "options": [
            {"label": "나이키", "value": "나이키", "description": "머큐리얼, 팬텀, 티엠포 중심"},
            {"label": "아디다스", "value": "아디다스", "description": "F50, 프레데터, 코파 중심"},
            {"label": "푸마", "value": "푸마", "description": "울트라, 퓨처 중심"},
            {"label": "미즈노", "value": "미즈노", "description": "모렐리아 중심"},
            {"label": "상관없음", "value": "브랜드 무관", "description": "브랜드 필터를 적용하지 않습니다"},
        ],
    },
    "position": {
        "question": "주 포지션을 알려주세요.",
        "options": [
            {"label": "공격수", "value": "공격수", "description": "스피드/슈팅 성향을 우선합니다"},
            {"label": "미드필더", "value": "미드필더", "description": "터치/패스 안정성을 우선합니다"},
            {"label": "수비수", "value": "수비수", "description": "접지력/안정성을 우선합니다"},
            {"label": "골키퍼", "value": "골키퍼", "description": "반응/안정성을 우선합니다"},
            {"label": "상관없음", "value": "포지션 무관", "description": "포지션 조건을 적용하지 않습니다"},
        ],
    },
}
_CONDITION_PRIORITY = ["brand", "budget", "surface", "position"]
_PRODUCT_SEARCH_REQUIRED_CONDITIONS = ["brand", "budget", "surface"]
_CAPABILITY_PRIORITY = ("product_search", "seller_search", "product_analysis")
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
    size: str | None = Field(None)


ShoppingCapability = Literal["product_search", "seller_search", "product_analysis"]


class ExtractionResult(BaseModel):
    intent: Literal["shopping", "product_guide", "chitchat"]
    requested_capabilities: list[ShoppingCapability] = Field(default_factory=list)
    conditions: ExtractedConditions


class PurchaseExtractionResult(BaseModel):
    product_index: int | None = None
    product_name: str | None = None
    product_url: str | None = None
    size: str | None = None
    recipient_name: str | None = None
    phone: str | None = None
    address: str | None = None
    detail_address: str | None = None


_purchase_parser = llm.with_structured_output(PurchaseExtractionResult)

# 장기 프로필은 LangMem 의 메모리 매니저 대신 "유저당 고정 키 1건" 직접 upsert 로 관리한다.
# (과거 LangMem 방식은 ① enable_inserts=False 로 신규 프로필 미생성, ② 저장이 그래프 컨텍스트
#  밖 create_task 에서 돌아 get_store() 실패, ③ 인덱스 없는 store 라 매 턴 중복 INSERT 누적 →
#  load 가 오래된 프로필을 집는 문제가 겹쳐 장기 기억이 동작하지 않았다.)
_PROFILE_KEY = "profile"
_PROFILE_FIELDS = ["brand", "budget", "surface", "position", "age_group", "product_name", "seller"]
_profile_extractor = llm.with_structured_output(UserProfile)
_PROFILE_EXTRACT_SYSTEM = (
    "다음 대화에서 사용자에 대해 알 수 있는 정보를 추출하세요: "
    "이름(name), 선호 브랜드(brand), 예산(budget), 선호 지면(surface), 포지션(position), "
    "연령대(age_group), 관심 상품(product_name), 선호 판매처(seller), "
    "플레이 스타일(play_style), 신체 특징(physical_traits). "
    "대화에서 명시적으로 드러난 항목만 채우고, 알 수 없는 항목은 비워 두세요(추측 금지)."
)


def _merge_profiles(existing: dict, new: dict) -> dict:
    """기존 프로필에 새로 추출한 프로필을 병합. 스칼라는 새 값이 있으면 덮어쓰고(없으면 유지),
    리스트는 합집합으로 누적한다."""
    merged = dict(existing or {})
    for key, value in (new or {}).items():
        if isinstance(value, list):
            if value:
                combined = list(dict.fromkeys([*(merged.get(key) or []), *value]))
                merged[key] = combined
        elif value not in (None, ""):
            merged[key] = value
    return merged


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
    item = await store.aget(namespace, _PROFILE_KEY)
    profile = _normalize_profile(_extract_profile_content(item.value) if item else {})
    profile_as_conditions = {
        key: profile[key]
        for key in _PROFILE_FIELDS
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
        messages = _sanitize_messages_for_memory(state.get("messages", []))
        if not messages:
            return {}
        extracted: UserProfile = await _profile_extractor.ainvoke(
            [SystemMessage(content=_PROFILE_EXTRACT_SYSTEM), *messages]
        )
        new_profile = _normalize_profile(extracted.model_dump())

        namespace = ("users", state["user_id"], "profile")
        existing_item = await store.aget(namespace, _PROFILE_KEY)
        existing = _extract_profile_content(existing_item.value) if existing_item else {}

        merged = _merge_profiles(existing, new_profile)
        if merged == existing:
            # 새로 추가된 정보가 없으면 불필요한 쓰기 생략
            return {"user_profile": _normalize_profile(merged)} if merged else {}

        await store.aput(namespace, _PROFILE_KEY, {"kind": "UserProfile", "content": merged})
        return {"user_profile": _normalize_profile(merged)}
    except Exception:
        return {}


# 백그라운드 메모리 저장 태스크의 강참조 보관소.
# asyncio.create_task 의 반환값을 어딘가에 잡아두지 않으면 GC 가 실행 도중 태스크를 회수해
# 프로필 저장이 조용히 누락될 수 있다(파이썬 공식 문서 경고). 완료 시 콜백으로 제거한다.
_pending_memory_saves: set[asyncio.Task] = set()


async def queue_user_memory_save(state: BuyerAgentStateV2, store: BaseStore) -> dict:
    task = asyncio.create_task(save_user_memory(dict(state), store))
    _pending_memory_saves.add(task)
    task.add_done_callback(_pending_memory_saves.discard)
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


_PRODUCT_SEARCH_RESET_KEYS = {"brand", "budget", "surface", "product_name", "seller"}


def _extract_explicit_product_conditions(message: str) -> dict[str, str]:
    """최신 사용자 발화에 명시된 상품 검색 조건만 규칙 기반으로 추출한다."""
    raw = str(message or "")
    lowered = raw.lower()
    upper = raw.upper().replace("AG PRO", "AG-PRO")
    conditions: dict[str, str] = {}

    for brand, aliases in BRAND_RULES.items():
        if any(alias.lower() in lowered for alias in aliases):
            conditions["brand"] = brand
            break

    if match := re.search(r"(\d+)\s*만원\s*(대|이하|이상)?", raw):
        suffix = match.group(2) or ""
        conditions["budget"] = f"{match.group(1)}만원{suffix}"
    elif match := re.search(r"(\d{5,7})\s*원\s*(대|이하|이상)?", raw.replace(",", "")):
        suffix = match.group(2) or ""
        conditions["budget"] = f"{match.group(1)}원{suffix}"

    for surface in BOOT_SURFACE_KEYWORDS:
        normalized = surface.replace("AG PRO", "AG-PRO")
        if re.search(rf"(?<![A-Z0-9]){re.escape(normalized)}(?![A-Z0-9])", upper):
            conditions["surface"] = normalized
            break

    if series := _requested_series_name(raw):
        conditions["product_name"] = series

    if match := re.search(r"사이즈\s*(?:가|는|이)?\s*(\d{3})|(\d{3})\s*사이즈", raw):
        conditions["size"] = match.group(1) or match.group(2)

    return conditions


def _is_unknown_surface(value: str | None) -> bool:
    return str(value or "").strip() in {"지면 모름", "잘 모르겠어요", "상관없음"}


def _is_fresh_product_search_request(message: str, explicit_conditions: dict[str, str]) -> bool:
    """브랜드/예산을 명시한 새 추천 요청이면 이전 필터 조건을 재사용하지 않는다."""
    text = str(message or "").lower()
    has_core_condition = bool(explicit_conditions.get("brand") or explicit_conditions.get("budget"))
    has_search_phrase = any(token in text for token in ("추천", "축구화", "풋살화", "찾아", "골라"))
    return has_core_condition and has_search_phrase


def _merge_product_conditions(
    existing_conditions: dict,
    extracted_conditions: dict,
    explicit_conditions: dict[str, str],
    latest_message: str,
) -> dict:
    existing = sanitize_condition_map(existing_conditions or {})
    extracted_conditions = dict(extracted_conditions or {})
    # LLM 조건 추출기는 "TF"처럼 짧고 모호한 답변을 surface로 못 잡고 product_name으로
    # 잘못 채우는 경우가 실측으로 확인됐다(예: "TF" 단독 답변 -> {"product_name": "TF"}).
    # product_name은 큐레이션된 시리즈 선택 여부를 판단하는 필드이므로, 인식 가능한 시리즈명이
    # 아니면 신뢰하지 않는다(그대로 두면 check_conditions의 시리즈 재질문이 조용히 스킵됨).
    if extracted_conditions.get("product_name") and not _requested_series_name(extracted_conditions["product_name"]):
        extracted_conditions.pop("product_name", None)
    new_conditions = sanitize_condition_map({**extracted_conditions, **explicit_conditions})

    if _is_fresh_product_search_request(latest_message, explicit_conditions):
        base_conditions = {
            key: value
            for key, value in existing.items()
            if key not in _PRODUCT_SEARCH_RESET_KEYS
        }
        if "surface" not in explicit_conditions:
            new_conditions.pop("surface", None)
    else:
        base_conditions = existing

    return sanitize_condition_map({**base_conditions, **new_conditions})


async def extract_conditions_and_intent(state: BuyerAgentStateV2) -> dict:
    previous_intent = state.get("intent", "")
    user_profile = _normalize_profile(dict(state.get("user_profile") or {}))
    structured_items = [f"{k}: {user_profile[k]}" for k in user_profile if user_profile.get(k)]
    latest = _last_user_message(state)

    # 조건 수집 질문에 답변 중인 턴 — intent/plan 재분류 없이 조건만 업데이트
    if state.get("question_sequence"):
        extractor = llm.with_structured_output(ExtractionResult)
        cond_result: ExtractionResult = await extractor.ainvoke(
            [SystemMessage(content="Extract only the product condition values from the user's reply. Do not infer intent."),
             HumanMessage(content=latest)]
        )
        explicit_conditions = _extract_explicit_product_conditions(latest)
        updated_conditions = _merge_product_conditions(
            state.get("user_conditions", {}),
            cond_result.conditions.model_dump(),
            explicit_conditions,
            latest,
        )
        return {
            "intent": previous_intent or "product_search",
            "user_profile": user_profile,
            "user_conditions": updated_conditions,
            "past_steps": [],
            "question_sequence": None,
            "status": "checking",
        }

    # 구매 의도는 오탐 시 리스크가 커서 LLM 호출 전에 정규식으로 선차단한다.
    if _looks_like_purchase_intent(latest) or _should_continue_purchase(state, latest):
        return {
            "intent": "purchase_prepare",
            "user_profile": user_profile,
            "status": "checking",
        }

    system_prompt = (
        "You are a Korean shopping intent classifier for soccer shoes.\n"
        f"Current intent: {previous_intent or 'none'}\n"
        f"Known profile: {', '.join(structured_items) if structured_items else 'none'}\n\n"
        "Classify the user's latest message (use the conversation history for context, e.g. "
        "pronoun/place references like '거기서', '이 제품') into ONE of:\n\n"
        "- shopping: the user wants product recommendations, seller/store info, and/or comparison of "
        "specific products. Set `requested_capabilities` to the subset of "
        "[product_search, seller_search, product_analysis] the message actually asks for — a single "
        "message can request more than one capability.\n"
        "  - product_search: general recommendation without a specific product/seller in mind.\n"
        "  - seller_search: asks WHERE to buy (store/site recommendation).\n"
        "  - product_analysis: compare/analyze specific products, or a specific seller mentioned together "
        "with a product name.\n"
        "- product_guide: educational buying guidance (e.g. FG/AG/TF 차이, 포지션별 스터드), not a live "
        "product search. `requested_capabilities` must be empty.\n"
        "- chitchat: anything else — greetings, unrelated questions, or complaints/comments that merely "
        "mention a product word without asking to search/buy. `requested_capabilities` must be empty.\n\n"
        "IMPORTANT: a purchase-intent phrase like '구매하려고', '사려고', '살래' by itself is NOT a "
        "seller_search request — it only signals the user wants to buy something. Only include "
        "seller_search when the user asks WHERE to buy (어디서, 판매처, 파는 곳 등). "
        "If intent is shopping, requested_capabilities must be non-empty.\n\n"
        "## Examples\n"
        "1) '나이키 10만원대 축구화 추천해주고 어디서 파는지도 알려줘' -> intent=shopping, "
        "requested_capabilities=[product_search, seller_search]\n"
        "2) (직전 AI 턴이 판매처 목록을 보여줌) '거기서 제일 싼 거 분석해줘' -> intent=shopping, "
        "requested_capabilities=[product_analysis]\n"
        "3) '나이키 축구화를 구매하려고 하는데 어떤 게 좋을까? 공격수이거든' -> intent=shopping, "
        "requested_capabilities=[product_search] (NOT seller_search — 어디서 살지가 아니라 뭘 살지를 묻는 것), "
        "conditions.position='공격수'\n"
        "4) 'FG랑 TF 차이가 뭐야?' -> intent=product_guide, requested_capabilities=[]\n"
        "5) '공격수는 축구화 고를 때 뭘 우선으로 봐야 해?' -> intent=product_guide, "
        "requested_capabilities=[] (특정 브랜드/상품 없이 선택 기준을 묻는 질문 — product_search 아님)\n"
        "6) '포지션별로는 어떤 스터드를 사용하는 게 좋아?' -> intent=product_guide, "
        "requested_capabilities=[] (추천이 아니라 일반적인 기준을 묻는 것)\n"
        "7) (직전 AI 턴이 특정 상품을 추천함) '그럼 TF는?' -> intent=shopping, "
        "requested_capabilities=[product_search] (직전 추천을 다른 지면 조건으로 이어서 묻는 짧은 "
        "follow-up — 'FG랑 TF 차이가 뭐야?'처럼 지면 종류 자체를 설명해달라는 게 아니라 그 지면용 "
        "상품을 다시 추천해달라는 것이므로 product_guide 아님), conditions.surface='TF'\n"
        "8) 'ㅎㅇ 오늘 날씨 좋다' -> intent=chitchat, requested_capabilities=[]\n\n"
        "conditions.surface is ONLY a ground type: FG/AG/TF/HG/IC/MG/SG. conditions.seller is ONLY a "
        "shop/marketplace name (e.g. 크레이지11, 사커붐, 레드사커, 카포스토어). A shop name mentioned with "
        "'~에서' (e.g. '크레이지11에서 비교해줘') belongs in conditions.seller, never conditions.surface — "
        "do not put a seller name into surface just because it doesn't look like a recognizable brand/model.\n\n"
        "Extract only conditions explicitly stated in the latest user request. "
        "Each of product_name/seller holds AT MOST ONE value drawn from the user's own latest "
        "wording — never combine multiple candidates listed in earlier assistant tables/messages "
        "into one field, and never carry over a value the user did not just state."
    )
    history = [
        message for message in state.get("messages", [])
        if isinstance(message, (HumanMessage, AIMessage))
    ][-6:]
    extractor = llm.with_structured_output(ExtractionResult)
    result: ExtractionResult = await extractor.ainvoke(
        [SystemMessage(content=system_prompt), *history]
    )

    explicit_conditions = _extract_explicit_product_conditions(latest)
    updated_conditions = _merge_product_conditions(
        state.get("user_conditions", {}),
        result.conditions.model_dump(),
        explicit_conditions,
        latest,
    )

    if result.intent == "shopping":
        # 조건 수집 게이트(check_conditions)가 어떤 capability의 필수 조건을 먼저 물을지 결정하는
        # 우선순위. 실제 실행 순서는 supervisor_node가 매 턴 다시 판단하므로, 여기서는 게이트용
        # 우선순위 하나만 고정한다.
        ordered = [step for step in _CAPABILITY_PRIORITY if step in result.requested_capabilities]
        intent = ordered[0] if ordered else "chitchat"
    else:
        intent = result.intent

    return {
        "intent": intent,
        "user_profile": user_profile,
        "user_conditions": updated_conditions,
        "requested_capabilities": result.requested_capabilities,
        "past_steps": [],
        "status": "checking",
    }


def check_conditions(state: BuyerAgentStateV2) -> dict:
    intent = state.get("intent", "")
    conditions = state.get("user_conditions", {})
    # search_result는 구버전 필드로, 지금 orchestration(Agent/orchestration/workers.py)은 그 값을
    # 쓰지 않고 대신 selected_series/last_products/products에 직전 검색 결과를 남긴다.
    has_prior_product_context = bool(
        state.get("selected_series") or state.get("last_products") or state.get("products")
    )
    missing = []

    if intent == "product_search":
        missing.extend(
            key
            for key in _PRODUCT_SEARCH_REQUIRED_CONDITIONS
            if not conditions.get(key)
        )
    elif intent == "seller_search":
        if not (has_prior_product_context or conditions.get("product_name")):
            missing.append("상품명 또는 이전 검색 결과")
    elif intent == "product_analysis":
        if not (has_prior_product_context or conditions.get("product_name")):
            missing.append("비교할 상품명 또는 이전 검색 결과")

    return {
        "missing_conditions": missing,
        "status": "waiting_input" if missing else "responding",
    }


def route_after_check(state: BuyerAgentStateV2) -> str:
    if state["missing_conditions"]:
        return "ask_missing_node"
    if state["intent"] in {"product_search", "seller_search", "product_analysis"}:
        return "supervisor_node"
    return {
        "purchase_prepare": "purchase_prepare_node",
        "product_guide": "product_guide_node",
        "chitchat": "chitchat_node",
    }.get(state["intent"], "chitchat_node")


def ask_missing_node(state: BuyerAgentStateV2) -> dict:
    effective_intent = state.get("intent", "")
    if effective_intent == "product_search":
        conditions = state.get("user_conditions", {})
        requested_missing = [
            key for key in state.get("missing_conditions", [])
            if key in _CONDITION_QUESTIONS
        ]
        remaining = requested_missing or [
            key
            for key in _PRODUCT_SEARCH_REQUIRED_CONDITIONS
            if not conditions.get(key)
        ]
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


def _known_profile_text(state: BuyerAgentStateV2) -> str:
    """load_user_memory 가 불러온 장기 프로필을 LLM 시스템 프롬프트에 주입하기 위한 텍스트.
    새 세션에서는 state['messages'] 에 과거 대화가 없으므로, 프로필을 명시적으로 넣어주지 않으면
    이름/선호 같은 장기 기억이 답변에 전혀 반영되지 않는다."""
    profile = _normalize_profile(dict(state.get("user_profile") or {}))
    labels = {
        "name": "이름", "brand": "선호 브랜드", "budget": "예산", "surface": "선호 지면",
        "position": "포지션", "age_group": "연령대", "product_name": "관심 상품", "seller": "선호 판매처",
    }
    parts = [f"{label}: {profile[key]}" for key, label in labels.items() if profile.get(key)]
    for key in ("play_style", "physical_traits"):
        values = profile.get(key) or []
        if values:
            parts.append(f"{key}: {', '.join(str(v) for v in values)}")
    return "; ".join(parts)


async def chitchat_node(state: BuyerAgentStateV2) -> dict:
    system_prompt = "당신은 축구화 구매를 돕는 한국어 챗봇입니다."
    known_profile = _known_profile_text(state)
    if known_profile:
        system_prompt += (
            "\n\n아래는 이 사용자에 대해 기억하고 있는 정보입니다. "
            "이름이나 선호를 물으면 이 정보를 활용해 답하세요.\n"
            f"[사용자 프로필] {known_profile}"
        )
    response = await _chitchat_chain.ainvoke({"system": system_prompt, "messages": state["messages"]})
    return {"messages": [AIMessage(content=response.content)], "active_agent": None, "status": "done"}


async def product_guide_node(state: BuyerAgentStateV2) -> dict:
    response = await _product_guide_chain.ainvoke({"messages": state["messages"]})
    return {
        "messages": [AIMessage(content=response.content)],
        "active_agent": "product_guide",
        "status": "done",
        "products": None,
        "sellers": None,
        "analysis": None,
    }


def _build_graph(checkpointer, store: BaseStore):
    builder = StateGraph(BuyerAgentStateV2)
    builder.add_node("load_user_memory", load_user_memory)
    builder.add_node("extract_conditions_and_intent", extract_conditions_and_intent)
    builder.add_node("check_conditions", check_conditions)
    builder.add_node("ask_missing_node", ask_missing_node)
    # supervisor_node/worker 노드들은 Command(goto=...)로 스스로 다음 목적지를 정하므로
    # add_edge를 등록하지 않는다 (고정 plan 대신 매 턴 재판단하는 루프).
    builder.add_node("supervisor_node", supervisor_node)
    builder.add_node("product_search_worker_node", product_search_worker_node)
    builder.add_node("seller_search_worker_node", seller_search_worker_node)
    builder.add_node("product_analysis_worker_node", product_analysis_worker_node)
    builder.add_node("product_guide_node", product_guide_node)
    builder.add_node("purchase_prepare_node", purchase_prepare_node)
    builder.add_node("chitchat_node", chitchat_node)
    builder.add_node("queue_user_memory_save", queue_user_memory_save)

    builder.add_edge(START, "load_user_memory")
    builder.add_edge("load_user_memory", "extract_conditions_and_intent")
    builder.add_edge("extract_conditions_and_intent", "check_conditions")
    builder.add_conditional_edges(
        "check_conditions",
        route_after_check,
        {
            "ask_missing_node": "ask_missing_node",
            "supervisor_node": "supervisor_node",
            "product_guide_node": "product_guide_node",
            "purchase_prepare_node": "purchase_prepare_node",
            "chitchat_node": "chitchat_node",
        },
    )

    builder.add_edge("ask_missing_node", END)
    builder.add_edge("purchase_prepare_node", END)
    builder.add_edge("chitchat_node", "queue_user_memory_save")
    builder.add_edge("product_guide_node", "queue_user_memory_save")
    builder.add_edge("queue_user_memory_save", END)
    return builder.compile(checkpointer=checkpointer, store=store)


# 커넥션 풀을 모듈 레벨에 보관해 프로세스 수명 동안 유지(GC/조기 close 방지).
_checkpointer_pool = None
_store_pool = None


async def build_graph():
    global _checkpointer_pool, _store_pool
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg_pool import AsyncConnectionPool

        # 단일 AsyncConnection 을 여러 코루틴(동시 요청 + 백그라운드 메모리 저장)이 공유하면
        # psycopg 가 "the connection is busy" 로 실패하고, 그 결과 체크포인트(단기 기억)/
        # 스토어(장기 기억) 쓰기·읽기가 조용히 누락돼 대화 기억이 끊긴다.
        # → 풀에서 코루틴마다 별도 커넥션을 빌려 쓰도록 구성한다.
        # prepare_threshold=0: Supabase 풀러 호환(prepared statement 충돌 방지).
        pool_kwargs = {"autocommit": True, "prepare_threshold": 0}
        _checkpointer_pool = AsyncConnectionPool(
            db_url, min_size=1, max_size=10, kwargs=pool_kwargs, open=False
        )
        _store_pool = AsyncConnectionPool(
            db_url, min_size=1, max_size=5, kwargs=pool_kwargs, open=False
        )
        await _checkpointer_pool.open()
        await _store_pool.open()

        checkpointer = AsyncPostgresSaver(_checkpointer_pool)
        await checkpointer.setup()

        store = AsyncPostgresStore(_store_pool)
        await store.setup()
    else:
        checkpointer = MemorySaver()
        store = InMemoryStore()

    return _build_graph(checkpointer, store)


graph = None
