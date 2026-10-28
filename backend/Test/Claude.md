# Test 폴더

## 역할
통합 테스트 및 기능 검증. Jupyter 노트북으로 빠른 실험, Python 스크립트로 자동화 테스트.

## 주요 파일
- `test_condition_sanitization.py` → 조건 정제 단위 테스트
- `test_seller_normalization.py` → 판매자 정규화 단위 테스트
- `test_raw_items_cache.py` → raw_items_cache 가격 범위/키워드 필터/중복 제거 단위 테스트
- `test_cache_primitives.py` → crawl registry exact/fuzzy hit와 web search L1/L2/TTL/손상 캐시 처리 테스트
- `test_crawler_normalization.py` → 판매처별 크롤 결과 공통 필드 fallback·중복 제거·async 실행 테스트
- `test_seller_search_agent_module.py`/`test_seller_selection.py` → 실제 외부 검색 없이 seller pipeline의
  `ok`/`no_results`/`error`/`partial_failure`, cache hit/miss/손상, 후보 검증·중복 제거와
  `(가격, 판매처명, URL)` 결정론적 최저가 선택 테스트
- `test_orchestration_supervisor.py` → `wants_all_comparison` 단위 테스트 (`plan_orchestration_steps`/`planner.py`는 삭제됨 — 고정 plan 대신 `supervisor_node`가 매 턴 재판단)
- `test_orchestration_workers.py` → `product_search_worker_node`/`seller_search_worker_node`/`product_analysis_worker_node`를 실제 미니 LangGraph(체크포인터 포함)로 구동해 `interrupt()` → `Command(resume=...)` 왕복, ordinal 선택, reset(리뷰 상태 초기화 + 메시지를 supervisor_node로 전달), all-comparison 리뷰 스킵, RAG 문서→카드 재사용을 검증하는 회귀 테스트 (`OrchestrationExecutor`/`executor.py`는 삭제됨)
- `test_product_search_followup_routing.py` → `extract_conditions_and_intent`의 조건 병합/멀티라벨 capability 추출 회귀 테스트 (orchestration_plan 필드는 삭제되어 더 이상 검증하지 않음; 실행 순서는 supervisor_node 책임)
- `eval_intent_extraction.py` / `fixtures/intent_extraction_cases.py` → 실제 LLM 호출로 intent/capability 분류 정확도를 재는 opt-in 스크립트(pytest 미포함, `OPENAI_API_KEY` 필요)
- `test_product_search_notebook.py` → Product_Search 노트북 LCEL 병렬 Tavily, 후보 필터, product item JSON 추출, rule-based 상품 정규화/필터, Agent 모듈 파이프라인 테스트 셀 reload/구조/컴파일 테스트
- `test_product_search_agent_module.py` → `Agent/product_search_agent.py`의 4개 판매처 도메인, Tavily 후보 필터, product item 파싱, 브랜드/가격대(판매가 우선, 없으면 소비자가)/지면/시리즈 필터, 탈락 사유 진단, dedupe, raw cache hit·miss, null 입력, 정상 0건과 외부 검색 실패 상태, markdown 파싱 회귀 테스트
- `test.py` → 통합 테스트
- `test_redsoccer_size_extraction.py` → `Crawling/redsoccer_test.py`의 `_looks_like_size`/`_extract_sizes_from_text_blob`가 무관한 3자리 숫자(상품코드 조각, 리뷰 수 등)를 신발 사이즈로 오인식하지 않는지 검증하는 회귀 테스트

## 노트북 (실험용)
- `test_mcp.ipynb`, `test_mcp_0223.ipynb` → MCP 연동 실험
- `crawling_test.ipynb` → 크롤러 실험
- `test_0312.ipynb`, `test.ipynb` → 전반적 기능 실험
