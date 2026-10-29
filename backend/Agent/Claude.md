# Agent 폴더

## 역할
LangGraph 기반 멀티에이전트 오케스트레이션. 사용자 의도 파악 → 조건 수집 → Supervisor가 매 턴 재판단하며
product_search/seller_search/product_analysis를 순서 제약 없이 호출 → 분석까지 전체 대화 흐름 관리.

## 주요 파일 (현재 사용)
- `LangGraph_buyeragent_with_personalization.py` → **메인 에이전트**. 파일명과 달리 LangMem은 더 이상 쓰지 않고,
  유저당 고정 키 1건을 직접 upsert하는 방식으로 장기 프로필을 관리한다(파일 내 주석 참조).
- `orchestration/` → Supervisor + 3개 워커 노드 (아래 "Orchestration 모듈" 참조)
- `product_search_agent.py`, `seller_search_agent.py`, `product_analysis_agent.py` → 3개 sub-agent

## 삭제된 구버전 (git 기록에만 남음)
- `LangGraph_buyeragent(with_personalization).py`(LangMem 원본), `orchestrator_agent*.py`,
  `LangGraph_orchestrator_agent.py`, `sub_agent.py`, `sub_agent_0310.py`(MCP Exa 검색 기반 하위 에이전트)
- 초기 버전은 하위 에이전트가 MCP(Exa)로 웹 검색했으나, 현재는 캐시 우선 + Tavily 직접 호출 파이프라인으로 대체됨

## 노드 흐름
```
load_user_memory
  → extract_conditions_and_intent
  → check_conditions
    → ask_missing_node        (조건 부족 시)
    → chitchat_node           (일반 대화)
    → product_guide_node
    → purchase_prepare_node
    → supervisor_node         (product_search/seller_search/product_analysis 의도)
        ├─ product_search_worker_node ─┐
        ├─ seller_search_worker_node  ─┼─→ (Command(goto=...)로 supervisor_node로 복귀, 매 턴 재판단)
        └─ product_analysis_worker_node┘     └─ 상품 선택 시 purchase_prepare_node로 직행
```
Supervisor/워커 노드들은 `Command(goto=...)`로 스스로 다음 목적지를 정하므로 그래프에 고정 엣지가 없다
(`_build_graph`에 이 노드들에 대한 `add_edge`가 없음 — 고정 plan 대신 매 턴 재판단하는 루프).

## Sub Agent 모듈
- `product_search_agent.py` → `search_products` tool(단일 `query: str` 파라미터, 1회 호출)을
  `create_react_agent`로 감쌈. `run_product_search_pipeline()`이 이제 `seller_search_agent`와 동일하게
  **캐시 우선, 없으면 Tavily 폴백** 순서로 동작(`_raw_cache_search_items(query)`가 있으면 4개 판매처
  Tavily LCEL 병렬 검색 자체를 생략) — 예전엔 캐시 유무와 무관하게 매번 Tavily를 먼저 돌리고 캐시는
  덧붙이기만 해서 매 턴 라이브 검색 편차에 그대로 노출됐었음. 크롤링/파싱/필터링 자체는 여전히 규칙
  기반(결정적)이며, LLM의 역할은 "도구를 언제/어떻게 부르고 결과를 어떻게 그대로 전달할지"로 한정된다.
  파이프라인 진단 결과에는 `source`, `search_status`, `failed_sellers`가 포함되어 cache/web 출처와 정상
  결과 없음(`no_results`), 외부 검색 실패(`error`)를 구분한다. 최종 외부 시그니처는 기존처럼 문자열이다.
- `seller_search_agent.py` → 캐시 우선, 없으면 판매처별 Tavily 폴백하는 `search_sellers` tool 하나를
  `create_react_agent`로 호출(외부 문자열 시그니처 유지). 내부 `run_seller_search_pipeline()`은 검증된
  시리즈만 입력으로 받고 지원 도메인·상품 일치·판매 상태·상세 URL·검증 가격을 통과한 후보만 남긴다.
  상태는 `ok`/`no_results`/`error`/`partial_failure`, 진단은 `source`/`failed_sellers`/
  `rejection_summary`로 표현한다. 부분 실패에서는 성공 후보를 버리지 않는다.
- `product_analysis_agent.py` → 크롤링 + RAG 분석 파이프라인. `create_react_agent`로 감싸지 않고
  결정적 함수로 유지(카드 생성이 RAG `docs` 메타데이터에 의존하고, 과거 AgentExecutor를 지연시간/
  hallucination 때문에 제거한 이력이 있어 되돌리지 않음). 생성 전 `filter_non_shoe_docs`(비축구화 제외,
  전부 빠지면 질의 재작성 후 1회 재검색) + 생성 후 `answer_cites_only_docs`(가격·URL 코드 검사, 실패 시
  1회 재생성). 예전 LLM 채점(CRAG/Self-RAG)은 근거 없는 주장을 줄이지 못하고 정상 문서를 과잉 제거해 대체됨.

## Orchestration 모듈 (`orchestration/`)
- `supervisor.py` → `supervisor_node`가 매 턴 대화·`past_steps`·조건을 보고 다음 액션
  (`product_search`/`seller_search`/`product_analysis`/`ask_user`/`FINISH`)을 구조화 출력으로 재판단한다.
  고정 순서(`_STEP_ORDER`)를 미리 계산해두던 옛 `planner.py`는 삭제되었다. `wants_all_comparison`
  (비교 요청 시 seller_search 생략 힌트)만 그대로 이식되어 있다.
- `workers.py` → `product_search_worker_node`/`seller_search_worker_node`/`product_analysis_worker_node`.
  각 워커는 결과가 여러 개면 LangGraph 네이티브 `interrupt()`로 멈춰 카드 리뷰를 요청하고, 재개된
  사용자 응답은 `_resolve_resume`(LLM 구조화 분류기, 순수 서수 입력만 LLM 호출 전에 즉시 처리)로
  해석한다. `reset`은 리뷰 상태만 지우고 사용자 메시지를 그대로 들고 `supervisor_node`로 복귀시켜,
  "취소" 요청과 "리뷰 도중 완전히 다른 요청"을 같은 경로로 자연스럽게 처리한다. 카드 정규화/직전 카드
  참조("첫 번째 제품") 해석 헬퍼는 옛 `executor.py`에서 그대로 이식됨.

### 삭제된 파일 (Agent/orchestration/)
`planner.py`, `resolver.py`(정규식 우선 게이트 — "사용자가 자유롭게 응답 못하는" 문제의 원인이었음),
`service.py`(로직이 각 워커의 interrupt 루프로 흡수됨), `executor.py`(→ `workers.py`로 대체).

## 의존성
- State: `State/AgentState_personalization.py`
- Memory: Postgres/Supabase(또는 InMemoryStore) 기반 직접 upsert. LangMem 라이브러리는 미사용(dead dependency).
