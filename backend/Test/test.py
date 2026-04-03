import os
import asyncio
import logging
from dotenv import load_dotenv
from contextlib import AsyncExitStack
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

# 로깅 설정: 터미널에서 진행 상황을 볼 수 있게 합니다.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
BRIGHT_DATA_API_KEY = os.environ["BRIGHT_DATA_API_KEY"]


async def main():
    # 1. 클라이언트 설정
    client = MultiServerMCPClient(
        {
            "brightdata": {
                "url": f"https://mcp.brightdata.com/mcp?token={BRIGHT_DATA_API_KEY}",
                "transport": "streamable_http",
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
        },
        # 테스트를 위해 무거운 sequential_thinking은 잠시 제외하거나
        # stdio 서버가 제대로 작동하는지 확인이 필요합니다.
    )

    async with AsyncExitStack() as stack:
        bri_session = await stack.enter_async_context(client.session("brightdata"))
        seq_session = await stack.enter_async_context(
            client.session("sequential_thinking")
        )

        bri_tools = await load_mcp_tools(bri_session, server_name="brightdata")
        seq_tools = await load_mcp_tools(seq_session, server_name="sequential_thinking")
        allowed_tool_names = {
            "scrape_as_markdown",
            "scrape_batch",
            "sequentialthinking",
        }

        tools = [*bri_tools, *seq_tools]
        tools = [t for t in tools if t.name in allowed_tool_names]
        prompt = """
        너는 Product Analysis Agent다.
        역할은 판매자 사이트의 상품 페이지에 접속해 상품 데이터를 수집하고, 사용자 조건에 맞게 비교/추천하는 것이다.

        사용 도구
        - scrape_as_markdown: 단일 URL 수집
        - scrape_batch: 여러 URL 일괄 수집
        - sequentialthinking: 비교 기준 정리 및 판단 보조

        규칙
        1. 페이지에서 확인한 정보만 사용한다. 추정하지 않는다.
        2. URL이 2개 이상이면 scrape_batch, 1개면 scrape_as_markdown을 사용한다.
        3. 수집 실패/불완전한 페이지는 scrape_as_markdown으로 재시도한다.
        4. 가격/재고/옵션은 변동 가능하므로 "페이지 기준"으로 설명한다.
        5. 각 상품마다 출처 URL을 반드시 포함한다.
        6. 현재 도구로 웹 검색은 불가하므로, 사용자가 URL을 주지 않으면 분석할 상품 URL을 요청한다.

        수집 필드 (가능한 범위)
        - 상품명
        - 브랜드
        - 모델명/코드
        - 가격(현재가/정가)
        - 배송비
        - 재고/판매상태
        - 옵션(사이즈/색상)
        - 판매자명
        - 상품 URL
        - 핵심 특징/스펙

        응답 방식
        - 한국어로 답변
        - 먼저 사용자 조건을 요약
        - 수집 결과를 표/리스트로 정리
        - 조건에 맞는 추천과 이유를 제시
        - 확인 불가 정보는 "확인 불가"로 표시
        """
        agent = create_agent(llm, tools=tools, system_prompt=prompt)
        result = await agent.ainvoke(
            {
                "messages": [
                    (
                        "user",
                        "https://soccerboom.co.kr/product/search.html?banner_action=&keyword=%EB%A8%B8%ED%81%90%EB%A6%AC%EC%96%BC+%EB%B2%A0%EC%9D%B4%ED%8D%BC 와  에서 머큐리얼 베이퍼 축구화 10만원대를 비교 및 분석해주세요.",
                    )
                ]
            }
        )
        print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
