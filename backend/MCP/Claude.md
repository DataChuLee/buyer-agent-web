# MCP 폴더

## 역할
Model Context Protocol(MCP) 기반 도구 연동. 에이전트가 MCP 서버를 통해 외부 도구 호출.

## 주요 파일
- `mcp_tool.py` → MCP 도구 래퍼 (3.4KB)

## 테스트 파일 (참고용)
- `product_analysis_agent_mcp_test.py`
- `product_analysis_agent_mcp_test_0221.py`
- `product_search_agent_mcp_test.py`
- `seller_search_agent_mcp_test.py`

## 의존성
- `langchain-mcp-adapters`
- `mcp==1.26.0`
