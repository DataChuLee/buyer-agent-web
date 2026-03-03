import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
# from langgraph.prebuilt import create_react_agent

load_dotenv()
SMITHERY_API_KEY = os.environ["SMITHERY_API_KEY"]
NAMESPACE = "stingray-C7LG"  # smithery namespace
CONNECTION_ID = "exa"  # smithery connectionId (해당 MCP ID)
llm = ChatOpenAI(model = 'gpt-4o-mini', temperature = 0)

async def main():
    client = MultiServerMCPClient(
            {
                "exa": {
                    "transport": "streamable_http",
                    "url": f"https://api.smithery.ai/connect/{NAMESPACE}/{CONNECTION_ID}/mcp",
                    "headers": {
                        "Authorization": f"Bearer {SMITHERY_API_KEY}",
                        "Content-Type": "application/json",
                    },
                },
                "sequential_thinking": {
                    "transport": "stdio",
                    "command": "npx.cmd",
                    "args": ["-y",
                            "@smithery/cli@latest",
                            "run",
                            "@kiennd/reference-servers"]            
                }
            }

        )

    async with AsyncExitStack() as stack:
        exa_session = await stack.enter_async_context(client.session("exa"))
        seq_session = await stack.enter_async_context(client.session("sequential_thinking"))

        exa_tools = await load_mcp_tools(exa_session, server_name="exa")
        seq_tools = await load_mcp_tools(seq_session, server_name="sequential_thinking")
        allowed_tool_names = {"web_search_exa", "sequentialthinking"}

        tools = [*exa_tools, *seq_tools]
        tools = [t for t in tools if t.name in allowed_tool_names]
        prompt = """
        너는 구매자를 대신해 판매자(셀러)를 탐색하고 1차 스크리닝하는 Seller Search Agent다.

        역할:
        - 후보 판매자를 찾는다.
        - 공개 웹 정보 기반으로 신뢰 신호를 수집한다.
        - 1차로 걸러낸 후보와 근거를 정리한다.

        사용 도구:
        - web_search_exa: 판매자 정보 검색 (스토어 페이지, 후기, 정책, 사업자 정보, 배송/반품 안내, 평판)
        - sequentialthinking: 탐색 기준 정리, 후보 필터링 순서 정리, 스크리닝 논리 구조화

        규칙:
        - 먼저 사용자 요구사항(제품/카테고리, 예산, 지역, 우선순위)을 짧게 정리한다.
        - 정보가 부족하면 꼭 필요한 질문만 1~2개 한다.
        - 정보가 충분하면 web_search_exa로 후보를 찾고, sequentialthinking으로 스크리닝 기준을 정리한 뒤 후보를 선별한다.
        - 추측하지 말고 검색 결과를 근거로 답한다.
        - sequentialthinking의 내부 JSON/메타정보는 출력하지 않는다.
        - 최종 답변은 자연어 텍스트로 작성한다.
        - 확정적 판단이 어려운 항목은 “추가 확인 필요”로 표시한다.

        판매자 스크리닝 기준(예시):
        - 판매 제품 적합성(원하는 제품/카테고리 취급 여부)
        - 가격 경쟁력(대략적인 가격대)
        - 배송/반품 정책 명확성
        - 판매자 신뢰 신호(리뷰, 운영 이력, 공식 스토어 여부 등)
        - 고객지원/문의 채널 존재 여부

        최종 답변 형식:
        1. 요구사항 요약
        2. 추천 판매자 후보 (우선 후보 + 대안 2~4개)
        3. 후보별 선택 이유 (장점/주의점)
        4. 근거 링크 (검색 출처)
        """

        agent = create_agent(llm, tools=tools, system_prompt=prompt)
        result = await agent.ainvoke({
            "messages": [("user", "나이키 머큐리얼 베이퍼 10만원대를 원하는데 크레이지 11이 해당 제품을 판매하는가?")]
        })
        print(result["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())

# async with client:   
#         tools = await client.get_tools()
#         allowed_tool_names = {"web_search_exa","sequentialthinking"}
#         tools = [t for t in tools if t.name in allowed_tool_names]
#         print([t.name for t in tools])
