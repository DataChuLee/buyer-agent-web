"""
product_analysis_agent.py
==========================
크롤링(crawl_and_index)과 RAG 검색(rag_search)을 도구로 가진 Product Analysis Agent.

흐름:
  User Query
      ↓
  ProductAnalysisAgent
      ├── crawl_and_index : 판매처 크롤링 → vectorstore upsert
      └── rag_search      : vectorstore 검색 → Markdown 비교표 생성
      ↓
  Final Answer
"""

import asyncio
import os
import sys

from dotenv import load_dotenv
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

load_dotenv()

# ── 경로 등록 ───────────────────────────────────────────────
AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(AGENT_DIR, ".."))
TOOLS_DIR = os.path.join(BACKEND_DIR, "Tools")

# Tools/, backend/ 를 sys.path 에 추가
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

# ── Tools import ────────────────────────────────────────────
# vectorstore_singleton 덕분에 import 경로와 무관하게 동일 인스턴스를 공유함.
# sys.modules alias 해킹 불필요.
from Tools.rag_search import rag_search
from Tools.crawl_and_index import crawl_and_index

# ── LLM ─────────────────────────────────────────────────────
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# ── System Prompt ────────────────────────────────────────────
SYSTEM_PROMPT = """
당신은 'Product Analysis Agent'입니다.
사용자가 원하는 축구화를 찾아 비교표 형태로 제공합니다.

🛠️ 사용 가능한 도구:
1. crawl_and_index
   - 지정한 판매처에서 실시간으로 축구화를 크롤링하고 인덱싱합니다.
   - 지원 판매처 (sellers 파라미터): crazy11, soccerboom, redsoccer, cafostore
    - sellers 파라미터는 리스트 형식으로 전달해야 합니다. -> sellers: list[str] -> ["crazy11", "soccerboom"] 형태로 전달
   - 사용자가 한국어 판매처명을 말해도 영문으로 변환하세요:
     크레이지11 → crazy11 / 사커붐 → soccerboom / 레드사커 → redsoccer / 카포스토어 → cafostore

2. rag_search
   - 인덱싱된 데이터에서 조건에 맞는 제품을 검색하고 Markdown 비교표를 생성합니다.
   - 사용자 쿼리 원문을 그대로 전달하세요.

💰 가격 범위 해석 규칙 (crawl_and_index의 min_price / max_price):
- N만원대       → min_price: N*10000,       max_price: (N+1)*10000 - 1
  예) 10만원대  → min_price: 100000,        max_price: 199999
  예) 15만원대  → min_price: 150000,        max_price: 159999
  예) 20만원대  → min_price: 200000,        max_price: 299999
- N만원 이상    → min_price: N*10000,       max_price: 999999
- N만원 이하    → min_price: 0,             max_price: N*10000
- 가격 언급 없음 → min_price: 0,            max_price: 999999

🔁 수행 절차:
1️⃣ 사용자 쿼리에서 판매처 / 키워드 / 가격 범위 추출
2️⃣ crawl_and_index 호출
3️⃣ rag_search 호출 (사용자 쿼리 원문 그대로 전달)
4️⃣ 비교표 반환

⚠️ 반드시 crawl_and_index → rag_search 순서로 호출하세요.

🚫 rag_search 쿼리 금지 사항:
- 사용자가 명시하지 않은 조건(FG, AG, TF, 축구화, 풋살화 등)을 임의로 추가하지 마세요.
- 사용자 원문에 없는 조건을 추가하면 검색 결과가 의도치 않게 필터링됩니다.
- 예) 사용자가 "머큐리얼 베이퍼 10만원대"라고 했으면 → "머큐리얼 베이퍼 10만원대"만 전달.
"""

# ── Agent 구성 ───────────────────────────────────────────────
analysis_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("placeholder", "{chat_history}"),
        ("human", "{input}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

analysis_tools = [crawl_and_index, rag_search]
analysis_agent = create_tool_calling_agent(llm, analysis_tools, analysis_prompt)
analysis_agent_executor = AgentExecutor(
    agent=analysis_agent,
    tools=analysis_tools,
    verbose=True,
)


# ── 프로필 컨텍스트 헬퍼 ─────────────────────────────────────
def _build_profile_context(user_profile: dict | None) -> str:
    if not user_profile:
        return ""
    lines = []
    labels = {
        "brand": "선호 브랜드",
        "budget": "예산",
        "surface": "선호 지면",
        "position": "포지션",
        "age_group": "연령대",
    }
    for key, label in labels.items():
        if user_profile.get(key):
            lines.append(f"- {label}: {user_profile[key]}")
    if user_profile.get("physical_traits"):
        lines.append(f"- 신체 특성: {', '.join(user_profile['physical_traits'])}")
    if user_profile.get("play_style"):
        lines.append(f"- 플레이 스타일: {', '.join(user_profile['play_style'])}")
    return "\n".join(lines)


# ── 실행 함수 ────────────────────────────────────────────────
async def product_analysis_agent(query: str, user_profile: dict = None) -> str:
    profile_context = _build_profile_context(user_profile)
    full_input = (
        f"{query}\n\n[유저 프로필 참고 — 비교표 설명에 개인화 반영]\n{profile_context}"
        if profile_context
        else query
    )
    response = await analysis_agent_executor.ainvoke({"input": full_input})
    return response["output"]


# ── 테스트 ────────────────────────────────────────────────────
if __name__ == "__main__":

    async def test():
        result = await product_analysis_agent(
            "크레이지11에서 머큐리얼 베이퍼 성인용 TF 사이즈 270 10만원대 추천해줘"
        )
        print(result)

    asyncio.run(test())
