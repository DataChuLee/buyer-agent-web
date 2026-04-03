# =============================================================================
# AgentState_personalization.py — LangMem 기반 Hybrid Memory 버전 State 정의
#
# 기존 AgentState.py와의 차이:
#   - UserProfile: TypedDict → Pydantic BaseModel
#     이유: LangMem의 create_memory_store_manager는 Pydantic 스키마를 받음
#          → LLM이 대화에서 자동으로 UserProfile 필드를 추출/업데이트
#
#   - BuyerAgentStateV2에 user_profile 필드 추가
#     · None = 아직 로드 안 됨 (첫 턴 판단 기준)
#     · dict = LangGraph Store에서 로드된 프로필
#
# [LangMem Hybrid Memory 설계]
#   기존(수동 방식):
#     _extract_soft_preferences() → LLM 직접 호출, 비정형 추출
#     _upsert_profile_to_supabase() → SQL 직접 작성
#
#   LangMem 방식 (이 파일):
#     create_memory_store_manager() → 대화에서 UserProfile 자동 추출/업데이트
#     store.asearch() → UserProfile 자동 로드
#     → 구조화(brand, budget) + 비정형(physical_traits, play_style) 한 모델로 통합
#
# [참고]
#   https://langchain-ai.github.io/langmem/guides/manage_user_profile/
# =============================================================================

from __future__ import annotations

from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


# =============================================================================
# 기존 타입 재정의 (AgentState.py와 동일, 독립적으로 사용 가능하도록)
# =============================================================================

IntentType = Literal[
    "product_search",  # 제품 추천 요청
    "seller_search",  # 판매처 탐색 요청
    "product_analysis",  # 제품 비교/분석 요청
    "chitchat",  # 일상 대화
]

StatusType = Literal[
    "extracting",
    "checking",
    "searching",
    "responding",
    "waiting_input",
    "error",
    "done",
]


class SearchResultItem(TypedDict):
    name: str
    description: str
    price: str
    url: str
    source: str


# =============================================================================
# [NEW] UserProfile — LangMem이 자동 관리하는 유저 프로필 스키마
#
# Pydantic BaseModel을 사용하는 이유:
#   create_memory_store_manager(schemas=[UserProfile])에 전달하면
#   LangMem이 대화를 분석해 각 필드를 자동으로 추출·업데이트해줌
#
# 필드 설계 전략:
#   구조화 필드 (brand, budget, surface, ...)
#     → 기존 user_conditions와 동일, 세션 간 유지
#
#   비정형 필드 (physical_traits, play_style)
#     → 기존에는 별도 LLM 호출로 수동 추출했던 soft_preferences
#     → LangMem이 자동으로 채워줌 (별도 추출 로직 불필요)
#
# enable_inserts=False 전략:
#   → 유저당 프로필 1개 유지 (insert가 아닌 update)
#   → 매 대화마다 기존 프로필에 새 정보를 누적
# =============================================================================


class UserProfile(BaseModel):
    """LangMem이 대화에서 자동 추출·업데이트하는 축구화 구매 유저 프로필."""

    # 구조화 선호도 (기존 user_conditions와 대응)
    brand: str | None = Field(None, description="선호 브랜드. 예: 나이키, 아디다스")
    budget: str | None = Field(
        None, description="선호 예산대. 예: 10만원대, 20만원 이하"
    )
    surface: str | None = Field(
        None, description="주 경기 지면. 예: AG, FG, TF, 인조잔디"
    )
    position: str | None = Field(
        None, description="포지션. 예: 공격수, 미드필더, 수비수"
    )
    age_group: str | None = Field(None, description="연령대. 예: 성인, 유소년")
    product_name: str | None = Field(
        None, description="최근 관심 제품명. 예: 머큐리얼 베이퍼"
    )
    seller: str | None = Field(None, description="선호 판매처. 예: 크레이지11, 사커붐")

    # 비정형 선호도 (기존에 별도 LLM 호출로 추출하던 soft_preferences)
    physical_traits: list[str] = Field(
        default_factory=list,
        description="신체적 특성. 예: ['발볼이 넓음', '발등이 높음', '무릎 부상 경험']",
    )
    play_style: list[str] = Field(
        default_factory=list,
        description="플레이 스타일/환경. 예: ['스피드 플레이 선호', '야간 경기 위주', '11인제 위주']",
    )


# =============================================================================
# [NEW] BuyerAgentStateV2 — 개인화 필드 추가된 State
#
# 기존 BuyerAgentState와의 차이:
#   + user_profile: LangGraph Store에서 로드한 UserProfile dict
#     - None = 아직 로드 안 됨 → load_user_memory 실행 트리거
#     - {} = 로드 완료, 신규 유저
#     - {...} = 로드 완료, 기존 유저 프로필 있음
# =============================================================================


class BuyerAgentStateV2(TypedDict):

    # ── 식별 정보 ────────────────────────────────────────────────────────────
    session_id: str
    user_id: str

    # ── 대화 이력 ────────────────────────────────────────────────────────────
    messages: Annotated[list, add_messages]

    # ── 의도 & 에이전트 전환 ─────────────────────────────────────────────────
    intent: IntentType
    active_agent: IntentType | None

    # ── 조건 누적 ────────────────────────────────────────────────────────────
    user_conditions: dict
    missing_conditions: list[str]

    # ── 검색 결과 ────────────────────────────────────────────────────────────
    search_result: list[SearchResultItem]

    # ── 흐름 제어 ────────────────────────────────────────────────────────────
    status: StatusType
    error: str | None
    retry_count: int

    # ── [NEW] LangMem 기반 유저 프로필 ───────────────────────────────────────
    #
    # user_profile:
    #   - LangGraph Store에서 로드한 UserProfile의 dict 표현
    #   - None = 아직 로드 안 됨 (load_user_memory 실행 트리거)
    #   - {} = 신규 유저 (저장된 프로필 없음)
    #   - {"brand": "나이키", "physical_traits": ["발볼 넓음"], ...} = 기존 유저
    #
    # soft_preferences 필드 제거:
    #   → UserProfile.physical_traits + UserProfile.play_style로 통합
    #   → LangMem이 자동 관리하므로 별도 필드 불필요
    # ─────────────────────────────────────────────────────────────────────────
    user_profile: dict | None

    # ── [NEW] UI 선택지 옵션 ─────────────────────────────────────────────────
    # ask_missing_node가 구조화 질문을 할 때 프론트엔드에 전달할 선택지 목록
    # None = 자유 텍스트 응답, list = 버튼/카드로 렌더링
    # ─────────────────────────────────────────────────────────────────────────
    question_options: list[str] | None

    # ── [NEW] 구조화 제품 목록 ───────────────────────────────────────────────
    # product_search_node가 텍스트 응답을 파싱해 구조화한 카드 데이터
    # [{"name": "...", "features": "...", "recommendation": "...", "price": "...", "url": "..."}]
    # ─────────────────────────────────────────────────────────────────────────
    products: list[dict] | None

    # ── [NEW] 구조화 판매처 목록 ─────────────────────────────────────────────
    # seller_search_node가 텍스트 응답을 파싱해 구조화한 카드 데이터
    # [{"name": "...", "description": "...", "url": "..."}]
    # ─────────────────────────────────────────────────────────────────────────
    sellers: list[dict] | None

    # ── [NEW] 남은 질문 시퀀스 ───────────────────────────────────────────────
    # 프론트엔드가 로컬에서 조건 수집을 순서대로 진행할 수 있도록
    # 아직 묻지 않은 모든 질문 목록을 한 번에 반환
    # 예: [{"key": "budget", "question": "예산은?", "options": [...]}, ...]
    # ─────────────────────────────────────────────────────────────────────────
    question_sequence: list[dict] | None

    # ── [NEW] 구조화 제품 분석 목록 ──────────────────────────────────────────
    # product_analysis_node가 텍스트 응답을 파싱해 구조화한 카드 데이터
    # [{"name": "...", "seller": "...", "price": "...", "size": "...",
    #   "features": [...], "image": "...", "url": "..."}]
    # ─────────────────────────────────────────────────────────────────────────
    analysis: list[dict] | None
