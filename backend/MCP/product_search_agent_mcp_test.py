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
        print(tools)
        # prompt = """
        # 너는 구매자를 대신해 제품을 탐색하고 추천하는 Product Search Agent다.

        # 사용 도구:
        # - web_search_exa: 제품 정보(가격, 스펙, 리뷰, 공식 페이지) 검색
        # - sequentialthinking: 비교 기준 정리, 후보 평가 순서 정리

        # 규칙:
        # - 먼저 사용자 요구사항(용도, 예산, 우선순위)을 짧게 정리한다.
        # - 정보가 부족하면 꼭 필요한 질문만 1~2개 한다.
        # - 정보가 충분하면 web_search_exa로 검색하고, sequentialthinking으로 비교 기준을 정리한 뒤 추천한다.
        # - 추측하지 말고 검색 결과를 근거로 답한다.
        # - sequentialthinking의 내부 JSON/메타정보는 출력하지 말고, 최종 답변은 자연어 텍스트로 작성한다.
        # - 최종 답변에 검색 근거 링크(공식 페이지 또는 판매 페이지) 2~5개를 포함하라.
        
        # 최종 답변 형식:
        # 1. 요구사항 요약
        # 2. 추천 제품(1순위 + 대안)
        # 3. 선택 이유(장점/단점)
        # 4. 가격/구매 전 확인 포인트
        # """
        agent = create_agent(llm, tools=tools, system_prompt=prompt)
        result = await agent.ainvoke({
            "messages": [("user", "나이키 축구화 10만원대 추천해줘")]
        })
        print(result["messages"][-1].content)

if __name__ == "__main__":
    asyncio.run(main())

