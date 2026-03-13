import asyncio
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent

load_dotenv()
SMITHERY_API_KEY = os.environ["SMITHERY_API_KEY"]
NAMESPACE = "stingray-C7LG"  # smithery namespace
CONNECTION_ID = "exa"  # smithery connectionId (?대떦 MCP ID)


@tool
async def search_mcp():
    """Exa 검색과 Sequential Thinking MCP 도구를 로드하여 반환합니다."""
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
                "args": [
                    "-y",
                    "@smithery/cli@latest",
                    "run",
                    "@kiennd/reference-servers",
                ],
                "env": {
                    **os.environ,
                    "NO_COLOR": "1",
                    "FORCE_COLOR": "0",
                },
            },
        }
    )

    async with AsyncExitStack() as stack:
        exa_session = await stack.enter_async_context(client.session("exa"))
        seq_session = await stack.enter_async_context(
            client.session("sequential_thinking")
        )

        exa_tools = await load_mcp_tools(exa_session, server_name="exa")
        seq_tools = await load_mcp_tools(seq_session, server_name="sequential_thinking")
        allowed_tool_names = {"web_search_exa", "sequentialthinking"}

        tools = [*exa_tools, *seq_tools]
        tools = [t for t in tools if t.name in allowed_tool_names]

        return tools
