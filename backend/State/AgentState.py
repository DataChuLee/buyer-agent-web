# =============================================================================
# BuyerAgentState — 동적 에이전트 전환 구조
#
# 핵심 설계 원칙:
#   매 사용자 메시지마다 오케스트레이터가 intent를 재판단하고,
#   전환이 감지되면 이전 에이전트의 search_result를 다음 에이전트에 인계한다.
#
# 대화 흐름 예시:
#   사용자: "나이키 10만원대 추천해줘"
#     → intent: product_search → product_search_agent 실행
#     → search_result: [{"name": "머큐리얼 클럽", ...}] 저장
#
#   사용자: "머큐리얼 클럽 어디서 살 수 있어?"
#     → intent: seller_search (전환 감지)
#     → active_agent 변경
#     → 이전 search_result를 seller_search_agent에 자동 인계
#
#   사용자: "사이즈가 어떻게 돼?"
#     → intent: seller_search (유지)
#     → 같은 에이전트 계속 대화
# =============================================================================

from __future__ import annotations

from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


# =============================================================================
# STEP 1. Intent 타입 정의
#
# 오케스트레이터가 매 턴마다 사용자 메시지를 보고 아래 4가지 중 하나로 분류한다.
# Literal을 쓰는 이유: str보다 명확하고 IDE에서 자동완성 + 오타 방지
# =============================================================================

IntentType = Literal[
    "product_search",    # 제품 추천 요청 ("나이키 축구화 추천해줘")
    "seller_search",     # 판매처 탐색 요청 ("어디서 살 수 있어?")
    "product_analysis",  # 제품 비교/분석 요청 ("이 두 개 비교해줘")
    "chitchat",          # 일상 대화 ("안녕!", "고마워")
]


# =============================================================================
# STEP 2. 에이전트 상태(Status) 타입 정의
#
# 현재 그래프가 어느 단계에 있는지를 나타낸다.
# status를 세분화해야 에러 복구, 재시도, 디버깅이 가능하다.
#
# 흐름:
#   extracting → checking → searching → responding → done
#                    ↓
#               waiting_input (조건 부족 시 interrupt)
#                    ↓
#               extracting (사용자 답변 후 resume)
# =============================================================================

StatusType = Literal[
    "extracting",     # 사용자 메시지에서 조건 파싱 중
    "checking",       # 조건이 충분한지 판단 중
    "searching",      # 서브에이전트 실행 중
    "responding",     # 최종 응답 생성 중
    "waiting_input",  # interrupt — 사용자 추가 입력 대기
    "error",          # 에러 발생 (재시도 or 사용자 안내)
    "done",           # 해당 턴 완료
]


# =============================================================================
# STEP 3. 검색 결과 아이템 타입 정의
#
# 기존: search_result: str  ← 통짜 문자열, 파싱/필터링 불가
# 변경: search_result: list[SearchResultItem]  ← 구조화된 데이터
#
# 이렇게 해야:
#   - seller_search가 product_search 결과에서 제품명을 꺼내 쿼리로 쓸 수 있다
#   - product_analysis가 특정 제품만 필터링해 비교할 수 있다
# =============================================================================

class SearchResultItem(TypedDict):
    name: str          # 제품명 또는 판매처명
    description: str   # 설명 / 특징
    price: str         # 가격 (예: "129,000원") — int 아닌 str로 유연하게
    url: str           # 상품 링크 또는 판매처 링크
    source: str        # 어느 에이전트가 생성했는지 ("product_search" | "seller_search" 등)


# =============================================================================
# STEP 4. 메인 State 정의
#
# LangGraph는 노드 간에 이 State 객체를 공유한다.
# 각 노드는 State의 일부를 읽고, 변경된 부분만 반환(return)한다.
# =============================================================================

class BuyerAgentState(TypedDict):

    # -------------------------------------------------------------------------
    # [식별 정보] — 멀티유저 SaaS의 핵심
    #
    # session_id: 하나의 대화 세션 (브라우저 탭 하나 = 세션 하나)
    # user_id:    어느 유저인지 식별 (다른 유저의 state에 접근 불가)
    #
    # LangGraph checkpointer는 thread_id로 state를 저장하는데,
    # thread_id = f"{user_id}:{session_id}" 조합으로 사용한다.
    # -------------------------------------------------------------------------
    session_id: str
    user_id: str

    # -------------------------------------------------------------------------
    # [대화 이력]
    #
    # add_messages: LangGraph 내장 reducer.
    # 새 메시지를 기존 리스트에 append해준다. (덮어쓰지 않음)
    # -------------------------------------------------------------------------
    messages: Annotated[list, add_messages]

    # -------------------------------------------------------------------------
    # [의도 & 에이전트 전환의 핵심]
    #
    # intent:        오케스트레이터가 매 턴 판단하는 현재 사용자 의도
    # active_agent:  현재 대화 중인 에이전트 (전환 감지의 기준점)
    #
    # 전환 감지 로직:
    #   if intent != active_agent:
    #       → 에이전트 전환 발생
    #       → 이전 search_result를 다음 에이전트에 인계
    #       → active_agent = intent 로 업데이트
    # -------------------------------------------------------------------------
    intent: IntentType
    active_agent: IntentType | None  # 처음엔 None, 첫 에이전트 진입 시 설정됨

    # -------------------------------------------------------------------------
    # [조건 누적]
    #
    # user_conditions: 매 턴마다 누적되는 사용자 조건
    #   예: {"brand": "나이키", "budget": "10만원대", "surface": "인조잔디"}
    #
    # missing_conditions: 현재 어떤 조건이 부족한지 명시
    #   예: ["budget", "surface"]
    #   → check_conditions 노드가 이 리스트를 보고 interrupt 여부 결정
    #   → 비어있으면 조건 충분 → 에이전트 실행
    # -------------------------------------------------------------------------
    user_conditions: dict
    missing_conditions: list[str]

    # -------------------------------------------------------------------------
    # [검색 결과 — 에이전트 간 컨텍스트 인계의 핵심]
    #
    # 기존 str 대신 구조화된 list[SearchResultItem]으로 저장.
    #
    # 인계 시나리오:
    #   product_search 완료 → search_result: [{"name": "머큐리얼 클럽", ...}]
    #   seller_search 시작  → state["search_result"]에서 name을 꺼내 쿼리로 사용
    #                         "머큐리얼 클럽 축구화 판매처 검색"
    # -------------------------------------------------------------------------
    search_result: list[SearchResultItem]

    # -------------------------------------------------------------------------
    # [흐름 제어]
    #
    # status:      현재 그래프 단계 (디버깅, 프론트 로딩 표시에 활용)
    # error:       에러 메시지 (None이면 정상)
    # retry_count: 외부 API 실패 시 재시도 횟수 추적 (최대 3회)
    # -------------------------------------------------------------------------
    status: StatusType
    error: str | None
    retry_count: int
