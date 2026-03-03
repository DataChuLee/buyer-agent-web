import re
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from Agent.sub_agent import (
    product_search_agent,
    seller_search_agent,
    product_analysis_agent,
)
from Chain.general_chat_chain import general_chat
from Chain.intent_chain import classify_intent

# orchestrator_agent -> 의도 분류 + general_chat + userprofile memory 반영
## userprofile memory -> supabase에 있는 User DB에 있는 사용자 이름을 thread_id로 해야됨
## 비동기로 처리

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


async def orchestrator_agent(query: str) -> dict:

    topic = (await classify_intent(query=query)).strip().lower()
    if topic not in {
        "general_chat",
        "product_search",
        "seller_search",
        "product_analysis",
    }:
        topic = "general_chat"

    if topic == "general_chat":
        answer = await general_chat(query=query)
        agent = "orchestrator_general"
    elif topic == "product_search":
        answer = await product_search_agent(query=query)
        agent = "product_search_agent"
    elif topic == "seller_search":
        answer = await seller_search_agent(query=query)
        agent = "seller_search_agent"
    else:
        answer = await product_analysis_agent(query=query)
        agent = "product_analysis_agent"

    return {
        "response": answer,
        "agent": agent,
        "intent": topic,
    }
