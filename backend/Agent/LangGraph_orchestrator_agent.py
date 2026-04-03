# =============================================================================
# LangGraph_orchestrator_agent.py — 동적 에이전트 전환 오케스트레이터
#
# 전체 흐름:
#   START
#     ↓
#   [extract_conditions_and_intent]  ← 매 턴, LLM 1회로 의도+조건 동시 추출
#     ↓
#   [check_conditions]               ← 조건 충분 여부 판단 (LLM 없음, 순수 로직)
#     ├── 조건 부족 → [ask_missing_node] → END  (사용자에게 질문 후 종료)
#     │                                          (다음 메시지에서 state 복원 후 재시도)
#     ├── chitchat  → [chitchat_node]   → END
#     ├── product_search   → [product_search_node]   → END
#     ├── seller_search    → [seller_search_node]    → END
#     └── product_analysis → [product_analysis_node] → END
#
# 동적 전환 핵심 로직:
#   매 노드 진입 시 `intent != active_agent` 이면 에이전트 전환 감지
#   → 이전 search_result를 다음 에이전트 쿼리에 자동 인계
# =============================================================================

from __future__ import annotations

import json
import os
from typing import Literal

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

# 같은 backend/ 폴더 기준 import
from State.AgentState import BuyerAgentState, SearchResultItem
from Agent.sub_agent_0310 import product_search_agent, seller_search_agent
from Agent.product_analysis_agent import product_analysis_agent
from Tools.condition_sanitization import sanitize_condition_map
from Tools.seller_normalization import normalize_seller_display

load_dotenv()

# =============================================================================
# LLM 설정
# 오케스트레이터는 gpt-4o-mini (속도/비용 균형)
# 구조화된 출력(Structured Output)에 최적화된 temperature=0
# =============================================================================
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


# =============================================================================
# STEP 1. 구조화 출력 스키마 정의
#
# extract_conditions_and_intent 노드에서 LLM이 반환할 구조.
# Pydantic BaseModel로 정의하면 LLM이 JSON을 자동으로 파싱해서 반환.
# =============================================================================

class ExtractedConditions(BaseModel):
    # 각 필드를 Optional[str]로 명시 → LLM이 정확히 어떤 값을 채워야 할지 명확해짐
    # 언급되지 않은 항목은 None으로 반환 → None 값은 merge 시 제외
    brand:        str | None = Field(None, description="브랜드명. 예: 나이키, 아디다스")
    budget:       str | None = Field(None, description="예산. 예: 10만원대, 20만원 이하")
    surface:      str | None = Field(None, description="경기 지면. 예: 인조잔디, 천연잔디, 풋살장, FG, AG, TF")
    position:     str | None = Field(None, description="포지션. 예: 공격수, 미드필더, 수비수")
    age_group:    str | None = Field(None, description="연령대. 예: 성인, 유소년")
    product_name: str | None = Field(None, description="구체적인 제품명. 예: 머큐리얼 베이퍼, 프레데터")
    seller:       str | None = Field(None, description="판매처명. 예: 크레이지11, 사커붐, 레드사커")


class ExtractionResult(BaseModel):
    intent: Literal["product_search", "seller_search", "product_analysis", "chitchat"] = Field(
        description="사용자 메시지의 의도 분류"
    )
    conditions: ExtractedConditions = Field(
        description="사용자 메시지에서 추출한 조건. 언급되지 않은 항목은 None."
    )


# =============================================================================
# STEP 2. extract_conditions_and_intent 노드
#
# [역할]
#   - 기존 classify_intent + extract_conditions 2개 노드를 1개로 통합
#   - LLM 호출 1회로 의도 분류 + 조건 추출 동시 처리 → 지연시간 절약
#
# [조건 누적 방식]
#   - 기존 user_conditions에 새로 추출한 conditions를 merge (덮어쓰지 않음)
#   - 예) 1턴: {"brand": "나이키"} + 2턴: {"budget": "10만원대"}
#          → {"brand": "나이키", "budget": "10만원대"}
# =============================================================================

async def extract_conditions_and_intent(state: BuyerAgentState) -> dict:
    # 이전 intent를 프롬프트에 포함 → 조건 보충 답변 시 intent 유지에 활용
    previous_intent = state.get("intent", "")
    intent_context = f"\n    현재 진행 중인 의도: {previous_intent}" if previous_intent else ""

    system_prompt = f"""
    당신은 축구화 구매 도우미 AI입니다.
    전체 대화 이력을 보고 아래 두 가지를 동시에 수행하세요.{intent_context}

    1. intent 분류 규칙 (중요):
       - AI가 조건(포지션, 예산, 브랜드 등)을 질문했고, 사용자가 그 답을 제공하는 경우
         → "현재 진행 중인 의도"를 그대로 유지하세요. intent를 바꾸지 마세요.
         예: AI가 "포지션이 어떻게 되세요?" → 사용자 "공격수야!" → product_search 유지
       - 사용자가 명확히 다른 의도를 표현할 때만 intent를 변경하세요.
         예: "어디서 살 수 있어?" → seller_search로 전환
       - intent 종류:
         · product_search: 제품 추천/검색 요청 ("추천해줘", "어떤 거 좋아?")
         · seller_search: 판매처 탐색 요청 ("어디서 살 수 있어?", "파는 곳 알려줘")
         · product_analysis: 제품 비교/분석 요청 ("이 두 개 비교해줘", "스펙 비교")
         · chitchat: 명확히 구매와 무관한 일상 대화 ("안녕!", "고마워")

    2. conditions 추출 (언급된 것만 추출, 없으면 None):
       - brand: 브랜드명 (예: "나이키", "아디다스")
       - budget: 예산 (예: "10만원대", "20만원 이하")
       - surface: 경기 지면 (예: "AG", "HG", "FG", "TF")
       - position: 포지션 (예: "공격수", "미드필더")
       - age_group: 연령대 (예: "성인", "유소년")
       - product_name: 구체적인 제품명 (예: "머큐리얼 베이퍼")
       - seller: 판매처명 (예: "크레이지11", "사커붐")
       - Missing fields must be null. Never output the literal strings "None" or "null".
    """

    # LLM에 구조화 출력 요청 (method 미지정 → LangChain이 모델에 맞는 최적 방식 자동 선택)
    structured_llm = llm.with_structured_output(ExtractionResult)

    # 전체 대화 이력 + 시스템 프롬프트 전달 (컨텍스트 유지)
    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    result: ExtractionResult = await structured_llm.ainvoke(messages)

    # ExtractedConditions → dict 변환 (None 값 제외)
    # None인 필드는 "언급되지 않은 조건"이므로 기존 값 유지
    new_conditions = sanitize_condition_map(result.conditions.model_dump())

    # 기존 조건과 새로 추출한 조건을 merge (누적)
    # 새 값이 기존 값을 덮어씀 → 사용자가 조건을 변경할 수 있음
    updated_conditions = sanitize_condition_map(
        {**state.get("user_conditions", {}), **new_conditions}
    )

    print(f"[추출] intent={result.intent} | new={new_conditions} | total={updated_conditions}")

    return {
        "intent": result.intent,
        "user_conditions": updated_conditions,
        "status": "checking",
    }


# =============================================================================
# STEP 3. check_conditions 노드
#
# [역할]
#   - 현재 intent에 필요한 조건이 충분한지 판단 (LLM 없음, 순수 Python 로직)
#   - 부족한 조건 목록을 missing_conditions에 저장
#
# [intent별 필수 조건]
#   - product_search: user_conditions가 완전히 비어있으면 최소 1개 요청
#                     (브랜드나 예산 중 하나라도 있으면 진행)
#   - seller_search:  search_result(이전 검색 결과) 또는 product_name 중 하나 필요
#   - product_analysis: search_result 또는 product_name 필요
#   - chitchat: 조건 불필요
# =============================================================================

def check_conditions(state: BuyerAgentState) -> dict:
    intent = state["intent"]
    conditions = state.get("user_conditions", {})
    search_result = state.get("search_result", [])
    missing = []

    if intent == "product_search":
        # 조건이 하나도 없을 때만 요청 (부분 조건은 허용)
        if not conditions:
            missing.append("brand(브랜드), budget(예산), surface(지면) 중 하나 이상")

    elif intent == "seller_search":
        # 이전 product_search 결과가 있거나 product_name을 직접 말했으면 진행
        has_product_context = bool(search_result) or bool(conditions.get("product_name"))
        if not has_product_context:
            missing.append("구매하려는 제품명 또는 브랜드")

    elif intent == "product_analysis":
        # 비교할 제품 정보가 있어야 함
        has_context = bool(search_result) or bool(conditions.get("product_name"))
        if not has_context:
            missing.append("비교할 제품명 또는 이전 검색 결과")

    # chitchat은 조건 불필요 → missing = []

    return {
        "missing_conditions": missing,
        "status": "waiting_input" if missing else "searching",
    }


# =============================================================================
# STEP 4. 조건 분기 엣지 함수 (Conditional Edge)
#
# [역할]
#   - check_conditions 이후 어느 노드로 갈지 결정
#   - LangGraph는 이 함수의 반환값(str)을 노드 이름으로 사용
# =============================================================================

def route_after_check(state: BuyerAgentState) -> str:
    # 조건 부족 → 사용자에게 질문
    if state["missing_conditions"]:
        return "ask_missing_node"

    # 조건 충분 → intent에 따라 해당 에이전트 노드로 분기
    intent = state["intent"]
    routing_map = {
        "product_search":   "product_search_node",
        "seller_search":    "seller_search_node",
        "product_analysis": "product_analysis_node",
        "chitchat":         "chitchat_node",
    }
    return routing_map.get(intent, "chitchat_node")


# =============================================================================
# STEP 5. ask_missing_node — 조건 부족 시 사용자에게 질문
#
# [역할]
#   - missing_conditions를 보고 자연스러운 질문 메시지 생성
#   - AIMessage로 messages에 추가 → 프론트에서 사용자에게 표시됨
#   - 이후 사용자가 답변하면 다음 요청에서 state 복원 후 다시 extract_conditions 실행
# =============================================================================

def ask_missing_node(state: BuyerAgentState) -> dict:
    missing = state["missing_conditions"]
    missing_str = ", ".join(missing)

    question = (
        f"축구화를 더 잘 추천해드리기 위해 몇 가지 여쭤볼게요! 😊\n\n"
        f"다음 정보를 알려주시면 바로 도와드릴 수 있어요:\n"
        f"✅ {missing_str}\n\n"
        f"편하게 말씀해 주세요!"
    )

    return {
        "messages": [AIMessage(content=question)],
        "status": "waiting_input",
    }


# =============================================================================
# STEP 6. product_search_node — 제품 추천 에이전트 실행
#
# [동적 전환 감지]
#   - active_agent가 None이거나 "product_search"이면: 일반 실행
#   - 다른 에이전트에서 전환: 동일 (product_search는 항상 새 검색)
#
# [쿼리 구성]
#   - user_conditions에서 조건들을 조합하여 자연어 쿼리 생성
#   - sub_agent.py의 product_search_agent에 전달
# =============================================================================

async def product_search_node(state: BuyerAgentState) -> dict:
    conditions = state.get("user_conditions", {})
    previous_agent = state.get("active_agent")

    # 에이전트 전환 감지 로그 (디버깅용)
    if previous_agent and previous_agent != "product_search":
        print(f"[전환 감지] {previous_agent} → product_search")

    # user_conditions에서 자연어 쿼리 조합
    query_parts = []
    if conditions.get("brand"):
        query_parts.append(conditions["brand"])
    if conditions.get("budget"):
        query_parts.append(conditions["budget"])
    if conditions.get("surface"):
        query_parts.append(conditions["surface"])
    if conditions.get("position"):
        query_parts.append(conditions["position"])
    if conditions.get("age_group"):
        query_parts.append(conditions["age_group"])
    if conditions.get("product_name"):
        query_parts.append(conditions["product_name"])

    # 최소한 "축구화 추천"은 포함
    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 축구화 추천"

    try:
        response = await product_search_agent(query)

        # 응답을 SearchResultItem 형태로 저장 (다음 에이전트가 활용)
        search_result: list[SearchResultItem] = [
            {
                "name": conditions.get("product_name", base),
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_search",
            }
        ]

        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result,
            "active_agent": "product_search",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        current_retry = state.get("retry_count", 0)
        if current_retry < 3:
            # 재시도 (다음 invoke 시 retry_count 확인)
            return {"status": "error", "error": str(e), "retry_count": current_retry + 1}
        return {
            "messages": [AIMessage(content="죄송해요, 제품 검색 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")],
            "status": "error",
            "error": str(e),
        }


# =============================================================================
# STEP 7. seller_search_node — 판매처 탐색 에이전트 실행
#
# [동적 전환 핵심 — 컨텍스트 인계]
#   - 이전 active_agent가 "product_search"이면 → search_result에서 제품명 추출
#   - 추출한 제품명을 seller_search 쿼리에 자동 포함 → 개인화된 판매처 검색
#
# 예시:
#   product_search → search_result: [{"name": "나이키 머큐리얼 클럽", ...}]
#   seller_search  → query: "나이키 머큐리얼 클럽 축구화 온라인 판매처"
# =============================================================================

async def seller_search_node(state: BuyerAgentState) -> dict:
    previous_agent = state.get("active_agent")
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})

    # ── 동적 전환: product_search에서 넘어온 경우 ──────────────────────────
    if previous_agent == "product_search" and search_result:
        # 이전 검색 결과의 제품명을 쿼리에 자동 인계
        product_name = search_result[0].get("name", "")
        print(f"[전환 감지] product_search → seller_search | 인계된 제품: {product_name}")
        query = f"{product_name} 축구화 온라인 판매처"

    # ── 직접 seller_search로 진입한 경우 ──────────────────────────────────
    else:
        # user_conditions에서 직접 쿼리 구성
        product_name = conditions.get("product_name", "")
        brand = conditions.get("brand", "")
        base = product_name or brand or "축구화"
        query = f"{base} 축구화 온라인 판매처"

    try:
        response = await seller_search_agent(query)

        search_result_updated: list[SearchResultItem] = [
            {
                "name": query,
                "description": response,
                "price": "",
                "url": "",
                "source": "seller_search",
            }
        ]

        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result_updated,
            "active_agent": "seller_search",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        return {
            "messages": [AIMessage(content="죄송해요, 판매처 검색 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")],
            "status": "error",
            "error": str(e),
        }


# =============================================================================
# STEP 8. product_analysis_node — 제품 비교 분석 에이전트 실행
#
# [역할]
#   product_analysis_agent는 아래 순서로 동작한다:
#     1. crawl_and_index: 판매처 크롤링 → vectorstore 저장
#     2. rag_search: vectorstore 검색 → Markdown 비교표 생성
#
# [쿼리 구성 전략]
#   product_analysis_agent는 자연어 쿼리를 그대로 받는다.
#   → "크레이지11에서 나이키 머큐리얼 10만원대 성인용 FG 축구화 비교해줘" 형태
#
# [동적 전환 컨텍스트 인계]
#   - product_search에서 전환: search_result[0]["name"]에서 제품명 추출
#   - seller_search에서 전환: search_result[0]["name"]에서 판매처 정보 추출
#   - 직접 진입: user_conditions에서 제품명/판매처 직접 사용
# =============================================================================

async def product_analysis_node(state: BuyerAgentState) -> dict:
    previous_agent = state.get("active_agent")
    search_result = state.get("search_result", [])
    conditions = state.get("user_conditions", {})

    # ── 동적 전환 감지 로그 ──────────────────────────────────────────────────
    if previous_agent and previous_agent != "product_analysis":
        print(f"[전환 감지] {previous_agent} → product_analysis | 분석 대상: {len(search_result)}개")

    # ── 쿼리 구성: 이전 에이전트 결과 + user_conditions 조합 ─────────────────
    #
    # product_analysis_agent가 이해하는 판매처명 (한국어 → 내부에서 영문 변환):
    #   크레이지11, 사커붐, 레드사커, 카포스토어
    #
    # 우선순위:
    #   1) seller_search 결과 → 판매처 정보 포함된 query 재사용
    #   2) user_conditions의 seller, product_name 직접 사용
    #   3) product_search 결과 → 제품명만 인계, 판매처는 전체 검색

    query_parts = []

    # 판매처 결정
    seller = normalize_seller_display(conditions.get("seller", ""))
    if not seller and previous_agent == "seller_search" and search_result:
        # seller_search 결과의 name은 "제품명 축구화 온라인 판매처" 형태의 쿼리가 저장됨
        # 특정 판매처를 직접 지정할 수 없으므로 전체 판매처 대상으로 분석
        seller = ""

    if seller:
        query_parts.append(f"{seller}에서")

    # 제품명 결정
    product_name = conditions.get("product_name", "")
    if not product_name and previous_agent == "product_search" and search_result:
        # product_search가 저장한 name 인계
        product_name = search_result[0].get("name", "")

    if product_name:
        query_parts.append(product_name)

    # 추가 조건
    if conditions.get("brand") and not product_name:
        query_parts.append(conditions["brand"])
    if conditions.get("budget"):
        query_parts.append(conditions["budget"])
    if conditions.get("age_group"):
        query_parts.append(conditions["age_group"])
    if conditions.get("surface"):
        query_parts.append(conditions["surface"])
    if conditions.get("position"):
        query_parts.append(conditions["position"])

    # 최종 자연어 쿼리 조합
    # 예: "크레이지11에서 나이키 머큐리얼 10만원대 성인용 FG 축구화 비교해줘"
    base = " ".join(query_parts) if query_parts else "축구화"
    query = f"{base} 축구화 비교해줘"

    try:
        response = await product_analysis_agent(query)

        # 분석 결과를 SearchResultItem으로 저장 (이후 에이전트가 활용할 수 있도록)
        search_result_updated: list[SearchResultItem] = [
            {
                "name": product_name or base,
                "description": response,
                "price": conditions.get("budget", ""),
                "url": "",
                "source": "product_analysis",
            }
        ]

        return {
            "messages": [AIMessage(content=response)],
            "search_result": search_result_updated,
            "active_agent": "product_analysis",
            "status": "done",
            "retry_count": 0,
            "error": None,
        }

    except Exception as e:
        return {
            "messages": [AIMessage(content="죄송해요, 제품 분석 중 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")],
            "status": "error",
            "error": str(e),
        }


# =============================================================================
# STEP 9. chitchat_node — 일상 대화 처리
#
# [역할]
#   - 구매 의도가 없는 일반 대화 처리
#   - LLM을 직접 호출하여 자연스러운 응답 생성
#   - search_result, user_conditions는 변경하지 않음 (누적 유지)
# =============================================================================

async def chitchat_node(state: BuyerAgentState) -> dict:
    system_prompt = (
        "당신은 친절한 축구화 구매 도우미입니다. "
        "사용자의 일상 대화에 따뜻하게 응답하세요. "
        "필요하다면 자연스럽게 축구화 관련 주제로 유도해도 좋습니다."
    )

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = await llm.ainvoke(messages)

    return {
        "messages": [AIMessage(content=response.content)],
        "active_agent": None,  # chitchat은 active_agent 변경 없음
        "status": "done",
    }


# =============================================================================
# STEP 10. 그래프 조립 (StateGraph 빌드)
#
# [노드 등록]
#   - add_node(이름, 함수)로 각 노드 등록
#
# [엣지 연결]
#   - add_edge: 고정 경로
#   - add_conditional_edges: 조건부 분기 (route 함수의 반환값 → 노드 이름 매핑)
# =============================================================================

def _build_graph_with_checkpointer(checkpointer):
    """노드/엣지 조립 + checkpointer 주입 → compiled graph 반환 (순수 sync)"""
    builder = StateGraph(BuyerAgentState)

    # ── 노드 등록 ────────────────────────────────────────────────────────────
    builder.add_node("extract_conditions_and_intent", extract_conditions_and_intent)
    builder.add_node("check_conditions",              check_conditions)
    builder.add_node("ask_missing_node",              ask_missing_node)
    builder.add_node("product_search_node",           product_search_node)
    builder.add_node("seller_search_node",            seller_search_node)
    builder.add_node("product_analysis_node",         product_analysis_node)
    builder.add_node("chitchat_node",                 chitchat_node)

    # ── 엣지 연결 ────────────────────────────────────────────────────────────

    # 1. 시작 → 조건+의도 추출
    builder.add_edge(START, "extract_conditions_and_intent")

    # 2. 조건+의도 추출 → 조건 검사
    builder.add_edge("extract_conditions_and_intent", "check_conditions")

    # 3. 조건 검사 → 분기 (핵심 라우팅)
    builder.add_conditional_edges(
        "check_conditions",
        route_after_check,
        {
            "ask_missing_node":      "ask_missing_node",
            "product_search_node":   "product_search_node",
            "seller_search_node":    "seller_search_node",
            "product_analysis_node": "product_analysis_node",
            "chitchat_node":         "chitchat_node",
        },
    )

    # 4. 각 노드 → END (각 에이전트가 메시지를 직접 추가하므로 respond 노드 불필요)
    builder.add_edge("ask_missing_node",      END)
    builder.add_edge("product_search_node",   END)
    builder.add_edge("seller_search_node",    END)
    builder.add_edge("product_analysis_node", END)
    builder.add_edge("chitchat_node",         END)

    return builder.compile(checkpointer=checkpointer)


async def build_graph():
    """
    Checkpointer를 async로 초기화한 뒤 graph를 빌드해 반환.

    - DATABASE_URL 있음 → AsyncPostgresSaver (Supabase 영구 저장)
    - DATABASE_URL 없음 → MemorySaver (로컬 개발용 in-memory)

    FastAPI lifespan 또는 최초 1회 await로 호출:
        graph = await build_graph()
    """
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        import psycopg
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        # ainvoke/astream 사용 시 반드시 AsyncPostgresSaver 사용
        conn = await psycopg.AsyncConnection.connect(db_url, autocommit=True)
        checkpointer = AsyncPostgresSaver(conn)
        # 최초 1회 실행 시 checkpoints 테이블 자동 생성
        await checkpointer.setup()
        print("[Checkpointer] AsyncPostgresSaver (Supabase) 연결 완료")
    else:
        checkpointer = MemorySaver()
        print("[Checkpointer] MemorySaver (로컬 개발)")

    return _build_graph_with_checkpointer(checkpointer)


# =============================================================================
# STEP 11. 그래프 인스턴스 생성
#
# build_graph()가 async이므로 모듈 로드 시 직접 await 불가.
# → FastAPI lifespan / run_test() 내부에서 await build_graph()로 초기화.
#
# FastAPI 사용 예시:
#   from contextlib import asynccontextmanager
#   @asynccontextmanager
#   async def lifespan(app):
#       app.state.graph = await build_graph()
#       yield
# =============================================================================

# 모듈 직접 실행(테스트)이 아닌 import 시에는 graph를 None으로 유지
# FastAPI에서는 lifespan에서 초기화
graph = None


# =============================================================================
# STEP 12. 로컬 테스트용 실행 함수
#
# python LangGraph_orchestrator_agent.py 로 직접 실행해서 동작 확인 가능
# =============================================================================

async def run_test():
    # graph를 async로 초기화 (AsyncPostgresSaver or MemorySaver)
    g = await build_graph()

    # 테스트용 session (실제 서비스에서는 user_id + session_id를 조합)
    config = {"configurable": {"thread_id": "test_user:session_001"}} # 여기에 사용자 이름을 기입

    print("=" * 60)
    print("BuyerAgent 동적 전환 테스트")
    print("=" * 60)

    # 초기 State (첫 메시지)
    initial_state = {
        "session_id": "session_001",
        "user_id": "LEE",
        "messages": [HumanMessage(content="가볍고 슈팅이 좋은 나이키 10만원대 축구화 추천해줘")],
        "intent": "",
        "active_agent": None,
        "user_conditions": {},
        "missing_conditions": [],
        "search_result": [],
        "status": "extracting",
        "error": None,
        "retry_count": 0,
    }

    # 1턴: 제품 추천
    print("\n[1턴] 제품 추천 요청")
    result = await g.ainvoke(initial_state, config=config)
    print(f"active_agent: {result['active_agent']}")
    print(f"user_conditions: {result['user_conditions']}")
    last_message = result["messages"][-1]
    print(f"응답 미리보기: {last_message.content[:150]}...")

    # 2턴: 조건 보충 (포지션 답변) — intent가 product_search로 유지되어야 함
    print("\n[2턴] 조건 보충 답변 (intent 유지 테스트)")
    result2 = await g.ainvoke(
        {"messages": [HumanMessage(content="선호하는 포지션은 공격수야!")]},
        config=config,  # 같은 thread_id → 이전 state 자동 복원
    )
    print(f"active_agent: {result2['active_agent']}")
    print(f"user_conditions: {result2['user_conditions']}")
    last_message2 = result2["messages"][-1]
    print(f"응답 미리보기: {last_message2.content[:150]}...")


if __name__ == "__main__":
    import asyncio
    import sys
    # Windows: psycopg async는 ProactorEventLoop 미지원 → SelectorEventLoop 강제 설정
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_test())
