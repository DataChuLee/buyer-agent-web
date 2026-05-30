# 인터뷰 형식
- 작업을 수행하는 과정에서 모르거나 애매한 게 있으면 인터뷰 형식 (카드 형식)으로 질문해주세요.

---

# Buyer Agent SaaS - Backend

## Overview
LangGraph + FastAPI 기반 AI 쇼핑 에이전트. 사용자 조건 수집 → 상품/판매자 크롤링 → RAG 검색 → 분석 결과 반환.

## Entry Point
- 실행: `uvicorn FastAPI.main:app --reload`
- API 서버: `FastAPI/main.py` (현재 버전)
- 구버전: `main.py` (레거시, 수정 X)

## Tech Stack
- Agent: LangGraph + LangMem (개인화)
- LLM: Claude (Anthropic)
- API: FastAPI + SSE 스트리밍
- Vector DB: ChromaDB (RAG)
- Scraping: Playwright, Selenium, Firecrawl
- Korean NLP: KoNLPy, Kiwi

## Architecture

```mermaid
flowchart TD
    User([사용자]) -->|ChatRequest\nuser_id, session_id, message| API

    subgraph API["FastAPI (main.py)"]
        CHAT[POST /chat]
        STREAM[POST /chat/stream · SSE]
    end

    API -->|graph.ainvoke / astream_events| GRAPH

    subgraph GRAPH["LangGraph 메인 그래프"]
        S([START]) --> LM[load_user_memory\n첫 턴만]
        LM --> EX[extract_conditions_and_intent\ngpt-4o-mini · 구조화 출력]
        EX --> CH[check_conditions\n의도별 필수 조건 검증]

        CH -->|조건 부족| ASK[ask_missing_node\n질문 + UI 옵션 반환]
        CH -->|chitchat| CC[chitchat_node\nClaude LLM]
        CH -->|product_search| PS[product_search_node]
        CH -->|seller_search| SS[seller_search_node]
        CH -->|product_analysis| PA[product_analysis_node]

        PS & SS & PA --> SV[save_user_memory\nLangMem 자동 추출]

        ASK --> E([END])
        CC  --> E
        SV  --> E
    end

    subgraph AGENTS["Sub-Agents (LangChain ReAct · gpt-4o-mini)"]
        PSA[product_search_agent]
        SSA[seller_search_agent]
        PAA[product_analysis_agent]
    end

    subgraph TOOLS["Tools"]
        T1[product_recommend\nTavily Search]
        T2[site_search\nTavily Search]
        T3[crawl_and_index\nPlaywright / Selenium\ncrazy11 · soccerboom · redsoccer · cafostore]
        T4[rag_search\nChromaDB RAG]
    end

    subgraph STORE["영속성"]
        DB1[(Supabase\nCheckpointer\n대화 기록)]
        DB2[(Supabase\nStore\n유저 프로필)]
        DB3[(ChromaDB\n벡터 DB)]
    end

    PS --> PSA --> T1
    SS --> SSA --> T2
    PA --> PAA --> T3 & T4
    T3 -->|벡터 저장| DB3
    T4 -->|검색| DB3

    GRAPH <-->|thread_id| DB1
    SV   <-->|users/user_id/profile| DB2

    GRAPH -->|ChatResponse\nproducts / sellers / analysis| API
    API -->|JSON or SSE| User
```

## Folder Map
각 폴더의 Claude.md에 상세 내용 있음.
- `Agent/` → LangGraph 에이전트 구현
- `Tools/` → 도구 함수 (RAG, 크롤링, 정규화)
- `FastAPI/` → REST API 서버
- `State/` → AgentState 정의
- `Crawling/` → 셀러 크롤러
- `Chain/` → LangChain 체인
- `MCP/` → Model Context Protocol
- `Userprofile/` → 유저 프로필 관리
- `Test/` → 테스트


## Conventions
- 한국어 주석 사용

## 자동 업데이트 규칙 (필수)
작업이 끝날 때마다 반드시 아래 두 파일을 업데이트할 것:

1. **해당 폴더의 `TODO.md`**
   - 작업한 내용 → `- [x]` 완료 항목으로 추가
   - 발견한 버그 / 남은 작업 → `- [ ]`로 추가

2. **해당 폴더의 `Claude.md`**
   - 새로운 파일이 생겼거나 구조가 바뀌었을 때만 업데이트
   - 변경 없으면 그대로 둘 것
