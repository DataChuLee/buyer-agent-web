# TODO - Test

## 진행 중
- [ ] 

## 버그
- [ ] `python -m unittest discover -s Test -p "test_*.py"`/`pytest` 전체 실행 시 기존 테스트 4건 실패: `profile_manager` 제거 이후 purchase prepare 테스트 미갱신, `FakeCollection.delete` 미구현, mocked background task가 set에 들어갈 수 없는 형태, product_analysis 스트리밍 허용 기대값이 현재 FastAPI 정책과 불일치

## 예정
- [ ] 

## 완료
- [x] Seller Search/Selection 독립 회귀 테스트: 입력 오류·결과 없음 가드, cache hit/miss/손상,
  부분/전체 실패, 지원 도메인, URL/가격/판매 상태, 판매가 우선/정상가 fallback, 정확한 시리즈,
  사용자 제외, 중복 제거, null/손상 row, 결정론적 동률 선택, 임의 fallback 금지를 mock 기반으로 검증.
- [x] product_analysis 사이즈 필터링 RAG 전환 회귀 테스트 추가:
  - `test_product_analysis_optimization.py`: `_extract_size`(조건/텍스트에서 사이즈 추출),
    `retrieve_analysis_documents_filtered()`의 size_min/size_max Chroma 필터 인자 구성 검증
    (`test_retrieve_analysis_documents_filtered_applies_size_range_filter`), size_text 정확 매칭이
    범위만으론 못 거르는 케이스를 걸러내는지(`test_retrieve_analysis_documents_filtered_excludes_size_mismatch`),
    `product_analysis_agent()`가 conditions의 size를 `_crawl_and_search_seller`에 그대로 전달하는지
    (`test_product_analysis_agent_passes_size_condition_to_search`) 추가. 기존
    `test_product_analysis_agent_calls_crawl_then_fast_rag`는 새 `size=` 키워드 인자를 반영해 갱신.
  - `test_product_search_followup_routing.py`: `_extract_explicit_product_conditions`가 "사이즈 265"/
    "265사이즈" 패턴을 규칙 기반으로 추출하는지 검증(`test_extracts_size_from_followup_question`).
  - `test_orchestration_workers.py`: `test_cards_summary_includes_size`(카드 요약에 사이즈 포함,
    1차 임시 수정의 회귀 방지 — 최종적으로는 필터링 RAG 재검색으로 대체됨),
    `test_condition_update_preserves_seller_scope_when_update_omits_it`(메인 그래프의 판매처명 오분류로
    `user_conditions`에 seller가 안 남아도, 사이즈처럼 판매처와 무관한 조건 변경 시 이미 좁혀둔 판매처
    범위가 조용히 전체로 넓어지지 않는지 검증) 추가.
  - 실사용 3턴 시나리오(크레이지11 머큐리얼 베이퍼 10만원대 → 다른 건 없어? → 사이즈 265 있어?)를 실제
    크롤링 캐시 + gpt-4o-mini + Supabase로 전/후 재현해 사이즈 오답 및 판매처 스코프 유실이 모두
    해결됐음을 확인(자동화 테스트가 아니라 수동 스크립트 기반 확인).
- [x] `backend/venv`에 `pytest`+`pytest-asyncio` 설치. 실제 앱 실행에 쓰이는 `backend/venv`(playwright+크로미움
  포함)에는 `pytest`가 없어서 그동안 별도 글로벌 python으로 테스트를 돌렸던 것으로 보임 — 이제
  `venv/Scripts/python.exe -m pytest Test/`로 실제 앱과 동일한 환경에서 테스트 가능.
- [x] Agentic orchestration 리팩터링(Supervisor + create_react_agent + native interrupt()) 테스트 정리:
  `test_orchestration_planner.py`/`test_orchestration_resolver.py`/`test_orchestration_service.py`/
  `test_orchestration_executor.py` 삭제(대상 모듈 `planner.py`/`resolver.py`/`service.py`/`executor.py`
  자체가 삭제됨). `test_orchestration_supervisor.py`(`wants_all_comparison`만 이동) +
  `test_orchestration_workers.py`(실제 미니 LangGraph로 `interrupt()`→`Command(resume=...)` 왕복 검증 —
  ordinal 선택, reset이 상태를 지우고 메시지를 supervisor_node로 넘기는지, all-comparison 리뷰 스킵, RAG
  문서→카드 재사용, `_parse_products`의 "결과 없음" 가드) 신규 작성. `test_product_search_followup_routing.py`
  는 `orchestration_plan` 대신 `requested_capabilities`/`past_steps`를 검증하도록 갱신.
  `test_fastapi_progress_events.py`/`test_fastapi_orchestration_response.py`는 새 노드명
  (`product_search_worker_node` 등)과 `__interrupt__` 기반 `pending_action` 응답 형태에 맞춰 갱신.
  `test_product_analysis_optimization.py`의 삭제된 `product_analysis_node` 참조 테스트를
  `test_orchestration_workers.py`(실제 `build_analysis_cards_from_docs` 사용)로 이동.
- [x] 후속 질문 3종 세트 버그 회귀 테스트 추가:
  - `test_product_analysis_optimization.py`에 `test_product_analysis_agent_interleaves_results_across_sellers`
    추가: 한 판매처가 문서를 많이 가져도(crazy11 3건 vs 나머지 1건씩) 라운드로빈으로 섞여 앞 4개 안에 4개
    판매처가 모두 등장하는지 검증.
  - `test_orchestration_executor.py`에 `test_product_search_drops_stale_brand_when_referencing_multiple_candidates`
    추가: "저 중에서 가성비 있는 시리즈는 뭐야" 메시지 + 잔존 `brand="나이키"` 조건일 때 검색 쿼리에 "나이키"가
    빠지고 나머지 조건(예산)은 유지되는지 검증.
  - `test_orchestration_resolver.py`에 `test_ordinal_index_ignores_price_digits`(서수 오매칭 방지) +
    `OrchestrationResolverLlmFallbackTest` 클래스(7개: 애매한 지칭 select, ss_review 카드 shape 정규화,
    질문 대상 판매처 부재/존재 시 응답, condition_update 라우팅, 인덱스 범위 초과/분류 예외 시 invalid 폴백)
    추가 — 전부 `classify` 파라미터에 fake 함수를 주입해 실제 LLM/네트워크 없이 검증.
  - `test_orchestration_service.py` 신규 추가: 결정론적 매칭 성공 시 LLM 폴백이 호출되지 않는지, `question`/
    `condition_update` 분기가 `_handle_pending_action`에서 올바르게 처리되는지, `condition_update`가 실제로
    `user_conditions`를 병합하고 현재 pending 단계를 재실행하는지 검증.
- [x] "모두 비교" + "앞서(서) 말한 시리즈" 조건 오염 회귀 테스트 추가: `test_orchestration_executor.py`에 `test_product_analysis_clears_polluted_seller_when_comparing_all_sellers`(오염된 `user_conditions["seller"]`가 있어도 "모두 비교" 메시지면 `conditions`에서 seller가 제거되는지), `test_product_analysis_resolves_prior_reference_phrase_from_last_products`("앞서서 말한 시리즈" 문구 + 오염된 다중 시리즈 문자열이 `user_conditions`에 있어도 `last_products`의 실제 카드 이름으로 정정되는지) 2건 추가
- [x] `test_surface_followup_overrides_chitchat_classifier_to_product_search` (rule-base override 하드코딩 mock 기반) 삭제: intent/plan 재설계로 이 override 로직 자체가 제거되어 mock으로는 더 이상 검증 대상이 아님. "그럼 TF는?" 케이스는 `Agent/orchestration/`가 아니라 `Test/fixtures/intent_extraction_cases.py`(실제 LLM 호출 eval)로 이관해 추적
- [x] `test_product_search_followup_routing.py`에 intent/plan 재설계 회귀 테스트 추가: 멀티라벨 `requested_capabilities`가 고정 순서 orchestration_plan으로 조립되는지(`test_multi_capability_extraction_builds_ordered_plan`), "구매하려고" 문구가 섞여도 삭제된 `_SELLER_PATTERNS` 재스캔이 되살아나 seller_search로 안 새는지(`test_bug_b_regression_purchase_phrase_routes_to_product_search`) 검증
- [x] `test_orchestration_planner.py`를 `plan_orchestration_steps`의 새 시그니처(원문 텍스트 대신 capability 리스트)에 맞춰 재작성, `test_orchestration_executor.py`에 seller_search용 "모두 비교" pending_action 스킵 회귀 테스트 추가
- [x] Product Search 크로스 브랜드 카드 버그 회귀 테스트 추가: `test_product_search_agent_module.py`에 시리즈 필터(요청 시리즈와 다른 시리즈 거절/시리즈 미지정 시 통과/동일 시리즈 다른 라인업 허용), `_raw_cache_search_keyword`/`_raw_cache_search_items`(시리즈 키워드 추출, `load_raw_items_cache` 매핑 및 미호출 케이스), `build_product_search_pipeline_result(..., extra_items=...)`가 캐시 아이템을 기존 브랜드/시리즈 필터에 그대로 통과·거절시키는지 검증하는 테스트 추가. `test_orchestration_executor.py`에 `_parse_products()`가 두 가지 "결과 없음" 안내 텍스트(포맷터 빈 결과 메시지 / 하드코딩 폴백 가이드) 모두에서 빈 배열을 반환하는지, `OrchestrationExecutor`가 폴백 가이드 텍스트로부터 상품 카드를 만들지 않는지 검증
- [x] product_guide 라우팅 회귀 테스트 추가: "포지션별로는 어떤 스터드를 사용하는 게 좋아?" 문장이 LLM이 `product_search`로 분류해도 최종 intent는 `product_guide`가 되고 orchestration plan은 비어 있는지 검증
- [x] Product Search 카드 null 방어 회귀 테스트 추가: parser가 `features`/`recommendation`/`price`/`url`을 `None`으로 반환해도 executor가 프론트 안전 문자열로 정규화하는지 검증
- [x] `Product_Search.ipynb` Agent 모듈 테스트 셀 reload 회귀 테스트 추가: Jupyter 커널 캐시 때문에 오래된 `build_product_search_pipeline_result()`가 호출되어 `rejection_summary`가 누락되지 않도록 `importlib.reload()` 존재를 검증
- [x] Product Search 가격 필터/탈락 진단 회귀 테스트 추가: `소비자가`가 요청 가격대에 맞고 `판매가`가 할인으로 낮아진 상품도 통과하며, 전체 탈락 시 `surface_mismatch` 등 사유가 집계되는지 검증
- [x] `Agent/product_search_agent.py` rule-based 파이프라인 회귀 테스트 추가: 판매처 도메인, Tavily 후보 필터, 상품명/판매가 매칭, 브랜드/가격대/지면 필터, dedupe, 최종 markdown 파싱을 검증
- [x] `Product_Search.ipynb` 모듈 테스트 셀 회귀 테스트 추가: `build_product_search_pipeline_result`, `run_product_search_pipeline`, `module_product_search_agent` 호출 셀이 존재하는지 검증
- [x] `Product_Search.ipynb` LLM Chain 제거 회귀 테스트 추가: 구조화 추출 Chain 문자열이 제거되고 rule-based 브랜드/가격/지면/시리즈 필터가 존재하는지 검증
- [x] `Product_Search.ipynb` product item JSON parser 회귀 테스트 추가: `상품명/제조사/소비자가/판매가` 블록에서 상품명과 판매가가 같은 item에 매칭되는지 검증
- [x] `Product_Search.ipynb` 단일 LLM 추출 구조 회귀 테스트 추가: 후보별 `abatch` 제거와 필터 결과 전체 context 기반 `ainvoke` 호출을 검증
- [x] `Product_Search.ipynb` Tavily 후보 필터 단순화 회귀 테스트 추가: 판매처별 top-k 보존 제거와 `score >= 0.35` 기준 필터 적용을 검증
- [x] `Product_Search.ipynb` LCEL 필터/구조화 추출 셀 회귀 테스트 보강: 후보 필터 상수, `filter_tavily_candidates`, 구조화 출력 모델, `series_extraction_chain`, 단일 `ainvoke`, dedupe 함수 존재와 컴파일을 검증
- [x] `Product_Search.ipynb` LCEL 병렬 Tavily 셀 회귀 테스트 추가: `RunnableParallel`/`RunnableLambda` 구조와 노트북 코드 셀 컴파일을 검증
- [x] Product Search Tavily 진단 회귀 테스트 추가: 카포스토어 도메인이 `capostore.co.kr`인지, `cafostore.co.kr`가 제외되는지, RAW/PRICE_DETECTED/PRICE_FILTERED 비교가 가격 조건 유무별로 동작하는지 검증
- [x] Product Search 시리즈 추천 복원 회귀 테스트 추가: 쿼리가 `시리즈 추천` 중심인지, 프롬프트가 개별 SKU 대신 시리즈를 요구하는지, 가격 없는 Tavily 결과도 unfiltered 디버그 출력에 남는지 검증
- [x] Product Search strict Tavily 필터 회귀 테스트 추가: 4개 지원 도메인 고정, 가격 없는 결과 제외, 요청 가격대 밖 결과 제외, 지원 도메인 밖 결과 제외, markdown 표 파싱으로 가격/URL/추천 이유가 보존되는지 검증
- [x] 오케스트레이션 회귀 테스트 보강: 잡담이 프로필 상품 기억으로 seller_search가 되지 않는지, Product Search 링크/last_products 보존, "첫 번째 제품/저 제품" 참조 해석, Seller 추천 이유 보존, Product Analysis RAG 0건 조건 설명을 검증
- [x] `test_seller_selection.py` 추가: Seller Search markdown 표에서 최저가 판매처를 선택하고 판매 중 행이 없으면 기본값으로 fallback하는지 검증
- [x] `test_raw_items_cache.py` 추가: raw items 캐시가 가격 미지정 SS 쿼리에서도 겹치는 가격대 캐시를 hit하고, 상품명 토큰 필터와 중복 제거를 적용하는지 검증
- [x] "모두 비교" 오라우팅/강제 선택 카드 회귀 테스트 추가: `test_orchestration_planner.py`에 `has_known_sellers=True` + "모두/전부" 문구일 때만 `seller_search`를 건너뛰는지(그 외엔 기존처럼 유지) 검증, `test_orchestration_executor.py`에 "모두 비교" 요청 시 `pa_review` pending_action 없이 `status=done`으로 끝나는지 검증, `test_orchestration_resolver.py`에 ss_review 응답의 복수 선택("1번이랑 3번", "크레이지11이랑 카포스토어 둘 다")이 `selected_list`로 반환되는지 검증
- [x] 크롤링·캐시 기반 회귀 테스트 보강: `test_cache_primitives.py`에서 crawl registry exact/fuzzy hit와
  web search L1/L2/TTL/손상 entry 처리를 검증하고, `test_crawler_normalization.py`에서 통합 크롤러의
  필드 fallback·중복 제거·async crawler 실행 경로를 검증. raw cache의 naive timestamp/손상 entry와
  벡터 문서 upsert 정책도 회귀 테스트로 고정.
- [x] Product Search 독립 안정화 회귀 테스트 보강: 기존 브랜드/예산/판매가 우선/지면/시리즈/도메인/
  dedupe/cache hit·miss 테스트에 더해 무가격·비정상 가격, 미지원 판매처 URL, null/불완전 cache item,
  구체적 제외 시리즈의 sibling 보존, 외부 검색 예외·판매처 전체 실패(`error`)와 정상 0건
  (`no_results`) 구분, 실패 안내에서 상품 카드가 생성되지 않는지 검증.
- [x] 그래프 리팩터링 후 깨진 테스트 3건 정비(2026-10-28): `test_purchase_prepare_graph.py`는 삭제된
  `profile_manager`/`product_analysis_agent`/`_parse_analysis` 패치 대신 `save_user_memory`를 패치하고,
  분석 턴(supervisor LLM + interrupt) 결과는 `aupdate_state`로 `analysis` 상태를 주입해 구매 준비 3턴만 검증.
  `test_response_performance_optimizations.py`는 의도적으로 스트리밍 화이트리스트에서 빠진 분석 노드 대신
  `chitchat_node` 스트리밍을 검증하고, `create_task` 가짜 반환값을 `_pending_memory_saves` set에 넣을 수 있는
  `MagicMock`으로 교체. 백엔드 테스트 169개 통과(venv 기준).
- [ ] 전역 Python(pyenv 3.11.9)은 FastAPI 0.112 + Starlette 1.6 조합이라 `FastAPI/main.py` import가 실패함
  (`Router.__init__() got an unexpected keyword argument 'on_startup'`). 테스트는 `backend/venv`로 실행할 것.
