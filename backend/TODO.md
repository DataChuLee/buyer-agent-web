# TODO

- [x] Added `benchmarks/measure_rag_embedding_cache.py`: an isolated retrieval benchmark that records uncached, cache-cold, and cache-warm mean/p50/p95 latency plus hit rate in JSON.
- [x] Added `benchmarks/measure_rag_filter_compliance.py` and `measure_chat_stream_e2e.py`: separate structured-condition compliance from SSE first-event/completion latency, with JSON reports and explicit measurement scopes.
- [x] `measure_chat_stream_e2e.py` can launch a temporary local uvicorn server with `FastAPI.loop_factory:selector_loop_factory`, avoiding the Windows Psycopg/ProactorEventLoop startup conflict before measuring SSE latency.
- [x] Added `--in-memory-state` to the local SSE benchmark so API/agent/SSE latency can be measured when Supabase is unavailable; reports explicitly identify the state backend.
- [x] SSE E2E benchmark now writes a JSON diagnostic report on startup/request failures and permits a one-run prompt diagnosis before repeated measurements.
- [x] Added `benchmarks/measure_indexed_rag_agent_e2e.py`: measures the production Product Analysis Agent's indexed RAG path (retrieval → CRAG → answer generation → Self-RAG) with live crawling excluded and scope recorded in JSON.
- [x] Indexed RAG E2E benchmark supports `--case-report` to reuse a successfully retrievable case during repeated runs instead of repeating external case discovery.
- [x] Fixed RAG result-state consistency: embedding/Chroma failures now raise `RagRetrievalError` and return a distinct temporary-search-failure response instead of being misreported as no matching products; added regression coverage and filter-alignment diagnostics.
- [x] Re-ran the fixed indexed RAG agent path for five successful samples (one retrieved document per run), recording stage and total p50/p95 latency in `benchmarks/results/indexed_rag_agent_e2e_20260822T200205Z.json`.
- [x] Added `benchmarks/measure_crawl_index_cache.py`: measures exact repeated requests through the production crawl-and-index registry using an isolated temporary registry, and records live cache-miss versus cache-hit p50/p95 without changing existing cache entries.
- [x] Measured Soccerboom crawl-and-index cache across three live miss/hit pairs: miss p50 70,479.84ms and hit p50 7.61ms (20 products each miss); report `benchmarks/results/crawl_index_cache_20260823T031408Z.json` explicitly excludes LangGraph/RAG/LLM/HTTP stages.

- [x] `Multi_Agent_Orchestration.ipynb` cell20 그래프 시각화가 Mermaid 원문 텍스트 대신 노트북 이미지 출력 우선으로 동작하도록 수정
- [x] `Multi_Agent_Orchestration.ipynb` Seller Search 캐시 테이블에서 `crazy11` 같은 seller code를 한글 판매처명으로 정규화하도록 수정
- [x] `Multi_Agent_Orchestration.ipynb` SS auto_select 하드코딩 제거: Seller Search 표의 최저가 판매처를 자동 선택하도록 수정
- [x] `Multi_Agent_Orchestration.ipynb` PA review 카드 키 매핑 수정: `name/price/url`을 `product_name/product_price/product_url`로 전달
- [x] `Product_Search.ipynb`에 `Agent/product_search_agent.py`의 Tavily advanced 검색/필터링 로직 반영
- [x] `Product_Search.ipynb` PowerShell 파이프 재작성 중 깨진 한글 인코딩 복구
- [x] `Product_Search.ipynb` Product Search 기본 테스트를 시리즈 추천으로 복원하고 가격 필터 없는 Tavily 원본 확인 셀 추가
- [x] `Product_Search.ipynb` Tavily 도구 원본을 RAW/PRICE_DETECTED/PRICE_FILTERED로 비교하고 카포스토어 도메인을 `capostore.co.kr`로 수정
- [x] `Product_Search.ipynb` 판매처별 Tavily 도구 4개를 LCEL `RunnableParallel`로 병렬 실행하도록 수정
- [x] `Product_Search.ipynb` 병렬 Tavily 결과에 score/URL/키워드 기반 후보 필터와 LCEL LLM 시리즈 구조화 추출 셀 추가
- [x] `Product_Search.ipynb` 후보 필터에서 판매처별 top-k 보존을 제거하고 URL 제외 후 `score >= 0.35` 기준으로 단순화
- [x] `Product_Search.ipynb` 구조화 추출을 후보별 `abatch` 호출에서 필터 결과 전체 context 기반 단일 `ainvoke` 호출로 단순화
- [x] `Product_Search.ipynb` LLM 입력을 일반 text context에서 상품명/판매가가 매칭된 product item JSON으로 변경
- [x] `Product_Search.ipynb` LLM Chain을 제거하고 product item JSON을 rule-based 브랜드/가격/지면/시리즈/URL 필터로 정규화
- [x] `Product_Search.ipynb`에서 검증한 rule-based Product Search 파이프라인을 `Agent/product_search_agent.py`에 반영하고, 노트북에서 모듈 파이프라인/전체 에이전트 실행을 테스트할 수 있는 셀 추가
- [x] Product Search 가격대 필터를 `판매가` 단독 비교에서 `판매가` 또는 `소비자가` 매칭으로 보정하고, 필터 탈락 사유(`rejection_summary`, `rejected_products`)를 에이전트/노트북 출력에 추가
- [x] `Product_Search.ipynb` Agent 모듈 테스트 셀에 `importlib.reload()`를 추가해 Jupyter 커널의 오래된 `Agent.product_search_agent` 캐시로 `rejection_summary` 키가 누락되는 문제 방지
- [ ] 오프라인 환경에서 `draw_mermaid_png()`가 실패하면 로컬 Mermaid 렌더러 설정 검토
- [ ] 레드사커 `머큐리얼 베이퍼 15 TF` exact raw item을 캐시에 포함하려면 크롤러/웜업 데이터 갱신 필요
- [x] 서비스(`FastAPI/main.py`, `AutomationWorker/main.py`)·테스트·벤치마크 어디서도 import되지 않는 구버전 코드 제거(2026-10-28):
  구버전 에이전트 6개(`orchestrator_agent*.py`, `LangGraph_orchestrator_agent.py`, `sub_agent*.py`, LangMem 원본 그래프),
  `MCP/`·`Chain/`·`Userprofile/` 폴더, `Tools/tool.py`, `State/AgentState.py`, 레거시 `main.py`, `Crawling/crawling.py`,
  미사용 `Agent/orchestration/types.py`, 실험용 노트북 6개. 테스트 169개 통과. 내용은 git 기록에서 복구 가능.
- [x] 배포 설정 정비(2026-10-28): `Dockerfile`이 레거시 `main.py`(구 `/buyer-agent/buyer_agent_0313`만 제공)를 실행하던 것을
  `FastAPI.main:app`으로 교체하고 미사용 MCP npm 설치 제거. `.dockerignore`가 `State/`를 빼서 현재 그래프 import가 실패하던 문제 수정.
  `requirements.txt`에 `DATABASE_URL` 경로가 쓰는 `langgraph-checkpoint-postgres`/`psycopg`/`psycopg-binary`/`psycopg-pool` 추가(venv 버전 고정).
- [ ] Docker 이미지 빌드 실제 검증(Docker Desktop 미실행으로 미확인). `.dockerignore`에 `.chroma_store/`, `benchmarks/results/` 제외 여부 검토.
- [ ] `Test/test.py`는 MCP `sequential_thinking`을 쓰는 구버전 수동 스크립트(unittest 수집 대상 아님) — 제거 검토.
