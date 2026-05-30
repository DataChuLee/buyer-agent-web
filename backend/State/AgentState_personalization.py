from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


IntentType = Literal[
    "product_search",
    "seller_search",
    "product_analysis",
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

    selected_product: dict | None
    purchase_status: str | None
    purchase_missing_fields: list[str]
    shipping_info: dict | None
    checkout_session: dict | None
