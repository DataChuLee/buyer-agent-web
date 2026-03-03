import os
import asyncio
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote
from dotenv import load_dotenv
from contextlib import AsyncExitStack

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

# from langgraph.prebuilt import create_react_agent
logging.basicConfig(level=logging.DEBUG)
for name in ["mcp", "httpx", "httpcore", "langchain_mcp_adapters"]:
    logging.getLogger(name).setLevel(logging.DEBUG)

load_dotenv()
SMITHERY_API_KEY = os.environ["SMITHERY_API_KEY"]
NAMESPACE = "stingray-C7LG"  # smithery namespace
CONNECTION_ID = "playwright-mcp-MtpW"  # smithery connectionId (해당 MCP ID)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)


async def main():
    client = MultiServerMCPClient(
        {
            "playwright": {
                "transport": "streamable_http",
                "url": f"https://api.smithery.ai/connect/{NAMESPACE}/{CONNECTION_ID}/mcp",
                "headers": {
                    "Authorization": f"Bearer {SMITHERY_API_KEY}",
                },
                "terminate_on_close": False,
            },
            "sequential_thinking": {
                "transport": "stdio",
                "command": "npx.cmd",
                "args": [
                    "-y",
                    "@smithery/cli@latest",
                    "run",
                    "@kiennd/reference-servers",
                ],
            },
        }
    )

    async with AsyncExitStack() as stack:
        play_session = await stack.enter_async_context(client.session("playwright"))
        seq_session = await stack.enter_async_context(
            client.session("sequential_thinking")
        )
        play_tools = await load_mcp_tools(play_session, server_name="playwright")
        seq_tools = await load_mcp_tools(seq_session, server_name="sequential_thinking")

        tools = [*play_tools, *seq_tools]
        print([t for t in tools if t.name])


if __name__ == "__main__":
    asyncio.run(main())
#         prompt = """
#         너는 구매자를 대신해 제품을 탐색하고 추천하는 Product Search Agent다.

#         사용 도구:
#         - web_search_exa: 제품 정보(가격, 스펙, 리뷰, 공식 페이지) 검색
#         - sequentialthinking: 비교 기준 정리, 후보 평가 순서 정리

#         규칙:
#         - 먼저 사용자 요구사항(용도, 예산, 우선순위)을 짧게 정리한다.
#         - 정보가 부족하면 꼭 필요한 질문만 1~2개 한다.
#         - 정보가 충분하면 web_search_exa로 검색하고, sequentialthinking으로 비교 기준을 정리한 뒤 추천한다.
#         - 추측하지 말고 검색 결과를 근거로 답한다.
#         - sequentialthinking의 내부 JSON/메타정보는 출력하지 말고, 최종 답변은 자연어 텍스트로 작성한다.
#         - 최종 답변에 검색 근거 링크(공식 페이지 또는 판매 페이지) 2~5개를 포함하라.

#         최종 답변 형식:
#         1. 요구사항 요약
#         2. 추천 제품(1순위 + 대안)
#         3. 선택 이유(장점/단점)
#         4. 가격/구매 전 확인 포인트
#         """
#         agent = create_agent(llm, tools=tools, system_prompt=prompt)
#         result = await agent.ainvoke({
#             "messages": [("user", "나이키 축구화 10만원대 추천해줘")]
#         })
#         print(result["messages"][-1].content)

# if __name__ == "__main__":
#     asyncio.run(main())
