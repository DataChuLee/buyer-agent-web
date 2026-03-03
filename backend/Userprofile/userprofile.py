from langgraph.prebuilt import create_react_agent
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import MemorySaver
from langmem import (
    create_manage_memory_tool,
    create_search_memory_tool,
    create_memory_manager,
    create_memory_store_manager,
)
from langchain_teddynote import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage
from langgraph.func import entrypoint
from langgraph.config import get_config
from langchain_core.runnables import RunnableConfig
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os


# Define profile structure
class UserProfile(BaseModel):
    """Represents the full representation of a user."""

    name: Optional[str] = None
    preferences_seller: Optional[str] = None
    preferences_product: Optional[str] = None
    preferences_price: Optional[str] = None
    preferences_category: Optional[str] = None
    preferences_size: Optional[str] = None
    preferences_age_group: Optional[str] = None
    preferences_ground_type: Optional[str] = None
    # preferences_negotiation: Optional[str] = None


def init_profile_manager(thread_id: str):
    # Set up store and models
    ## Cloud LLM 버전
    store = InMemoryStore(
        index={
            "dims": 1536,
            "embed": "openai:text-embedding-3-large",
        }
    )

    # Create profile manager
    manager = create_memory_store_manager(
        "gpt-4o",
        namespace=("users", "{thread_id}", "profile"),  # Isolate profiles by user
        schemas=[UserProfile],
        instructions="""Extract user profile information from the conversation.
특히 아래 필드들을 대화 중 언급될 때 자동으로 인식하고 저장해야 한다:
- preferences_seller: 사용자가 선호하거나 자주 언급하는 판매 사이트 또는 쇼핑몰 이름
- preferences_product: 사용자가 선호하는 구체적인 상품명 (예: "나이키 머큐리얼 베이퍼 AG")
- preferences_price: 사용자가 선호하는 가격대 (예: "20만원대")
- preferences_category: 상품의 일반 카테고리 (예: "축구화")
- preferences_ground_type: 운동화 등에서의 착용 환경 유형 (예: "AG", "FG" 등)
- preferences_size: 사용자가 선호하는 사이즈 (숫자 또는 단위 포함, 예: "270mm")
- preferences_age_group: 제품의 대상 연령층 (예: "성인용", "주니어용")""",
        enable_inserts=False,  # Update existing profile only
    )
    return store, manager


# # memory manager
# PROFILE_STORE, PROFILE_MANAGER = init_profile_manager(thread_id="bootstrap")
# PROFILE_MANAGER._store = PROFILE_STORE  # LangGraph runtime outside 대응


# def _memory_config(thread_id: str) -> dict:
#     return {"configurable": {"thread_id": thread_id}}


# def _profile_to_text(items) -> str:
#     if not items:
#         return "- 저장된 선호 정보 없음"
#     lines = []
#     for it in items[:5]:
#         value = getattr(it, "value", {})
#         content = value.get("content", value) if isinstance(value, dict) else value
#         if isinstance(content, dict):
#             for k, v in content.items():
#                 if v:
#                     lines.append(f"- {k}: {v}")
#     return "\n".join(lines) if lines else "- 저장된 선호 정보 없음"


# async def get_profile_context(question: str, thread_id: str) -> str:
#     items = await PROFILE_MANAGER.asearch(
#         query=question,
#         limit=5,
#         config=_memory_config(thread_id),
#     )
#     return _profile_to_text(items)
