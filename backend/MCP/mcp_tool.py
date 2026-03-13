import asyncio
import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

load_dotenv()
NAMESPACE = "stingray-C7LG"  # smithery namespace
CONNECTION_ID = "exa"  # smithery connectionId (Exa MCP ID)

ALLOWED_TOOL_NAMES = {"web_search_exa", "sequentialthinking"}


def get_npx_command() -> str:
    """
    운영체제에 따라 npx 실행 파일명을 반환합니다.
    Windows면 npx.cmd, 그 외면 npx 사용.
    """
    return "npx.cmd" if os.name == "nt" else "npx"


def build_mcp_client() -> MultiServerMCPClient:
    return MultiServerMCPClient(
        {
            "exa": {
                "transport": "streamable_http",
                "url": f"https://api.smithery.ai/connect/{NAMESPACE}/{CONNECTION_ID}/mcp",
                "headers": {
                    "Content-Type": "application/json",
                },
            },
            "sequential_thinking": {
                "transport": "stdio",
                "command": get_npx_command(),
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-sequential-thinking",
                ],
                "env": {
                    **os.environ,
                    "NO_COLOR": "1",
                    "FORCE_COLOR": "0",
                    "DISABLE_THOUGHT_LOGGING": "true",
                },
            },
        }
    )


@asynccontextmanager
async def get_search_mcp_tools():
    """
    MCP 세션이 살아있는 동안 사용할 수 있는 실제 MCP 도구 목록을 제공합니다.
    이 context를 벗어나면 세션이 닫히므로 tools를 밖으로 빼서 재사용하면 안 됩니다.
    """
    client = build_mcp_client()

    async with AsyncExitStack() as stack:
        exa_session = await stack.enter_async_context(client.session("exa"))
        seq_session = await stack.enter_async_context(
            client.session("sequential_thinking")
        )

        exa_tools = await load_mcp_tools(exa_session, server_name="exa")
        seq_tools = await load_mcp_tools(seq_session, server_name="sequential_thinking")

        tools = [*exa_tools, *seq_tools]
        tools = [tool for tool in tools if tool.name in ALLOWED_TOOL_NAMES]

        if not tools:
            raise RuntimeError(
                "로드된 MCP 도구가 없습니다. "
                "Smithery 연결, API 키, MCP 서버 이름, allowed tool names를 확인하세요."
            )

        yield tools


async def test():
    async with get_search_mcp_tools() as tools:
        print("최종 로드된 툴 개수:", len(tools))
        print("최종 로드된 툴 이름:", [t.name for t in tools])


if __name__ == "__main__":
    asyncio.run(test())
