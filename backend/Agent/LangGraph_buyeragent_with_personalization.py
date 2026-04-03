# =============================================================================
# LangGraph_buyeragent(with personalization).py — LangMem 기반 개인화 오케스트레이터
#
# 기존 LangGraph_orchestrator_agent.py 대비 변경점:
#   1. load_user_memory 노드    → store.asearch()로 UserProfile 로드
#   2. save_user_memory 노드    → profile_manager.ainvoke()로 자동 업데이트
#   3. extract_conditions_and_intent → UserProfile을 프롬프트에 주입
#   4. build_graph → LangGraph Store + LangMem 초기화 포함
#
# [핵심: 기존 수동 방식 vs LangMem 방식]
#
#   수동 방식 (이전 구현):
#     _extract_soft_preferences() → LLM 직접 호출로 비정형 정보 추출
#     _upsert_profile_to_supabase() → psycopg로 SQL 직접 작성
#     _load_profile_from_supabase() → SQL SELECT
#
#   LangMem 방식 (이 파일):
#     create_memory_store_manager(schemas=[UserProfile])
#       → 대화를 보고 UserProfile 필드를 자동 추출·업데이트
#       → enable_inserts=False: 유저당 프로필 1개 유지 (insert가 아닌 update)
#     store.asearch(namespace) → 저장된 UserProfile 자동 로드
#     → 별도 SQL, 별도 추출 로직 없이 LangMem이 전부 처리
#
# [그래프 흐름]
#   START
#     ↓
#   [load_user_memory]           ← 첫 턴만 (user_profile is None 조건)
#     ↓                             store.asearch() → UserProfile 로드
#   [extract_conditions_and_intent]  → user_conditions에 병합 + 프롬프트 주입
#     ↓
#   [check_conditions]
#     ├── 조건 부족 → [ask_missing_node]      → END  (저장 안 함)
#     ├── chitchat  → [chitchat_node]         → END  (저장 안 함)
#     ├── product_search   → [product_search_node]   → [save_user_memory] → END
#     ├── seller_search    → [seller_search_node]    → [save_user_memory] → END
#     └── product_analysis → [product_analysis_node] → [save_user_memory] → END
#
# [참고]
#   https://langchain-ai.github.io/langmem/guides/manage_user_profile/
# =============================================================================

from __future__ import annotations

import os
import re
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore
from langmem import create_memory_store_manager
from pydantic import BaseModel, Field

from State.AgentState_personalization import (
    BuyerAgentStateV2,
    SearchResultItem,
    UserProfile,
)
from Agent.sub_agent_0310 import product_search_agent, seller_search_agent
from Agent.product_analysis_agent import product_analysis_agent
from Tools.condition_sanitization import sanitize_condition_map, sanitize_optional_text
from Tools.rag_search import build_analysis_cards
from Tools.seller_normalization import normalize_seller_display

load_dotenv()

# =============================================================================
# LLM 설정
# =============================================================================
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


# =============================================================================
# STEP 1. 구조화 출력 스키마 (extract_conditions_and_intent용)
# =============================================================================


class ExtractedConditions(BaseModel):
    brand: str | None = Field(None, description="브랜드명. 예: 나이키, 아디다스")
    budget: str | None = Field(None, description="예산. 예: 10만원대, 20만원 이하")
    surface: str | None = Field(None, description="경기 지면. 예: 인조잔디, FG, AG, TF")
    position: str | None = Field(None, description="포지션. 예: 공격수, 미드필더")
    age_group: str | None = Field(None, description="연령대. 예: 성인, 유소년")
    product_name: str | None = Field(
        None, description="구체적인 제품명. 예: 머큐리얼 베이퍼"
    )
    seller: str | None = Field(None, description="판매처명. 예: 크레이지11, 사커붐")


class ExtractionResult(BaseModel):
    intent: Literal[
        "product_search", "seller_search", "product_analysis", "chitchat"
    ] = Field(description="사용자 메시지의 의도 분류")
    conditions: ExtractedConditions = Field(
        description="사용자 메시지에서 추출한 조건. 언급되지 않은 항목은 None."
    )


# =============================================================================
# STEP 2. LangMem Profile Manager 초기화
#
# create_memory_store_manager 핵심 파라미터:
#   - model: 프로필 추출에 사용할 LLM
#   - namespace: Store 저장 경로. "{user_id}"는 config에서 자동 치환됨
#   - schemas=[UserProfile]: 추출할 데이터 구조 (Pydantic 모델)
#   - enable_inserts=False: 유저당 프로필 1개 유지
#     → insert 금지, 기존 프로필에 새 정보만 누적 (update only)
#
# 동작 방식:
#   manager.ainvoke({"messages": [...]}, config={"configurable": {"user_id": "..."}})
#   → 대화 이력을 분석해 UserProfile 각 필드를 자동으로 추출·업데이트
#   → 내부적으로 LangGraph Store에 저장
# =============================================================================

profile_manager = create_memory_store_manager(
    "openai:gpt-4o-mini",
    namespace=("users", "{user_id}", "profile"),
    schemas=[UserProfile],
    enable_inserts=False,  # 유저당 단일 프로필 유지
)


# =============================================================================
# STEP 3. load_user_memory 노드 — 세션 첫 턴에만 실행
#
# [실행 조건]
#   state["user_profile"] is None → 아직 로드 안 됨 → 실행
#   state["user_profile"] is not None → 이미 로드됨 → 스킵
#
# [로드 방식]
#   store.asearch(namespace) → LangGraph Store에서 UserProfile 검색
#   → 신규 유저: 빈 dict {} 반환
#   → 기존 유저: 저장된 UserProfile dict 반환
#
# [user_conditions 병합 전략]
#   Supabase 프로필(과거) < 현재 세션 조건(최신)
#   → 과거 데이터를 기본값으로, 이번 세션에서 말한 것이 우선
# =============================================================================


async def load_user_memory(state: BuyerAgentStateV2, store: BaseStore) -> dict:
    # 이미 로드된 경우 스킵 (2턴 이후)
    if state.get("user_profile") is not None:
        print(f"[Memory] user_profile 이미 로드됨, 스킵")
        return {}

    user_id = state["user_id"]
    print(f"[Memory] 첫 턴 감지 → user_id={user_id} 프로필 로드 시작")

    # LangGraph Store에서 UserProfile 검색
    namespace = ("users", user_id, "profile")
    results = await store.asearch(namespace)

    profile: dict = {}
    if results:
        profile = results[0].value
        print(f"[Memory] 로드된 UserProfile: {profile}")
    else:
        print(f"[Memory] 신규 유저 — 저장된 프로필 없음")

    # UserProfile의 구조화 필드를 user_conditions 기본값으로 병합
    # (세션 조건 우선: 이번 세션에서 말한 것이 과거 데이터보다 최신)
    structured_keys = [
        "brand",
        "budget",
        "surface",
        "position",
        "age_group",
        "product_name",
        "seller",
    ]
    for key in structured_keys:
        normalized = sanitize_optional_text(profile.get(key))
        if normalized is None:
            profile.pop(key, None)
        else:
            profile[key] = normalized

    profile_as_conditions = {k: profile[k] for k in structured_keys if profile.get(k)}
    current_conditions = sanitize_condition_map(state.get("user_conditions", {}))
    merged_conditions = {**profile_as_conditions, **current_conditions}

    return {
        "user_profile": profile,
        "user_conditions": merged_conditions,
    }


# =============================================================================
# STEP 4. save_user_memory 노드 — 검색/분석 완료 후에만 실행
#
# [실행 시점]
#   product_search_node, seller_search_node, product_analysis_node 이후만 연결
#   ask_missing_node, chitchat_node 이후에는 연결하지 않음
#
# [LangMem 동작]
#   profile_manager.ainvoke()가 아래를 자동 처리:
#     1. 대화 이력 분석
#     2. UserProfile 각 필드 추출 (구조화 + 비정형 모두)
#        예: brand="나이키", physical_traits=["발볼 넓음"], play_style=["스피드 선호"]
#     3. enable_inserts=False → 기존 프로필에 새 정보만 누적 (덮어쓰지 않음)
#     4. LangGraph Store에 자동 저장
# =============================================================================


async def save_user_memory(state: BuyerAgentStateV2, store: BaseStore) -> dict:
    user_id = state["user_id"]
    messages = state.get("messages", [])

    print(f"[Memory] user_id={user_id} 프로필 업데이트 시작")

    try:
        # LangMem이 대화에서 UserProfile을 자동 추출·업데이트·저장
        # store를 config에 명시적으로 전달 → profile_manager가 올바른 store에 접근
        await profile_manager.ainvoke(
            {"messages": messages},
            config={"configurable": {"user_id": user_id}, "store": store},
        )

        # 업데이트된 프로필을 state에도 반영
        namespace = ("users", user_id, "profile")
        results = await store.asearch(namespace)
        if results:
            updated_profile = results[0].value
            structured_keys = [
                "brand",
                "budget",
                "surface",
                "position",
                "age_group",
                "product_name",
                "seller",
            ]
            for key in structured_keys:
                normalized = sanitize_optional_text(updated_profile.get(key))
                if normalized is None:
                    updated_profile.pop(key, None)
                else:
                    updated_profile[key] = normalized
            print(f"[Memory] 업데이트된 UserProfile: {updated_profile}")
            return {"user_profile": updated_profile}

    except Exception as e:
        print(f"[Memory] 프로필 업데이트 실패: {e}")

    return {}


# =============================================================================
# STEP 4-B. 제품 텍스트 → 구조화 카드 파싱 스키마
#
# product_search_agent가 반환한 마크다운 텍스트를 LLM으로 파싱해
# 프론트엔드 카드 렌더링에 필요한 구조화 데이터를 추출
# =============================================================================


class ProductItem(BaseModel):
    name: str = Field(description="제품 시리즈명. 예: Nike Phantom GX 2 Academy")
    features: str = Field(description="제품 특징 요약 (1-2문장)")
    recommendation: str = Field(description="추천 이유 요약 (1-2문장)")
    price: str | None = Field(None, description="가격 정보. 없으면 None")
    url: str | None = Field(None, description="제품/구매 링크 URL. 없으면 None")


class ParsedProducts(BaseModel):
    products: list[ProductItem] = Field(description="추출된 제품 목록 (최대 5개)")


_parsing_llm = llm.with_structured_output(ParsedProducts)


async def _parse_products(text: str) -> list[dict]:
    """텍스트 응답에서 제품 목록을 구조화 데이터로 파싱."""
    try:
        system = (
            "아래 텍스트에서 추천된 축구화 제품 목록을 파싱해 구조화된 JSON으로 반환하세요. "
            "텍스트에 없는 정보는 None으로 두세요."
        )
        result: ParsedProducts = await _parsing_llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=text)]
        )
        return [p.model_dump() for p in result.products]
    except Exception as e:
        print(f"[파싱] 제품 구조화 실패: {e}")
        return []


# =============================================================================
# STEP 4-C. 판매처 텍스트 → 구조화 카드 파싱 스키마
# =============================================================================


class AnalysisItem(BaseModel):
    name: str = Field(description="제품명. 예: Nike Phantom GX 2")
    seller: str | None = Field(None, description="판매처. 예: 나이키 공식몰, 크레이지11. 없으면 None")
    price: str | None = Field(None, description="가격 정보. 없으면 None")
    size: str | None = Field(None, description="사이즈 정보. 예: 240~290mm. 없으면 None")
    features: list[str] = Field(description="주요 특징 목록 (2~4개)")
    image: str | None = Field(None, description="제품 이미지 URL. 없으면 None")
    url: str | None = Field(None, description="제품 상세 페이지 또는 구매 링크 URL. 없으면 None")


class ParsedAnalysis(BaseModel):
    analysis: list[AnalysisItem] = Field(description="분석된 제품 목록 (최대 5개)")


_analysis_parsing_llm = llm.with_structured_output(ParsedAnalysis)


async def _parse_analysis(text: str) -> list[dict]:
    """텍스트 응답에서 제품 분석 목록을 구조화 데이터로 파싱."""
    try:
        system = (
            "아래 텍스트에서 비교/분석된 축구화 제품 목록을 파싱해 구조화된 JSON으로 반환하세요. "
            "각 제품의 판매처(seller), 가격(price), 사이즈(size), 주요 특징(features), "
            "이미지 URL(image), 상품 상세/구매 링크(url)를 추출하세요. "
            "텍스트에 없는 정보는 None으로 두세요."
        )
        result: ParsedAnalysis = await _analysis_parsing_llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=text)]
        )
        return [item.model_dump() for item in result.analysis]
    except Exception as e:
        print(f"[파싱] 제품 분석 구조화 실패: {e}")
        return []


def _normalize_analysis_key(value: str | None) -> str:
    return re.sub(r"[\W_]+", "", (value or "").lower())


def _match_analysis_item(card: dict, parsed_items: list[dict]) -> dict | None:
    card_name = _normalize_analysis_key(card.get("name"))
    card_seller = _normalize_analysis_key(card.get("seller"))

    if not card_name:
        return None

    for item in parsed_items:
        item_name = _normalize_analysis_key(item.get("name"))
        item_seller = _normalize_analysis_key(item.get("seller"))
        if item_name == card_name and (not card_seller or not item_seller or item_seller == card_seller):
            return item

    for item in parsed_items:
        item_name = _normalize_analysis_key(item.get("name"))
        if item_name and (item_name in card_name or card_name in item_name):
            return item

    return None


def _merge_analysis_cards(source_cards: list[dict], parsed_items: list[dict]) -> list[dict]:
    if not source_cards:
        return parsed_items

    merged_cards: list[dict] = []
    for card in source_cards:
        matched = _match_analysis_item(card, parsed_items)
        merged_cards.append(
            {
                **card,
                "features": matched.get("features") if matched and matched.get("features") else card.get("features", []),
            }
        )

    return merged_cards


class SellerItem(BaseModel):
    name: str = Field(description="판매처 이름. 예: 크레이지11, 나이키 공식몰")
    description: str = Field(description="판매처 특징 요약 (1-2문장)")
    url: str | None = Field(None, description="판매처 URL. 없으면 None")


class ParsedSellers(BaseModel):
    sellers: list[SellerItem] = Field(description="추출된 판매처 목록 (최대 5개)")


_seller_parsing_llm = llm.with_structured_output(ParsedSellers)


async def _parse_sellers(text: str) -> list[dict]:
    """텍스트 응답에서 판매처 목록을 구조화 데이터로 파싱."""
    try:
        system = (
            "아래 텍스트에서 추천된 판매처 목록을 파싱해 구조화된 JSON으로 반환하세요. "
            "텍스트에 없는 정보는 None으로 두세요."
        )
        result: ParsedSellers = await _seller_parsing_llm.ainvoke(
            [SystemMessage(content=system), HumanMessage(content=text)]
        )
        return [s.model_dump() for s in result.sellers]
    except Exception as e:
        print(f"[파싱] 판매처 구조화 실패: {e}")
        return []


# =============================================================================
# STEP 5. extract_conditions_and_intent — UserProfile 컨텍스트 주입 버전
#
# 기존 대비 변경:
#   - user_profile (LangGraph Store에서 로드) → 프롬프트에 주입
#     · 구조화 선호도: brand, budget, surface 등
#     · 비정형 선호도: physical_traits, play_style (LangMem이 추출한 것)
#   → LLM이 유저 맥락을 이해하고 더 자연스러운 추천 가능
#
# [중요] 과거 프로필은 참고용으로만 주입
#   이번 대화에서 명시적으로 언급된 것만 conditions로 추출하도록 지시
#   → 사용자가 말하지 않은 것을 자동으로 채우는 부작용 방지
# =============================================================================


async def extract_conditions_and_intent(state: BuyerAgentStateV2) -> dict:
    previous_intent = state.get("intent", "")
    user_profile = dict(state.get("user_profile") or {})

    # UserProfile에서 프롬프트 컨텍스트 구성
    structured_keys = [
        "brand",
        "budget",
        "surface",
        "position",
        "age_group",
        "product_name",
        "seller",
    ]
    for key in structured_keys:
        normalized = sanitize_optional_text(user_profile.get(key))
        if normalized is None:
            user_profile.pop(key, None)
        else:
            user_profile[key] = normalized
    structured_items = [
        f"{k}: {user_profile[k]}" for k in structured_keys if user_profile.get(k)
    ]
    physical_traits = user_profile.get("physical_traits", [])
    play_style = user_profile.get("play_style", [])

    profile_context = ""
    if structured_items:
        profile_context += (
            f"\n    [이 유저의 과거 선호도]: {', '.join(structured_items)}"
        )
    if physical_traits:
        profile_context += f"\n    [이 유저의 신체 특성]: {', '.join(physical_traits)}"
    if play_style:
        profile_context += f"\n    [이 유저의 플레이 스타일]: {', '.join(play_style)}"

    intent_context = (
        f"\n    현재 진행 중인 의도: {previous_intent}" if previous_intent else ""
    )

    system_prompt = f"""
    당신은 축구화 구매 도우미 AI입니다.
    전체 대화 이력을 보고 아래 두 가지를 동시에 수행하세요.{intent_context}{profile_context}

    1. intent 분류 규칙 (중요):
       - AI가 조건(포지션, 예산, 브랜드 등)을 질문했고, 사용자가 그 답을 제공하는 경우
         → "현재 진행 중인 의도"를 그대로 유지하세요. intent를 바꾸지 마세요.
         예: AI가 "포지션이 어떻게 되세요?" → 사용자 "공격수야!" → product_search 유지
       - 사용자가 명확히 다른 의도를 표현할 때만 intent를 변경하세요.
       - intent 종류:
         · product_search: 제품 추천/검색 요청
         · seller_search: 판매처 탐색 요청
         · product_analysis: 제품 비교/분석 요청
         · chitchat: 명확히 구매와 무관한 일상 대화

    2. conditions 추출 (이번 대화에서 언급된 것만, 없으면 None):
       - [이 유저의 과거 선호도]는 참고용입니다.
         이번 대화에서 사용자가 명시적으로 언급한 것만 추출하세요.
       - brand, budget, surface, position, age_group, product_name, seller
       - Missing fields must be null. Never output the literal strings "None" or "null".
    """

    structured_llm = llm.with_structured_output(ExtractionResult)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    result: ExtractionResult = await structured_llm.ainvoke(messages)

    new_conditions = sanitize_condition_map(result.conditions.model_dump())
    updated_conditions = sanitize_condition_map(
        {**state.get("user_conditions", {}), **new_conditions}
    )

    print(
        f"[추출] intent={result.intent} | new={new_conditions} | total={updated_conditions}"
    )

    return {
        "intent": result.intent,
        "user_profile": user_profile,
        "user_conditions": updated_conditions,
        "status": "checking",
    }


# =============================================================================
# STEP 6. check_conditions — 기존과 동일
# =============================================================================


def check_conditions(state: BuyerAgentStateV2) -> dict:
    intent = state["intent"]
    conditions = state.get("user_conditions", {})
    search_result = state.get("search_result", [])
    missing = []

    if intent == "product_search":
        if not conditions:
            missing.append("brand(브랜드), budget(예산), surface(지면) 중 하나 이상")

    elif intent == "seller_search":
        if not (bool(search_result) or bool(conditions.get("product_name"))):
            missing.append("구매하려는 제품명 또는 브랜드")

    elif intent == "product_analysis":
        if not (bool(search_result) or bool(conditions.get("product_name"))):
            missing.append("비교할 제품명 또는 이전 검색 결과")

    return {
        "missing_conditions": missing,
        "status": "waiting_input" if missing else "searching",
    }


# =============================================================================
# STEP 7. 라우팅 엣지 — 기존과 동일
# =============================================================================


def route_after_check(state: BuyerAgentStateV2) -> str:
    if state["missing_conditions"]:
        return "ask_missing_node"

    routing_map = {
        "product_search": "product_search_node",
        "seller_search": "seller_search_node",
        "product_analysis": "product_analysis_node",
        "chitchat": "chitchat_node",
    }
    return routing_map.get(state["intent"], "chitchat_node")


# =============================================================================
# STEP 8. ask_missing_node — 구조화 질문 + UI 선택지 옵션 반환
#
# product_search 조건 부족 시 조건별 우선순위 질문을 순서대로 1개씩 표시.
# 각 질문에는 프론트엔드가 버튼/카드로 렌더링할 선택지(options)를 함께 반환.
# =============================================================================

# 조건별 질문 텍스트 + 선택지 정의
_CONDITION_QUESTIONS: dict[str, dict] = {
    "budget": {
        "question": "예산은 얼마 정도인가요?",
        "options": ["10만 원 이하", "20만 원 이하", "30만 원 이하", "30만 원 초과"],
    },
    "surface": {
        "question": "어떤 환경에서 사용하실 예정인가요?",
        "options": ["천연잔디 (FG)", "인조잔디 (AG/TF)", "풋살장 (IC/IN)", "상관없음"],
    },
    "brand": {
        "question": "선호하는 브랜드가 있으신가요?",
        "options": ["나이키", "아디다스", "푸마", "뉴발란스", "상관없음"],
    },
    "position": {
        "question": "어떤 포지션을 담당하시나요?",
        "options": ["공격수", "미드필더", "수비수", "골키퍼", "포지션 무관"],
    },
}

# 조건을 묻는 우선순위 순서
_CONDITION_PRIORITY = ["budget", "surface", "brand", "position"]


def ask_missing_node(state: BuyerAgentStateV2) -> dict:
    intent = state.get("intent", "")
    conditions = state.get("user_conditions", {})

    # product_search: 남은 모든 조건의 질문 시퀀스를 한 번에 반환
    # → 프론트엔드가 로컬에서 순서대로 수집 후 마지막에만 API 호출
    if intent == "product_search":
        remaining = [k for k in _CONDITION_PRIORITY if k not in conditions]
        if remaining:
            # 전체 시퀀스 구성
            sequence = [
                {
                    "key": k,
                    "question": _CONDITION_QUESTIONS[k]["question"],
                    "options": _CONDITION_QUESTIONS[k]["options"],
                }
                for k in remaining
            ]
            first_q = _CONDITION_QUESTIONS[remaining[0]]
            return {
                "messages": [AIMessage(content=first_q["question"])],
                "status": "waiting_input",
                "question_options": first_q["options"],
                "question_sequence": sequence,  # 남은 전체 질문 목록
            }

    # 그 외 / fallback: 자유 텍스트 질문
    missing_str = ", ".join(state["missing_conditions"])
    question = (
        f"축구화를 더 잘 추천해드리기 위해 몇 가지 여쭤볼게요!\n\n"
        f"다음 정보를 알려주시면 바로 도와드릴 수 있어요:\n"
        f"✅ {missing_str}\n\n"
        f"편하게 말씀해 주세요!"
    )
    return {
        "messages": [AIMessage(content=question)],
        "status": "waiting_input",
        "question_options": None,
        "question_sequence": None,
    }


# =============================================================================
# STEP 9~11. 검색/분석 노드 — 기존과 동일
# =============================================================================


async def product_search_node(state: BuyerAgentStateV2) -> dict:
    conditions = state.get("user_conditions", {})
    previous_agent = state.get("active_agent")

    if previous_agent and previous_agent != "product_search":
        print(f"[전환 감지] {previous_agent} → product_search")

    query_parts = [
        conditions[k]
        for k in ["brand", "budget", "surface", "position", "age_group", "product_name"]
        if conditions.get(k)
    ]
    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 축구화 추천"

    try:
        response = await product_search_agent(
            query, user_profile=state.get("user_profile") or {}
        )
        search_result: list[SearchResultItem] = [
            {
                "name": conditions.get("product_name", base),
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_search",
            }
        ]
        # 텍스트 응답 → 구조화 카드 데이터 파싱
        products = await _parse_products(response)
        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result,
            "products": products if products else None,
            "active_agent": "product_search",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        current_retry = state.get("retry_count", 0)
        if current_retry < 3:
            return {
                "status": "error",
                "error": str(e),
                "retry_count": current_retry + 1,
            }
        return {
            "messages": [
                AIMessage(content="죄송해요, 제품 검색 중 오류가 발생했어요.")
            ],
            "status": "error",
            "error": str(e),
        }


async def seller_search_node(state: BuyerAgentStateV2) -> dict:
    previous_agent = state.get("active_agent")
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})

    if previous_agent == "product_search" and search_result:
        product_name = search_result[0].get("name", "")
        print(
            f"[전환 감지] product_search → seller_search | 인계된 제품: {product_name}"
        )
        query = f"{product_name} 축구화 온라인 판매처"
    else:
        base = conditions.get("product_name") or conditions.get("brand") or "축구화"
        query = f"{base} 축구화 온라인 판매처"

    try:
        response = await seller_search_agent(
            query, user_profile=state.get("user_profile") or {}
        )
        search_result_updated: list[SearchResultItem] = [
            {
                "name": query,
                "description": response,
                "price": "",
                "url": "",
                "source": "seller_search",
            }
        ]
        sellers = await _parse_sellers(response)
        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result_updated,
            "sellers": sellers if sellers else None,
            "active_agent": "seller_search",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        return {
            "messages": [
                AIMessage(content="죄송해요, 판매처 검색 중 오류가 발생했어요.")
            ],
            "status": "error",
            "error": str(e),
        }


async def product_analysis_node(state: BuyerAgentStateV2) -> dict:
    previous_agent = state.get("active_agent")
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})

    if previous_agent and previous_agent != "product_analysis":
        print(f"[전환 감지] {previous_agent} → product_analysis")

    query_parts = []
    seller = normalize_seller_display(conditions.get("seller", ""))
    if seller:
        query_parts.append(f"{seller}에서")

    product_name = conditions.get("product_name", "")
    if not product_name and previous_agent == "product_search" and search_result:
        product_name = search_result[0].get("name", "")
    if product_name:
        query_parts.append(product_name)
    if conditions.get("brand") and not product_name:
        query_parts.append(conditions["brand"])
    for key in ["budget", "age_group", "surface", "position"]:
        if conditions.get(key):
            query_parts.append(conditions[key])

    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 축구화 비교해줘"

    try:
        response = await product_analysis_agent(
            query, user_profile=state.get("user_profile") or {}
        )
        source_cards = build_analysis_cards(query)
        parsed_items = await _parse_analysis(response)
        analysis = _merge_analysis_cards(source_cards, parsed_items)
        search_result_updated: list[SearchResultItem] = [
            {
                "name": product_name or base,
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_analysis",
            }
        ]
        # 텍스트 응답 → 구조화 카드 데이터 파싱
        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result_updated,
            "analysis": analysis if analysis else None,
            "active_agent": "product_analysis",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        return {
            "messages": [
                AIMessage(content="죄송해요, 제품 분석 중 오류가 발생했어요.")
            ],
            "status": "error",
            "error": str(e),
        }


# =============================================================================
# STEP 12. chitchat_node — 기존과 동일
# =============================================================================


async def chitchat_node(state: BuyerAgentStateV2) -> dict:
    system_prompt = (
        "당신은 친절한 축구화 구매 도우미입니다. "
        "사용자의 일상 대화에 따뜻하게 응답하세요."
    )
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await llm.ainvoke(messages)
    return {
        "messages": [AIMessage(content=response.content)],
        "active_agent": None,
        "status": "done",
    }


# =============================================================================
# STEP 13. 그래프 조립 — LangGraph Store 포함 버전
#
# [핵심 변경]
#   builder.compile(checkpointer=checkpointer, store=store)
#   → store를 추가함으로써 LangMem profile_manager가 자동으로 해당 store 사용
#   → load_user_memory, save_user_memory 노드에 store가 자동 주입됨
#
# [Store 선택]
#   로컬 개발: InMemoryStore (서버 재시작 시 초기화)
#   프로덕션: AsyncPostgresStore 권장
#     → pip install langgraph-checkpoint-postgres
#     → from langgraph.store.postgres import AsyncPostgresStore
#     → store = await AsyncPostgresStore.from_conn_string(db_url)
#     → await store.setup()
# =============================================================================


def _build_graph(checkpointer, store: BaseStore):
    builder = StateGraph(BuyerAgentStateV2)

    # ── 노드 등록 ────────────────────────────────────────────────────────────
    builder.add_node("load_user_memory", load_user_memory)
    builder.add_node("extract_conditions_and_intent", extract_conditions_and_intent)
    builder.add_node("check_conditions", check_conditions)
    builder.add_node("ask_missing_node", ask_missing_node)
    builder.add_node("product_search_node", product_search_node)
    builder.add_node("seller_search_node", seller_search_node)
    builder.add_node("product_analysis_node", product_analysis_node)
    builder.add_node("chitchat_node", chitchat_node)
    builder.add_node("save_user_memory", save_user_memory)

    # ── 엣지 연결 ────────────────────────────────────────────────────────────
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
            "chitchat_node": "chitchat_node",
        },
    )

    # 저장 불필요한 노드 → END 직접 연결
    builder.add_edge("ask_missing_node", END)
    builder.add_edge("chitchat_node", END)

    # 검색/분석 노드 → save_user_memory → END
    builder.add_edge("product_search_node", "save_user_memory")
    builder.add_edge("seller_search_node", "save_user_memory")
    builder.add_edge("product_analysis_node", "save_user_memory")
    builder.add_edge("save_user_memory", END)

    return builder.compile(checkpointer=checkpointer, store=store)


async def build_graph():
    """
    Checkpointer + Store 초기화 후 graph 반환.

    DATABASE_URL이 있으면:
      - Checkpointer: AsyncPostgresSaver (Supabase) → 대화 이력 영구 저장
      - Store:        AsyncPostgresStore (Supabase) → UserProfile 장기 메모리 영구 저장

    DATABASE_URL이 없으면:
      - Checkpointer: MemorySaver (메모리)
      - Store:        InMemoryStore (메모리)
    """
    db_url = os.environ.get("DATABASE_URL")

    if db_url:
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres import AsyncPostgresStore

        conn = await psycopg.AsyncConnection.connect(db_url, autocommit=True)
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()
        print("[Checkpointer] AsyncPostgresSaver (Supabase) 연결 완료")

        store = AsyncPostgresStore(
            await psycopg.AsyncConnection.connect(db_url, autocommit=True)
        )
        await store.setup()
        print(
            "[Store] AsyncPostgresStore (Supabase) 연결 완료 — UserProfile 장기 저장 활성화"
        )
    else:
        checkpointer = MemorySaver()
        store = InMemoryStore()
        print("[Checkpointer] MemorySaver (로컬 개발)")
        print("[Store] InMemoryStore (로컬 개발) — 재시작 시 UserProfile 초기화")

    return _build_graph(checkpointer, store)


graph = None


# =============================================================================
# STEP 14. 로컬 테스트
# =============================================================================


async def run_test():
    g = await build_graph()

    config = {"configurable": {"thread_id": "LEE:session_001"}}

    print("=" * 60)
    print("BuyerAgent LangMem 개인화 테스트")
    print("=" * 60)

    # initial_state = {
    #     "session_id": "session_001", "user_id": "LEE",
    #     "messages":   [HumanMessage(content="가볍고 슈팅이 좋은 나이키 10만원대 축구화 추천해줘")],
    #     "intent": "", "active_agent": None,
    #     "user_conditions": {}, "missing_conditions": [],
    #     "search_result": [], "status": "extracting",
    #     "error": None, "retry_count": 0,
    #     "user_profile": None,  # None → load_user_memory 실행 트리거
    # }

    # print("\n[1턴] 제품 추천 + 첫 턴 메모리 로드")
    # result = await g.ainvoke(initial_state, config=config)
    # print(f"user_profile:    {result.get('user_profile')}")
    # print(f"user_conditions: {result['user_conditions']}")
    # print(f"응답 미리보기: {result['messages'][-1].content[:150]}...")

    # print("\n[2턴] 비정형 정보 추가 (LangMem 추출 확인)")
    # result2 = await g.ainvoke(
    #     {"messages": [HumanMessage(content="발볼이 좀 넓은 편이고 공격수야!")]},
    #     config=config,
    # )
    # print(f"user_profile:    {result2.get('user_profile')}")
    # print(f"  → physical_traits: {result2.get('user_profile', {}).get('physical_traits')}")
    # print(f"응답 미리보기: {result2['messages'][-1].content[:150]}...")

    print("\n[3턴] 비정형 정보 추가 (LangMem 추출 확인)")
    result2 = await g.ainvoke(
        {
            "messages": [
                HumanMessage(
                    content="크레이지11에서 나이키 머큐리얼 베이퍼 성인용 TF 10만원대 비교해줘"
                )
            ]
        },
        config=config,
    )
    print(f"user_profile:    {result2.get('user_profile')}")
    print(
        f"  → physical_traits: {result2.get('user_profile', {}).get('physical_traits')}"
    )
    print(f"응답 미리보기: {result2['messages'][-1].content[:150]}...")


if __name__ == "__main__":
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_test())
