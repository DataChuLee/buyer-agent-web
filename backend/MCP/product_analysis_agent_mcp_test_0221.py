import os
import asyncio
import logging
import traceback
from typing import Any
from contextlib import AsyncExitStack

from dotenv import load_dotenv
from langchain_core.tools.base import ToolException
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent


load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, timeout=120)

SESSION_START_TIMEOUT_SEC = int(os.getenv("SESSION_START_TIMEOUT_SEC", "120"))
TOOL_LOAD_TIMEOUT_SEC = int(os.getenv("TOOL_LOAD_TIMEOUT_SEC", "120"))
AGENT_INVOKE_TIMEOUT_SEC = int(os.getenv("AGENT_INVOKE_TIMEOUT_SEC", "900"))
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "20"))


def _configure_runtime_logging() -> None:
    # smithery/npx가 MCP JSON-RPC 시작 전 stdout에 설치 로그를 찍을 수 있음.
    # 이때 mcp stdio 클라이언트가 JSON 파싱 스택트레이스를 남기므로 노이즈를 줄인다.
    logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)


def _tool_error_handler(exc: Exception) -> str:
    message = str(exc)
    if "Cannot read properties of undefined" in message and "status" in message:
        return (
            "Firecrawl MCP 서버 내부 오류가 발생했습니다 (reading 'status'). "
            "단일 상품 상세 절대 URL로 다시 시도하거나 요청을 재실행해 주세요."
        )
    return f"Tool error: {message}"


def _format_startup_error(exc: Exception) -> str:
    message = str(exc)
    if "Connection closed" in message:
        return (
            "[STARTUP ERROR] MCP subprocess closed during initialize.\n"
            "- smithery/npx auto-install may have exited early\n"
            "- first run can take time; rerun once\n"
            "- verify Node.js / npx works: `npx -v`\n"
            "- if it still fails, run the same smithery command manually to inspect stderr"
        )
    return f"[STARTUP ERROR] {type(exc).__name__}: {message}"


def _make_tool_calls_non_fatal(tools: list[Any]) -> None:
    for tool in tools:
        # 도구 예외가 agent 전체 크래시로 전파되지 않도록 처리
        if hasattr(tool, "handle_tool_error"):
            tool.handle_tool_error = _tool_error_handler
        if hasattr(tool, "handle_validation_error"):
            tool.handle_validation_error = True


async def _wait_with_timeout(label: str, awaitable: Any, timeout_sec: int):
    print(f"[STEP] {label} (timeout={timeout_sec}s)", flush=True)
    try:
        # asyncio.wait_for() runs the awaitable in a separate task, which breaks
        # AnyIO/MCP cancel scopes when the awaited code enters async context managers.
        # asyncio.timeout() cancels in the current task, so enter/exit happen in the
        # same task and cleanup remains valid.
        async with asyncio.timeout(timeout_sec):
            result = await awaitable
        print(f"[OK] {label}", flush=True)
        return result
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"{label} timed out after {timeout_sec}s") from e


async def main():
    _configure_runtime_logging()
    print("[START] product_analysis_agent_mcp_test copy.py", flush=True)
    print(
        f"[ENV] FIRECRAWL_API_KEY={'set' if os.getenv('FIRECRAWL_API_KEY') else 'missing'}",
        flush=True,
    )
    print(
        f"[ENV] OPENAI_API_KEY={'set' if os.getenv('OPENAI_API_KEY') else 'missing'}",
        flush=True,
    )
    print(
        f"[CFG] SESSION_START_TIMEOUT_SEC={SESSION_START_TIMEOUT_SEC}, "
        f"TOOL_LOAD_TIMEOUT_SEC={TOOL_LOAD_TIMEOUT_SEC}, "
        f"AGENT_INVOKE_TIMEOUT_SEC={AGENT_INVOKE_TIMEOUT_SEC}, "
        f"AGENT_RECURSION_LIMIT={AGENT_RECURSION_LIMIT}",
        flush=True,
    )

    client = MultiServerMCPClient(
        {
            "firecrawl": {
                "transport": "stdio",
                "command": "npx.cmd",
                "args": [
                    "-y",
                    "@smithery/cli@latest",
                    "run",
                    "@Krieg2065/firecrawl-mcp-server",
                ],
                "env": {
                    **dict(os.environ),
                    "FIRECRAWL_API_KEY": os.environ["FIRECRAWL_API_KEY"],
                    "NO_COLOR": "1",
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
                "env": {**dict(os.environ), "NO_COLOR": "1"},
            },
        }
    )

    async with AsyncExitStack() as stack:
        fire_session = await _wait_with_timeout(
            "Open MCP session: firecrawl",
            stack.enter_async_context(client.session("firecrawl")),
            SESSION_START_TIMEOUT_SEC,
        )
        seq_session = await _wait_with_timeout(
            "Open MCP session: sequential_thinking",
            stack.enter_async_context(client.session("sequential_thinking")),
            SESSION_START_TIMEOUT_SEC,
        )

        fire_tools = await _wait_with_timeout(
            "Load MCP tools: firecrawl",
            load_mcp_tools(fire_session, server_name="firecrawl"),
            TOOL_LOAD_TIMEOUT_SEC,
        )
        seq_tools = await _wait_with_timeout(
            "Load MCP tools: sequential_thinking",
            load_mcp_tools(seq_session, server_name="sequential_thinking"),
            TOOL_LOAD_TIMEOUT_SEC,
        )

        allowed_tool_names = {
            "firecrawl_scrape",
            "firecrawl_batch_scrape",
            "sequentialthinking",
        }

        tools = [*fire_tools, *seq_tools]
        tools = [t for t in tools if t.name in allowed_tool_names]
        _make_tool_calls_non_fatal(tools)
        print(f"[INFO] Loaded tools: {[t.name for t in tools]}", flush=True)

        prompt = """
        너는 Product Analysis Agent다.

        [역할]
        - 판매자 웹사이트에서 상품 정보를 수집, 비교, 검증하여 구조화된 결과로 반환한다.
        - Firecrawl MCP는 페이지 수집/스크랩에 사용하고, sequential_thinking MCP는 수집 계획/검증/정리에 사용한다.
        - 추측하지 않는다. 확인되지 않은 값은 null 또는 "unknown"으로 표시한다.

        [사용 도구]
        - firecrawl_scrape: 단일 페이지 스크랩
        - firecrawl_batch_scrape: 여러 페이지 스크랩
        - sequential_thinking: 수집 순서 계획, 정보 충돌 점검, 결과 정리 (내부용)

        [핵심 규칙]
        1. 판매자 공식 사이트(동일 도메인) 중심으로만 수집한다. 사용자가 명시하지 않은 외부 사이트로 확장하지 않는다.
        2. 상품 상세 페이지를 우선 확인하고, 필요하면 배송/반품/보증/교환 정책 페이지도 확인한다.
        3. firecrawl_scrape와 firecrawl_batch_scrape의 url 필드에는 반드시 절대 URL(https://...)만 넣는다.
        - 자연어 문장, 한글 조사, 설명 텍스트, 상대경로를 url 필드에 넣지 않는다.
        4. URL이 불명확하거나 유효하지 않으면 Firecrawl 호출 전에 먼저 사용자에게 확인 질문을 한다.
        5. 가격/재고/옵션/주요 스펙/정책 정보는 가능한 한 출처 URL을 함께 남긴다.
        6. 정보가 모호하거나 페이지 간 값이 다르면 충돌 내용을 warnings에 명시한다.
        7. sequential_thinking의 내부 추론 과정은 출력하지 않는다. 최종 결과만 출력한다.

        [작업 절차]
        1. 사용자 요청에서 분석 대상 사이트 URL과 상품 조건(브랜드/모델/가격대)을 분리한다.
        2. 사이트 루트 URL만 주어진 경우:
        - 홈페이지/카테고리/검색 관련 페이지를 먼저 스크랩하여 후보 상품 링크를 찾는다.
        3. 후보 상품 페이지를 선별한 뒤, 필요 시 firecrawl_batch_scrape로 여러 상품 페이지를 수집한다.
        4. 배송/반품/보증 정책이 비교에 중요하면 관련 정책 페이지를 추가 스크랩한다.
        5. sequential_thinking으로 수집 결과를 정리하고 충돌 여부를 점검한다.
        """

        agent = create_agent(llm, tools=tools, system_prompt=prompt)
        print("[STEP] Agent invoke", flush=True)

        try:
            result = await _wait_with_timeout(
                "Agent invoke",
                agent.ainvoke(
                {
                    "messages": [
                        (
                            "user",
                            "https://www.crazy11.co.kr/ 에서 나이키 머큐리얼 베이퍼 10만원대 비교 및 분석해줘",
                        )
                    ]
                },
                config={"recursion_limit": AGENT_RECURSION_LIMIT},
                ),
                AGENT_INVOKE_TIMEOUT_SEC,
            )
            print(result["messages"][-1].content)
            print("[DONE]", flush=True)
        except ToolException as e:
            print(_tool_error_handler(e))
        except TimeoutError as e:
            print(f"[TIMEOUT] {e}", flush=True)
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(_format_startup_error(e), flush=True)
        traceback.print_exc()
