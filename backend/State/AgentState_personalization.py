from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


IntentType = Literal[
    "product_search",
    "seller_search",
    "product_analysis",
    "product_guide",
    "purchase_prepare",
    "chitchat",
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


class UserProfile(BaseModel):
    name: str | None = Field(None, description="User name")
    brand: str | None = Field(None, description="Preferred brand")
    budget: str | None = Field(None, description="Preferred budget")
    surface: str | None = Field(None, description="Preferred playing surface")
    position: str | None = Field(None, description="Playing position")
    age_group: str | None = Field(None, description="Age group")
    product_name: str | None = Field(None, description="Recently discussed product")
    seller: str | None = Field(None, description="Preferred seller")
    physical_traits: list[str] = Field(default_factory=list, description="Physical traits")
    play_style: list[str] = Field(default_factory=list, description="Play style")


class BuyerAgentStateV2(TypedDict):
    session_id: str
    user_id: str
    request_id: str | None
    messages: Annotated[list, add_messages]

    intent: IntentType
    active_agent: IntentType | None

    user_conditions: dict
    missing_conditions: list[str]
    search_result: list[SearchResultItem]

    status: StatusType
    error: str | None
    retry_count: int

    user_profile: dict | None

    question_options: list[str] | None
    question_sequence: list[dict] | None

    products: list[dict] | None
    sellers: list[dict] | None
    analysis: list[dict] | None
    crawled_context: dict | None

    # 최신 응답에는 노출하지 않지만, "첫 번째 제품", "저 제품" 같은 후속 참조를
    # 실제 카드명으로 해석하기 위해 체크포인트에 보관한다.
    last_products: list[dict] | None
    last_sellers: list[dict] | None
    last_analysis: list[dict] | None

    # 분석 후속 질문("다른 건 없어?") 시 이미 보여준 제품을 제외하기 위한 누적 키("seller|name").
    # 체크포인트 state 에만 보관되는 내부 필드(응답 스키마 비노출).
    shown_product_keys: list[str]

    selected_product: dict | None
    purchase_status: str | None
    purchase_missing_fields: list[str]
    shipping_info: dict | None
    checkout_session: dict | None

    requested_capabilities: list[str]
    past_steps: list[str]
    selected_series: str | None
    selected_series_card: dict | None
    selected_seller: dict | None
    rejected_series: list[str]
    rejected_sellers: list[str]
    rejected_product_keys: list[str]
    orchestration_retry_count: int
