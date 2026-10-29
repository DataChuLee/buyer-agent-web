# TODO - Agent

## 진행 중
- [ ] `Agent/orchestration/supervisor.py`의 `_get_supervisor_classifier`를 `gpt-5.4-nano`로 교체함 —
  실제 API 키로 `remaining_order`/`next` 구조화 출력이 안정적으로 채워지는지 아직 실호출 검증 전.
  `temperature=0` 거부나 스키마 정확도 저하가 보이면 `gpt-5.4-mini`로 교체.

## 버그
- [ ] (이번 세션에서 발견, 미수정, 낮은 우선순위) `extract_conditions_and_intent`가 "크레이지11에서
  나이키 머큐리얼 베이퍼 10만원대 비교해줘"에서 `conditions.seller="크레이지11"`은 이제 정확히
  잡지만(아래 완료 항목의 few-shot 보강으로 해결), `conditions.surface`에 엉뚱하게 "머큐리얼"을
  채워 넣는 별도 오분류가 관찰됨(실제 FG/AG/TF 같은 지면 종류가 아닌데도 surface 필드를 항상
  채우려는 경향으로 보임). product_analysis 시나리오에선 surface가 필수 조건이 아니라 무해했지만,
  product_search 흐름에서는 `check_conditions`가 이 값을 "지면 조건 이미 있음"으로 오인해 실제 지면
  질문을 건너뛸 수 있어 영향이 있을 수 있음 — 프롬프트에 "조건을 못 찾으면 그 필드는 비워 두라"는
  명시적 지침 추가 검토 필요(범위 밖이라 이번엔 미수정).
- [ ] (이번 세션에서 발견, 무관한 pre-existing 이슈 — 이번 작업 범위 밖이라 미수정) `Test/test_purchase_prepare_graph.py`가 더 이상 존재하지 않는 `buyer_graph.profile_manager`를 참조해 `asyncSetUp`에서 즉시 실패. `Test/test_response_performance_optimizations.py`의 `test_add_new_documents_skips_duplicate_and_existing_ids`(FakeCollection에 `.delete` 미구현), `test_extract_stream_chunk_allows_product_analysis_streaming`(현재 설계상 `product_analysis_*` 노드는 의도적으로 스트리밍 제외이므로 이 테스트의 기대값 자체가 stale), `test_queue_user_memory_save_schedules_background_task`(SimpleNamespace 관련) 모두 이번 리팩터링 이전부터 깨져 있었음(무관한 파일들이 세션 시작 시점에 이미 uncommitted 상태로 수정돼 있었음)

## 예정
- [ ] Product_Search.ipynb 구현 내용을 `Agent/product_search_agent.py`로 모듈화 후 `sub_agent_0310.py`의 `run_product_search_agent()` 교체
- [ ] Seller_Search.ipynb 구현 내용을 `Agent/seller_search_agent.py`로 모듈화 후 `sub_agent_0310.py`의 `run_seller_search_agent()` 교체
- [ ] 모듈화 완료 후 `MCP/mcp_tool.py` Product/Seller Search 의존성 제거
- [ ] (이번 세션에서 발견, 미수정) product_search 결과 카드의 `url`이 실제 크롤링된 `product_url`이 아니라
  `_ensure_product_links()`(orchestration/workers.py)가 채우는 네이버 검색 링크로 대체됨 —
  `format_product_search_results()`가 텍스트에 product_url을 안 넣어서 생기는 손실. Seller Search는
  `URL:` 라벨로 실제 URL을 전달하는 것과 비대칭.
- [ ] (이번 세션에서 발견, 미수정) 뉴발란스처럼 `SERIES_BRAND`에 큐레이션 시리즈가 0개인 브랜드는 여전히
  자유검색만 타므로, `normalize_product_item()`의 13개 시리즈 화이트리스트에 안 걸리는 실제 상품은
  조용히 걸러지는 문제가 남아있음(의도적으로 이번 수정 범위 밖으로 뺌 — 아래 series 조건 항목 참고)

## 완료
- [x] Product Analysis 판매처당 검색/카드 개수 6 → 3으로 축소, 카드가 판매처별로 묶여 나오도록 수정.
  `Agent/product_analysis_agent.py`의 `retrieve_analysis_documents_filtered(..., limit=6)` →
  `limit=3`(판매처당 RAG 후보 문서 수). `Tools/rag_search.py`의 `build_analysis_cards_from_docs`는
  기존엔 `limit`이 라운드로빈 병합 순서에 적용되는 전역 카드 개수 제한이라, 판매처마다 남은 후보
  수가 다르면 그 절단선 안에서 특정 판매처가 몰려 카드가 판매처별로 안 묶여 보였다(실사용 재현:
  크레이지11/카포스토어/크레이지11/크레이지11 순서로 표시). `limit`을 "판매처당 최대 개수"로
  의미를 바꾸고, 결과를 판매처 첫 등장 순서대로 묶어서 반환하도록 수정 — `Agent/orchestration/
  workers.py`의 호출부도 `limit=3`으로 함께 변경(라운드로빈 병합 자체는 판매처 쏠림 방지용으로
  그대로 유지, `product_analysis_agent.py`의 `_merge_docs_round_robin` 참고). 회귀 테스트:
  `Test/test_product_analysis_optimization.py`의
  `test_build_analysis_cards_from_docs_groups_by_seller_with_per_seller_cap`.
- [x] Product Search "됐다가 안됐다가" 근본 재발 방지: 시리즈를 안 고른 채(브랜드만 있는) 검색이
  캐시 조회 자체를 건너뛰고 매번 라이브 Tavily(도메인당 max_results=5)로 빠지던 문제 수정 (실사용
  재현: "나이키 축구화 10만원대 추천해줘" → "TF" → 매 호출마다 결과 0~2개로 들쭉날쭉, 필터 탈락
  요약도 매번 다름). 캐시엔 이미 나이키 시리즈별로 수백 건씩 크롤링돼 있었는데(`머큐리얼` 10만원대만
  111건), `_raw_cache_search_items`가 쿼리에 특정 시리즈명이 없으면 캐시 조회를 아예 스킵하도록
  돼 있어 이 방대한 캐시를 못 쓰고 있었음. `_raw_cache_search_keywords()` 추가: 시리즈가 없어도
  브랜드가 있으면 그 브랜드의 큐레이션 시리즈 전체(`series_options_for_brand`)를 캐시에서 조회해
  병합, 하나도 없을 때만 라이브 Tavily로 폴백. 회귀 테스트:
  `Test/test_product_search_agent_module.py`의
  `test_raw_cache_search_keywords_falls_back_to_brand_curated_series`,
  `test_raw_cache_search_keywords_returns_empty_without_brand_or_series`,
  `test_raw_cache_search_items_merges_hits_across_brand_curated_series`(기존
  `test_raw_cache_search_items_skips_lookup_without_series_keyword`는 의도적 동작 변경으로 대체).
  동일 쿼리 3회 반복 호출로 완전히 동일한 시리즈 3개가 나오는 것 확인(이전엔 호출마다 달랐음).
- [x] Product Search 조건 수집 카드에서 시리즈(series) 질문 제거 — 시리즈까지 사용자가 카드로 직접
  고르면 product_search가 검색·추천하는 역할 자체가 무의미해진다는 판단. `check_conditions()`의
  시리즈 재질문 분기(brand/budget/surface 확정 후 curated 브랜드면 series를 missing에 추가하던 로직)
  삭제, `ask_missing_node()`의 `series` 특수 처리 및 이제 안 쓰는 `_series_question()` 함수 삭제
  (관련 import `SERIES_DESCRIPTIONS`/`series_options_for_brand`도 함께 제거). 이제 필수 조건은
  brand/budget/surface만 남고, product_name/시리즈는 사용자가 메시지에 시리즈명을 직접 언급했을
  때만(`_extract_explicit_product_conditions`) 채워짐. `Test/test_product_search_followup_routing.py`
  갱신(시리즈 질문 관련 obsolete 테스트 제거/수정). 라이브 서버로 "TF" 답변 후 시리즈 질문 없이 바로
  검색 결과로 넘어가는 것 확인.
- [x] Seller Search 추천 이유 문구에서 내부 구현 디테일("캐시 기준") 노출 제거 — "캐시 기준 조건에 맞는
  상품 N개가 확인되고..." → "조건에 맞는 상품 N개가 확인되고...". `Test/test_seller_search_agent_module.py`
  갱신.
- [x] Product Search 시리즈 재질문 스킵 버그 수정 (실사용 재현: "나이키 축구화 10만원대 추천해줘" →
  surface 질문에 "TF"만 답하면 시리즈 질문 없이 바로 검색으로 직행, 캐시 미스인 채 라이브 Tavily에
  노출되어 "됐다가 안됐다가" 재발). 근본 원인: 조건 수집 질문에 답변 중인 턴이 쓰는 LLM 조건 추출기가
  "TF"처럼 짧은 답변을 surface로 못 잡고 `product_name: "TF"`로 잘못 채움(직접 호출로 실측 확인) —
  룰 기반 추출기가 surface는 정확히 덮어쓰지만 product_name은 안 건드려 오염된 값이 그대로 남았고,
  `check_conditions`의 시리즈 재질문 분기(`not conditions.get("product_name")`)가 항상 스킵됨.
  `_merge_product_conditions`에서 `product_name`은 `_requested_series_name()`으로 실제 인식 가능한
  시리즈명일 때만 신뢰하도록 수정. 회귀 테스트: `Test/test_product_search_followup_routing.py`의
  `test_merge_drops_hallucinated_product_name_not_a_known_series`,
  `test_merge_keeps_product_name_when_recognized_series`. 라이브 서버 2턴 재현으로 전/후 비교 확인.
- [x] "저 중에서" 후속 질문이 조건을 좁히는 요청일 때도 무조건 brand를 지워 결과가 턴마다 들쭉날쭉하던
  버그 수정 (실사용 재현: "저 중에서 10만원대이고 공격수에게 적합한 시리즈는 뭐야" → 나이키 시리즈가
  1개 나올 때도 2개 나올 때도 있음). 근본 원인: `product_search_worker_node`가
  `_MULTI_CANDIDATE_REFERENCE_PATTERNS`("저 중에서" 등) 매칭 시 무조건 `brand`를 지우는데, 이 메시지엔
  특정 시리즈명이 없어 캐시 조회가 스킵되고 매번 라이브 Tavily 검색으로 빠짐 + brand 필터까지 풀려
  범위가 더 넓어짐 → 라이브 검색 특성상 매 호출 결과가 달라짐. budget/surface로 조건을 실제로 좁히는
  메시지면 brand를 유지하도록 조건부 처리(`_extract_requested_price_range`/`_query_requests_surface`로
  판별). 회귀 테스트: `Test/test_orchestration_workers.py`의
  `test_multi_candidate_reference_keeps_brand_when_message_narrows`,
  `test_multi_candidate_reference_drops_brand_without_narrowing`(기존 "다른 거 없어?" 동작은 유지).
- [x] product_analysis 시나리오 실사용 재현 테스트("크레이지11에서 나이키 머큐리얼 베이퍼 10만원대
  비교해줘" → "다른 건 없어?" → "사이즈가 265인 제품은 없어?") 중 발견한 버그 수정: `workers.py`의
  `_cards_summary()`(리뷰 응답 분류기 `_resolve_resume`에 넘기는 카드 요약)가 `name`/`seller`/`price`만
  담고 `size`는 빼먹어, 사이즈 질문이 카드 데이터에 실제 답이 있어도 항상 "근거 없음(ungrounded)"으로
  판정되며 고정 안내 문구만 반환되던 문제. 요약 줄에 `사이즈={card.get('size')}`를 추가.
  회귀 테스트: `Test/test_orchestration_workers.py`의 `test_cards_summary_includes_size`.
  실사용 재현으로 전/후 비교 확인 — 수정 전엔 항상 `_UNGROUNDED_QUESTION_FALLBACK` 고정 문구, 수정 후엔
  실제 사이즈 데이터를 근거로 답변을 시도했으나, 여전히 카드 텍스트를 LLM이 읽고 답하는 방식이라
  콤마로 나열된 긴 사이즈 목록에서 실제로 265가 있는데도 "없다"고 오답하는 경우가 남아있었음(아래
  항목에서 필터링 기반 RAG 재검색으로 근본 해결).
- [x] product_analysis 사이즈 후속 질문("사이즈가 265인 제품은 없어?")을 카드 텍스트 기반 LLM 응답이
  아니라 **필터링 기반 RAG 재검색**으로 전환(위 `_cards_summary` 임시 수정은 여전히 카드 텍스트를 LLM이
  읽고 판단해 콤마로 나열된 긴 사이즈 목록에서 오답하는 근본 문제를 안 고쳤음 — 사용자가 "애초에
  SelfQueryRetriever 대신 필터링 기반 RAG로 바꾼 거 아니었나"라고 지적해 설계를 재검토):
  1. **RAG 필터에 사이즈 추가**: `Tools/rag_search.py`의 `retrieve_analysis_documents_filtered()`에
     `size` 파라미터 추가. `crawl_and_index.py`가 이미 인덱싱 시 저장해두던 `size_min`/`size_max`
     메타데이터로 Chroma `$and` 필터 1차 압축 후, `size_text`(콤마 목록) 정확 매칭으로 2차 확정
     (min/max 범위만 믿으면 중간에 빠진 사이즈까지 있다고 오탐할 수 있어서).
  2. **조건 스키마 확장**: `ExtractedConditions`(`LangGraph_buyeragent_with_personalization.py`)에
     `size` 필드 추가, `_extract_explicit_product_conditions()`에 규칙 기반 사이즈 추출("사이즈 265"/
     "265사이즈" 패턴, LLM 호출 없음) 추가. `product_analysis_agent.py`에 `_extract_ground_type`과
     동일 패턴의 `_extract_size()` 추가해 `_crawl_and_search_seller()`/`retrieve_analysis_documents_filtered()`
     양쪽 호출부(최초 시도 + CRAG 재시도)에 전부 관통시킴. `_build_no_result_answer()`도 사이즈를
     필터 목록에 표시하도록 보강.
  3. **분류 라우팅 변경**: `_RESOLUTION_SYSTEM`(orchestration/workers.py) 프롬프트에 "사이즈 N 있어?"
     류 질문은 `question`(카드 텍스트를 LLM이 읽고 답변)이 아니라 `condition_update`(실제 재검색
     트리거)로 분류하라는 예시 추가 — 기존에 판매처 제외/조건 변경을 `condition_update`로 처리하던
     것과 동일한 패턴.
  4. **부수 발견 + 수정 A(판매처명 오분류)**: 재검증 중 `extract_conditions_and_intent`가 "크레이지11"
     같은 판매처명을 `conditions.seller`가 아니라 `conditions.surface`로 잘못 채우는 걸 발견(사커붐 등
     다른 이름은 정상 추출됨 — 이름별 비일관). 시스템 프롬프트에 "surface는 FG/AG/TF/HG/IC/MG/SG
     지면 종류만, 판매처명은 seller 필드로" 명시적 제약 추가.
  5. **부수 발견 + 수정 B(조건 변경 시 판매처 스코프 유실)**: 4번 버그 때문에 `user_conditions`에
     seller가 아예 안 남으면, `product_analysis_worker_node`의 `condition_update` 분기가
     `_apply_condition_update()`(메인 그래프 조건에만 의존)만 보고 판매처 범위를 결정해 사이즈처럼
     판매처와 무관한 조건 변경에도 이미 좁혀둔 판매처(크레이지11)가 조용히 전체 4곳으로 넓어졌음
     (`_analysis_conditions()`가 메시지에서 판매처를 재추론하는 별도 로직에는 이 문제가 없었음 — retry
     경로만 우연히 안전했던 것). `condition_update` 분기에 방어적 폴백 추가: 갱신된 조건에 seller가
     없고 "모두 비교" 요청도 아니면, 이번 노드 진입 시 이미 계산해둔 seller를 그대로 유지.
  - 검증: `Test/test_product_analysis_optimization.py`(사이즈 필터/RAG 파라미터 전달, size_min/max
    범위 필터 + size_text 정확 매칭 분리 검증), `Test/test_product_search_followup_routing.py`(사이즈
    규칙 기반 추출), `Test/test_orchestration_workers.py`(판매처 스코프 유지 회귀) 전체 통과(132개,
    무관한 pre-existing 실패 4건 제외). **3턴 시나리오(크레이지11 머큐리얼 베이퍼 10만원대 → 다른 건
    없어? → 사이즈 265 있어?)를 실제 크롤링 캐시 + gpt-4o-mini + Supabase로 전/후 재현 — 수정 전엔
    "사이즈 265 없음"으로 오답(실제로는 있었음), 수정 후엔 크레이지11 범위를 유지한 채 실제로 사이즈
    265를 포함하는 6개 상품을 정확히 찾아 반환함을 확인.**
- [x] Product Search "됐다가 안됐다가" 플레이키 재현 조사 + 수정 (사용자 실사용 재현: "나이키 머큐리얼
  시리즈 10만원대" → TF 답변 후 매번 결과가 다름, `brand_mismatch=4, not_boot_or_missing_series=4`로
  전멸). 근본 원인: `run_product_search_pipeline()`이 `raw_items_cache` 유무와 무관하게 매 턴 라이브
  Tavily 검색(판매처 4곳 × `max_results=5`)을 먼저 돌리고 캐시는 그 결과에 덧붙이기만 해서, 브랜드+
  시리즈+지면+가격을 동시에 만족해야 하는 좁은 AND 필터가 그날 Tavily가 우연히 반환한 소수 후보에
  그대로 노출됐음. 유일한 구제책이던 `_run_surface_expanded_search`(0건 시 FG/AG/TF/IC로 재검색)도
  `check_conditions`가 surface를 필수 조건으로 강제해 쿼리에 항상 surface가 포함되므로
  `_query_requests_surface(query)`가 항상 True가 되어 실사용에서 사실상 발동 못 했음(부수 관찰,
  이번 수정 범위 밖). `seller_search_agent.search_sellers`가 이미 쓰던 "캐시 우선, 없으면 Tavily
  폴백" 순서를 `run_product_search_pipeline()`에도 동일 적용(`_raw_cache_search_items(query)`가
  비어있지 않으면 Tavily 호출 자체를 생략) — 도구 시그니처(`search_products(query: str)` 단일 파라미터,
  1회 호출)는 그대로 유지하고 캐시/Tavily 순서 판단은 도구 내부 코드에만 남김(캐시 조회용 도구를
  react agent에 별도로 추가하는 안은 기각 — seller_search가 과거 `search_sellers(keyword, min, max)`처럼
  여러 파라미터를 LLM이 직접 채우게 했다가 문제를 겪고 `(query: str)` 단일 파라미터로 되돌린 전례와
  동일한 비결정성을 재도입하게 됨). 회귀 테스트:
  `test_pipeline_uses_cache_only_and_skips_tavily_when_cache_hits`,
  `test_pipeline_falls_back_to_tavily_when_cache_misses`
  (`Test/test_product_search_agent_module.py`).
- [x] PS/SS 리뷰 단계 "다른 거 없어?"(retry)가 실제로는 같은/제외 대상 후보를 다시 보여주던 버그 수정
  (사용자 실사용 재현):
  1. **Product Search 핵심 버그**: `workers.py`가 retry 시 쿼리에 붙이는 "exclude: A, B" 절이
     `classify_product_item()`의 필터링 단계까지 그대로(스트리핑 없이) 흘러가, `_requested_series_name()`이
     "exclude:" 앞뒤 구분 없이 쿼리 전체에서 substring 매칭을 해 **제외 대상 시리즈명을 "요청된 시리즈"로
     오인식**했다 — 그 결과 그 시리즈와 정확히 일치하는 상품만 필터를 통과시키고 다른 시리즈는 전부
     `series_mismatch`로 걸러버렸음(우연히 같은 시리즈의 다른 매물이 있으면 그게 다시 보여짐). 게다가
     "제외"를 실제로 걸러내는 필터 자체가 없이 Tavily 쿼리 문구("... 제외")에만 의존했다(Tavily는 부정
     연산자를 이해 못함). `classify_product_item()`에 `_excluded_series_names()`(SERIES_PATTERNS 별칭의
     substring 매칭 — 콤마 분리 대신 이 방식을 쓴 이유는 exclude 절 뒤에 항상 " 축구화 추천" 접미사가
     붙어 콤마 분리 시 마지막 이름에 접미사가 섞이기 때문) + 명시적 `excluded_series` reject 사유를 추가.
     회귀 테스트: `test_retry_exclude_clause_filters_out_rejected_series_but_keeps_others`.
  2. **Seller Search 동일 계열 버그**: `_build_cache_table()`/`_build_tavily_table()`이 애초에 제외
     파라미터 자체를 받지 않아 "다른 판매처 없어?"도 항상 같은 4곳을 다시 보여줬다. `_excluded_seller_names()`
     추가 + 두 함수에 `excluded_sellers` 파라미터 추가. 회귀 테스트:
     `test_excluded_seller_names_parses_exclude_clause`, `test_cache_table_respects_excluded_sellers`.
  3. **분류 오분류 방어**: `_resolve_resume`(LLM 분류기)가 "저 시리즈 말고 다른 건 없어?" 같은 사실상
     retry 의도의 메시지를 `condition_update`로 오분류하는 걸 실측으로 확인(재현 스크립트로 직접 호출해
     `action='condition_update'` 확인). `condition_update` 분기는 원래 `retry` 분기와 달리 지금 보여준
     카드를 제외 목록에 안 넣어서, 실제 조건 변화가 없으면 같은 카드가 그대로 재검색됐다.
     product_search/seller_search 두 워커의 `condition_update` 분기에도 `retry`와 동일하게 제외 목록
     반영을 추가(seller_search는 `wants_all_comparison`이면 스킵 — "4곳 모두 비교해줘"까지 제외되면 안 됨).
  4. **남은 비결정성(코드 버그 아님)**: 위 수정 후에도 실사용/curl 재현에서 간헐적으로 같은 결과가
     반복되는 경우가 있었는데, 직접 원인을 추적한 결과 (a) `_apply_condition_update`가 명시 패턴에
     안 걸리는 메시지는 LLM 추출기로 넘기는데 이 추출이 호출마다 `product_name` 조건을 다르게 처리할
     수 있고(비결정적), (b) Tavily 실시간 검색 자체가 매 호출 결과가 달라질 수 있어(라이브 웹 검색),
     "정확히 동일한 쿼리"라도 결과가 재현되지 않는 경우가 있다. `run_product_search_pipeline()`/
     `product_search_agent()`를 exclude 절이 포함된 쿼리로 직접 호출해 필터 로직 자체는
     `excluded_series` 사유로 정확히 걸러냄을 반복 검증(스크립트 기반)했으므로, 로직 버그는 해결됐고
     남은 변동성은 LLM 조건 추출/Tavily 라이브 검색의 고유한 비결정성으로 판단(정규식 우선 게이트로
     "고치면" `resolver.py` 삭제 이력의 문제(자유 응답 제한)가 재발할 위험이 있어 시도하지 않음).
  - 검증: `Test/test_product_search_agent_module.py`, `Test/test_seller_search_agent_module.py`,
    `Test/test_orchestration_workers.py` 포함 전체 스위트(무관한 pre-existing 4건 제외) 통과.
- [x] ToolMessage 직접 반환 수정 후에도 남아있던 잔여 중복(모델이 "완료"라는 짧은 확인 문구조차
  반복 생성 → 프론트가 그 텍스트를 done.response보다 우선해 보여줌) 마저 제거:
  1. `product_search_worker_node`/`seller_search_worker_node`의 `_search`가 `product_search_agent`/
     `seller_search_agent`를 항상 `config={"callbacks": []}`로 호출하도록 변경(재시도 여부와 무관 —
     기존 `mute` 조건 분기 제거). 어차피 모델의 생성 텍스트는 버리고 ToolMessage만 쓰므로 스트리밍
     자체가 필요 없어졌고, 이걸 끄지 않으면 모델이 "완료"만 답하라고 시켜도 그조차 반복 생성해
     ("완료완료") 프론트에 잠깐 노출될 수 있었다(실제 curl 재현으로 확인).
  2. `frontend/app/dashboard/page.tsx`의 `done` 핸들러가 "이미 스트리밍된 content가 있으면 유지"
     하던 로직을 되돌려 **항상 `event.response`(백엔드 최종 답변)를 신뢰**하도록 변경 — 이제
     product_search/seller_search는 모델 스트리밍 텍스트와 최종 답변이 다를 수 있다는 게 전제이므로
     (스트리밍 중엔 "완료"만 보이고 실제 목록은 done에만 실림), 스트리밍된 내용을 우선하면 안 된다.
  - 검증: 전체 테스트 스위트(무관한 pre-existing 4건 제외) 통과, `npx tsc --noEmit` 통과.
    **라이브 서버에 curl로 3턴 전체 흐름(조건 질문→TF→PS 결과→시리즈 선택→SS 자동 연결)을 재현해
    원시 SSE로 `done.response`가 두 경우 모두 중복 없이 깨끗함을 재확인.**
- [x] PS/SS 텍스트 완전 중복의 **진짜** 근본 원인 발견 + 수정(위 `_run_search` mute 수정은 틀린 계층을
  고치고 있었음을 실사용 서버 직접 재현으로 확인 후 정정):
  1. **`_run_search` mute 수정이 효과 없었던 이유**: 사용자가 서버를 재시작한 뒤에도 동일하게
     재발 — 파일 mtime이 프로세스 시작 시각보다 이전임을 확인해 "리로드 안 됨" 가설도 배제하고,
     `/chat/stream`에 직접 curl로 동일 시나리오를 재현해 원시 SSE를 캡처했다. 그 결과
     **AIMessage.content 자체(= `done.response`)에 도구 응답 텍스트가 이미 두 번 들어있음**을
     확인 — `_run_search`의 재실행이 아니라, `create_react_agent`가 감싼 gpt-4o-mini에게
     "도구가 반환한 텍스트를 한 글자도 바꾸지 말고 그대로 베껴 출력하라"고 시킨 것 자체가
     소형 모델의 verbatim-copy 반복 생성 실패 모드를 유발하고 있었다(긴 텍스트를 복사하라고
     시키면 소형 모델이 마지막에 처음부터 한 번 더 반복하는 경우가 있음).
  2. **수정**: `product_search_agent()`/`seller_search_agent()`가 모델이 생성한 최종 메시지를
     더 이상 신뢰하지 않고, `create_react_agent`의 결과 메시지 목록에서 `ToolMessage`(=
     `search_products`/`search_sellers` 도구의 원문 반환값)를 직접 찾아 반환하도록 변경.
     시스템 프롬프트도 "베껴 쓰라"는 지시를 없애고 "도구 호출 후 '완료' 한 마디만 답하라"로
     단순화해 모델이 애초에 긴 텍스트를 재생성할 이유 자체를 없앴다. Seller Search가 LLM에게
     맡기던 "[캐시/Tavily 기준]에 따른 안내 문구 추가"는 `_finalize_seller_search_answer()`
     결정론적 후처리로 대체(다운스트림 `parse_seller_markdown_table` 등은 이 마커에 의존하지
     않음을 grep으로 확인 후 진행).
  - 검증: 전체 테스트 스위트(무관한 pre-existing 실패 4건 제외) 통과. **실제 로컬 서버
    (`/chat/stream`)에 curl로 동일 대화 흐름(조건 질문 → TF 답변 → PS 결과 → 시리즈 선택 →
    SS 자동 연결)을 재현해 원시 SSE를 캡처/분석 — PS/SS 응답 모두 중복 없이 1회만 출력되고
    PS 선택 후 SS로 자동 연결되는 것까지 실제 API 호출로 확인함.**
  - 교훈: 이전 두 차례 수정(`config=None` → `config={"callbacks": []}`)은 모두 "같은 LLM 호출이
    두 번 실행돼 스트리밍이 중복된다"는 잘못된 가설 위에서 이뤄졌고, 실사용 재현 스크린샷이 반복
    재발하는데도 가설을 검증 없이 다음 단계로 넘어간 게 원인이었다. 최소 재현 스크립트로 가설을
    직접 검증(callbacks=[]가 실제로 이벤트를 막는지)하는 것과, 라이브 서버에 직접 재현해 원시
    데이터(SSE)를 보는 것 사이의 차이 — 전자는 메커니즘이 "작동할 수 있음"만 증명하고, 실제
    프로덕션에서 "그 메커니즘이 문제의 원인"이라는 건 증명하지 못했다.
- [x] 실사용 재테스트에서 발견한 PS/SS 텍스트 완전 중복(단순 flash 아님) + PS 선택 후 SS 미연결 버그 수정
  (systematic-debugging으로 근본 원인 추적, 계획 없이 바로 수정):
  1. **완전 중복의 진짜 원인**: 지난 세션에 프론트 `done` 핸들러 수정(이미 스트리밍된 content 유지)으로
     "flash"는 없앴지만, 실제로는 `_run_search()`(workers.py) 자체가 같은 턴 안에서 답변을 **두 번
     생성**하고 있었다 — `@task`가 astream_events 조합 엣지케이스로 `None`을 반환하면 `_run_search`가
     `task_fn.func`로 원본 함수를 다시 실행하는데, 이 "실패한" 첫 시도도 실제로는 끝까지 실행되어(Tavily
     검색 + react agent LLM 호출 + 스트리밍까지) 이미 사용자에게 스트리밍된 뒤 반환값만 유실된 것이었다.
     재실행이 `product_search_agent`/`seller_search_agent`를 **같은 config로 다시 호출해 스트리밍
     이벤트를 또 발생**시키던 것이 중복의 정체(지난 세션엔 재현 스크린샷이 없어 "done 시점 flash"로
     오진단했었음).
     **1차 수정 실패 + 정정**: 처음엔 재실행 시 `config=None`으로 호출하면 astream_events가 그 이벤트를
     못 볼 거라 가정했는데, 사용자 재테스트에서 중복이 그대로 재발함 → 최소 재현 스크립트로 직접 검증한
     결과 **LangChain이 콜백을 contextvar로 자동 전파해 `config=None`을 넘겨도 조상 실행의 콜백을 그대로
     물려받음**(가정이 틀렸음을 실측으로 확인). `config={"callbacks": []}`로 콜백을 명시적으로 비워야만
     실제로 이벤트가 안 잡힌다는 것도 같은 방식으로 검증 후 `product_search`/`seller_search`의 `_search`
     클로저를 `config={"callbacks": []} if mute else config`로 수정(product_analysis의 `_search`는
     config/스트리밍 자체가 없어 `mute` 무시).
     회귀 테스트: `RunSearchTaskFallbackTest`를 폴백 호출에 `mute=True`가 전달되는지 검증하도록 갱신,
     `SearchMuteConfigTest`를 신규 추가해 실제 `product_search_worker_node` 경로에서 폴백 호출이
     `config={"callbacks": []}`로 나가는지 회귀 검증.
  2. **시리즈 선택 후 판매처 탐색 미연결**: product_search 리뷰 카드 문구("다음 단계에서 사용할 시리즈를
     선택해주세요")가 선택 후 이어짐을 약속하는데도, 원 요청에 seller_search가 없으면 확인 메시지만
     남기고 끝났음. seller_search 완료 시 `_ensure_product_analysis_requested()`로 항상 product_analysis로
     잇던 것과 동일 패턴으로 `_ensure_seller_search_requested()`를 추가해 product_search 선택 완료 시
     seller_search가 항상 이어지도록 함.
  - 검증: `Test/test_orchestration_workers.py`/`test_orchestration_supervisor.py` 34개 통과, 전체 스위트
    (무관한 pre-existing 실패 4건 제외) 통과. 실서버 스트리밍 재현은 다음 실사용 테스트에서 확인 필요.
- [x] 사용자 요청으로 Product Search/Seller Search 답변 포맷 재정리 + 스트리밍 텍스트 중복 노출 버그 수정:
  1. **Product Search**: `format_product_search_results()`에서 "근거: {evidence_text}" 부착을 제거해
     "N. 시리즈명 / 추천 이유: ..." 두 줄만 남기도록 단순화(`Agent/product_search_agent.py`). 파서
     (`_PRODUCT_HEADER_RE`/`_PRODUCT_REASON_RE`)는 `^\s*` 허용이라 변경 불필요.
  2. **Seller Search**: `_build_cache_table()`/`_build_tavily_table()`이 판매 중(가격/링크 확인된) 판매처만
     나열하도록 변경(전부 없으면 안내 문구만 반환), 포맷을 "N. 판매처명 / 추천 이유: / URL:"로 변경(기존
     "판매처명 — 상태 · 가격", "바로가기" 라벨 제거). `_SELLER_HEADER_RE`/`_SELLER_FIELD_RE`/
     `_parse_seller_prose_blocks()`도 새 포맷에 맞춰 갱신(상태/가격 헤더 분리 로직 제거).
     `Test/test_seller_search_agent_module.py`의 `test_tavily_table_only_uses_supported_domains`가 옛
     "검색 결과 없음" 문구를 전제로 해 새 동작(판매 중인 곳만 표시)에 맞게 갱신, 미발견 케이스 테스트
     (`test_tavily_table_reports_when_no_seller_found`) 추가.
  3. **프론트엔드 중복 노출 버그**: `frontend/app/dashboard/page.tsx`의 `done` 핸들러가 이미 스트리밍으로
     그려진 `content`를 `event.response`(백엔드가 의도적으로 같은 텍스트를 재전송)로 무조건 덮어써
     "텍스트가 한 번 더 나타났다 사라지는" 것처럼 보이던 버그 수정 — 이미 스트리밍된 content가 있으면
     유지. 아울러 `progress` 핸들러가 `stream` 이벤트로 `null`이 된 `progressSteps`를 `?? []`로 되살려
     렌더가 진행 스피너 브랜치로 튀었다 돌아오는 깜빡임도, `progressSteps === null`이면 무시하도록 수정.
  - 검증: `Test/test_seller_search_agent_module.py`/`test_product_search_agent_module.py`/
    `test_orchestration_workers.py` 64개 통과, `npx tsc --noEmit`로 `page.tsx` 타입 확인, 전체 스위트
    재확인(무관한 pre-existing 실패 4건은 변동 없음 — langmem 미설치로 인한 collection 에러 포함).
- [x] 리뷰 카드 응답 중 "선택 + 새 요청" 복합 메시지 처리 버그 2건 수정 (사용자 스크린샷 재현: "머큐리얼
  수퍼플라이로 할게 이걸 판매하는 곳은 어디야"):
  1. **할루시네이션**: `_resolve_resume`가 사용자 메시지를 `select`/`retry`/`condition_update`/`reset`/
     `question` 5개 중 하나로만 강제 분류하는데, "선택 + 판매처 질문"이 섞인 메시지가 `question`으로
     오분류되고, `question` 분기가 분류기의 `message`를 무조건 신뢰해 카드에 없는 정보(판매처)를
     지어냄("머큐리얼 수퍼플라이를 판매하는 곳은 '머큐리얼 수퍼플라이'입니다" 같은 무의미한 답).
     `PendingResolution`에 `grounded: bool` 필드를 추가하고, `_RESOLUTION_SYSTEM`에 "카드에 없는
     정보면 grounded=false로" 지침 추가. 세 워커(product_search/seller_search/product_analysis)의
     `question` 분기 전부, `grounded`가 false거나 message가 비어있으면 분류기 답 대신 고정 안내
     문구(`_UNGROUNDED_QUESTION_FALLBACK`)를 쓰도록 수정 — 프롬프트 지침 + 코드 레벨 가드 이중 방어.
  2. **복합 요청 유실**: 설령 나중에 `select`로 올바르게 분류돼도, 메시지에 섞여 있던 새 요청
     (예: seller_search)은 그냥 사라지고 있었음(select 분기가 선택만 처리, 추가 요청 감지 로직 없음).
     `PendingResolution`에 `followup_capabilities: list[Capability]` 필드를 추가해 분류기가 select와
     함께 감지하도록 하고, `product_search_worker_node`/`seller_search_worker_node`의 select 분기가
     이걸 `requested_capabilities`에 큐잉하도록 수정(신규 `_merge_requested_capabilities()` 헬퍼로
     일반화 — 기존 `_ensure_product_analysis_requested()`도 이걸 재사용하도록 리팩터). PA의 select
     분기는 구매 흐름(`purchase_prepare_node`)으로 직행하는 별개 경로라 범위 밖으로 둠.
  - 회귀 테스트: `Test/test_orchestration_workers.py`에 `test_select_with_embedded_followup_request_queues_next_capability`,
    `test_ungrounded_question_answer_is_replaced_with_fallback` 추가. 오케스트레이션 스위트 33개 전부 통과.
- [x] 판매처 선택 후 잘못된 라우팅(엉뚱하게 product_search 시리즈 카드로 튐) + 판매처 리뷰 카드
  "모두 비교해줘" 응답 시 동일 카드 무한 반복 버그 2건 수정, supervisor의 replan 구조 개선:
  1. **버그 A(반복 카드)**: `seller_search_worker_node`의 `condition_update` 분기(`_resolve_resume`의
     few-shot이 "판매처 4곳 모두 비교해줘"를 `condition_update`로 유도함)에 `product_analysis_worker_node`
     에는 있던 `wants_all_comparison(resume)` 확정 가드가 빠져 있어, 재검색 후 동일 카드로 다시
     `interrupt()`하던 회귀(`executor.py`→`workers.py` 리팩터링 중 seller_search 쪽만 누락). 가드 추가.
  2. **판매처 선택 완료 → product_analysis 미연결**: 리뷰 카드 문구("상세 분석에 사용할 판매처를
     선택해주세요")가 이미 분석으로 이어짐을 약속하는데도, 원래 요청에 `product_analysis`가 없으면
     이어지지 않던 문제. `_ensure_product_analysis_requested()` 헬퍼를 추가해 seller_search 완료
     시점(4개 반환 경로 전부)에 `requested_capabilities`에 `product_analysis`를 자동 추가.
  3. **버그 B(순서 무시)**: `supervisor_node`가 매 턴 "다음에 뭐 할지" 하나만 LLM에게 묻고, 그 답이
     `remaining_requested`(아직 안 한 요청) 안에만 있으면 순서 상관없이 그대로 채택해, `product_search`
     와 `seller_search`가 함께 남아있어도 LLM이 `seller_search`부터 골라버릴 수 있었음(제품 확정 전에
     판매처가 먼저 나오는 엇갈림). LangGraph 공식 Plan-and-Execute 튜토리얼의 `replan_step`(원본은
     매 스텝 후 `input`+`plan`+`past_steps` 전체를 보고 남은 계획 전체를 통째로 재생성, `execute_step`은
     항상 `plan[0]`만 기계적으로 집행)과 대조해 구조적 차이를 확인 — `SupervisorDecision`에
     `remaining_order`(남은 capability를 지금 상황 기준으로 재정렬한 전체 리스트) 필드를 추가하고,
     `supervisor_node`는 `decision.next`가 아니라 항상 `remaining_order[0]`(빠진 항목은 기존 순서로
     보충)만 집행하도록 변경. 순서를 하드코딩하지 않고 매 턴 LLM이 다시 판단하게 해 에이전틱함 유지.
  4. **모델 교체**: `_get_supervisor_classifier()`를 `gpt-4o-mini`(API에서 곧 완전 은퇴 수순인 레거시
     모델)에서 `gpt-5.4-nano`(현재 시점 최신 저비용 경량 구조화 출력 모델)로 교체.
  - 회귀 테스트: `Test/test_orchestration_workers.py`에 `condition_update`+전체비교 케이스,
    판매처 선택 시 `requested_capabilities` 자동 추가 케이스 추가. `Test/test_orchestration_supervisor.py`
    에 `remaining_order`가 `decision.next`의 순서 이탈을 덮어쓰는지, 빈 `remaining_order`일 때 기존
    리스트 순서로 폴백하는지 검증하는 테스트 추가. 전체 스위트 통과(무관한 pre-existing 실패 4건은
    변동 없음 — `test_purchase_prepare_graph.py`/`test_response_performance_optimizations.py`).
- [x] product_search에 `series`를 4번째 필수 조건으로 추가 (`Agent/LangGraph_buyeragent_with_personalization.py`
  `check_conditions`/`ask_missing_node`, `Agent/product_search_agent.py`
  `SERIES_OPTIONS_BY_BRAND`/`series_options_for_brand()`): brand/budget/surface가 다 채워졌고 그 브랜드에
  큐레이션 시리즈가 있는데 `product_name`이 없으면 "이 브랜드엔 이런 시리즈가 있어요" 카드 질문을 한 번 더
  띄움(뉴발란스처럼 큐레이션 시리즈가 0개인 브랜드는 질문 없이 기존 자유검색으로 폴백). 목적은 Tavily가
  13개 시리즈 화이트리스트에 안 걸리는 이름을 반환해 조용히 "찾지 못했습니다"로 끝나던 실패를, 검색 전에
  확정된 시리즈명으로 캐시/필터가 항상 걸리게 만드는 것. `_extract_explicit_product_conditions`에도
  `_requested_series_name()` 기반 결정적 시리즈 추출을 추가해 "나이키 머큐리얼 베이퍼 10만원대 추천" 같은
  단발 요청은 질문 없이 바로 `product_name`이 채워지게 함. 새 노드/새 상태 필드 없음(기존 `product_name`
  조건과 `ask_missing_node`/`RequirementChoices` 카드 UI 재사용). 회귀 테스트
  `Test/test_product_search_followup_routing.py`에 5개 추가, 관련 스위트 67개 전부 통과 확인.
- [x] `extract_conditions_and_intent` few-shot 보강으로 product_search ↔ product_guide 오분류 수정: "공격수는
  축구화 고를 때 뭘 우선으로 봐야 해?", "포지션별로는 어떤 스터드를 사용하는 게 좋아?"가 product_search로
  오분류되던 케이스를 few-shot 예시 2개 추가로 해결. 추가 직후 "그럼 TF는?"(직전 추천 이어서 표면 조건만
  바꿔 묻는 follow-up)이 product_guide로 새로 오분류되는 회귀 발생 → 대비 예시("FG랑 TF 차이가 뭐야?"는
  guide, "그럼 TF는?"은 이어서 묻는 search) 1개 더 추가해 해결. `python Test/eval_intent_extraction.py`
  19/19(100%) 확인. 이전에 버그란에 있던 "그럼 TF는?" 오분류 우려 항목도 이걸로 해소.
- [x] "cannot unpack non-iterable NoneType object" 실사용 버그 수정 (`orchestration/workers.py:476`,
  `cards, response = await _search([])`): 나이키+공격수 조건 → "10만원대 TF" 답변 시 재현, 같은
  세션의 다음 무관한 메시지에서도 곧바로 재발. `FastAPI/main.py`의 `/chat`, `/chat/stream` 예외
  핸들러가 트레이스백 없이 `str(exc)`만 프론트로 보내던 것부터 문제 — `logger.exception()`을 추가해
  실제 트레이스백을 확보. 확보한 트레이스백으로 확인한 근본 원인은 애플리케이션 코드가 아니라
  langgraph 자체의 엣지케이스: 이전에 `@task(name="product_search_search")`(및 seller_search/
  product_analysis 동일 패턴)로 스케줄된 호출 기록에 RETURN/ERROR 쓰기가 없으면, `interrupt()` 재개 +
  `astream_events`(=`/chat/stream`이 쓰는 경로) 조합에서 langgraph가 결과를 조용히 `None`으로
  resolve함(`langgraph/pregel/_runner.py`의 `_acall_impl`, langgraph 1.0.8 설치 버전 확인).
  `graph.ainvoke()`로는 100% 재현 안 되고 `astream_events`로만 재현되는 것을 직접 스크립트로 검증
  (실제 대화 흐름 그대로 재생); 한 번 발생하면 해당 스레드 체크포인트에 남아 이후 턴까지 오염시키는
  것도 확인. `[[interrupt() 재개 시 검색이 다시 실행되는 버그]]`(바로 아래 항목)에서 이 memoization을
  위해 `@task`를 도입한 게 이 문제의 전제 조건 — langgraph 내부라 직접 고칠 수 없으므로 `workers.py`에
  `_run_search(task_fn, *args)` 헬퍼를 추가해 9개 호출부(product_search/seller_search/
  product_analysis 워커의 `_search` 호출) 전부를 이걸 통하도록 변경 — task 호출 결과가 `None`이면
  `task_fn.func`(장식되지 않은 원본 함수)로 한 번 더 직접 실행해 우회. `Test/test_orchestration_workers.py`에
  `RunSearchTaskFallbackTest` 회귀 테스트 추가. langgraph 업그레이드로 이 엣지케이스가 사라지면 헬퍼
  제거 검토.
- [x] `/code-review high` findings 중 나머지 4건 수정 (9번 `sub_agent_0310.py` 관련 finding은 그
  파일 자체가 현재 플로우에서 미사용이라 스킵):
  1. **가격대 필터링 불일치**: `product_analysis_agent.py`의 `_extract_price_range`가 자체 정규식으로
     "이상"의 상한을 999,999로 캡핑해, `product_search_agent.py`/`seller_search_agent.py`가 쓰는
     `_extract_requested_price_range`(상한 9,999,999)와 같은 문구("10만원 이상")에 대해 서로 다른
     결과를 냈음(예: 105만원 상품이 analysis에선 걸러지고 search에선 안 걸러짐). 중복 로직을 지우고
     `product_analysis_agent.py`가 `product_search_agent._extract_requested_price_range`를 그대로
     재사용하도록 통합(단, 실패 시 `DEFAULT_PRICE_RANGE` 폴백은 유지). 기존 회귀 테스트 기대값도
     새 상한(9,999,999)에 맞게 갱신.
  2. **브랜드/지면 키워드 테이블 중복**: `LangGraph_buyeragent_with_personalization.py`의
     `_EXPLICIT_BRAND_PATTERNS`/`_EXPLICIT_SURFACE_PATTERNS`가 `product_search_agent.py`의
     `BRAND_RULES`/`BOOT_SURFACE_KEYWORDS`와 내용이 사실상 동일(지면 목록은 `MG` 하나만 빠짐)한데도
     각자 따로 관리되고 있었음. 로컬 정의를 지우고 `product_search_agent`에서 import해서 공유하도록
     변경 — 앞으로 브랜드/지면 별칭을 추가/수정할 때 한 곳만 고치면 됨.
  3. **interrupt() 재개 시 검색이 다시 실행되는 버그**: `orchestration/workers.py`의 3개 워커
     (product_search/seller_search/product_analysis) 모두 `_search()`(실제 Tavily/캐시/크롤 호출)를
     `interrupt()` 루프 진입 전에 호출하는데, LangGraph는 resume 시 노드 함수 전체를 처음부터 다시
     실행하므로 단순 "카드 선택" 응답에도 `_search()`가 매번 재실행되어, 사용자가 실제로 본 카드
     목록과 선택 인덱스를 매칭하는 `cards`가 서로 다른 실행 결과일 수 있었음(재조회 결과가 다르면
     엉뚱한 카드가 선택될 수 있음). `langgraph.func.task`가 `StateGraph` 노드 안의 클로저 함수에도
     정상 동작하는지 별도 스크립트로 먼저 검증(재실행 시 메모이즈되어 실제 호출은 다시 안 일어나되,
     인자가 바뀐 재시도는 정상적으로 새로 실행됨을 확인) 후, 3개 워커의 `_search`에 각각
     `@task(name=...)`를 적용. 부수 효과로 단순 select resume마다 반복되던 불필요한 검색 호출도
     줄어듦.
  - 검증: `Test/test_orchestration_workers.py`(interrupt/resume round-trip 포함 20개) 등 전체
    테스트 스위트(무관한 pre-existing 실패 4건 제외) 통과.
- [x] `/code-review high` 실행 후 발견된 최우선 순위 버그 3건 수정 (나머지 findings는 별도 진행 예정):
  1. **`check_conditions`가 죽은 `search_result` 필드를 참조**: orchestration 리팩터링 이후 어떤 워커도
     `state["search_result"]`를 쓰지 않는데, `check_conditions`는 여전히 그 값을 seller_search/product_analysis
     실행 가능 여부 판단에 썼음(항상 빈 값 → `user_conditions["product_name"]`만으로 게이트). product_search에서
     시리즈를 선택해도 그 결과는 `selected_series`/`last_products`에 남지, `user_conditions["product_name"]`엔
     안 남아서, "그럼 어디서 파는지 알려줘" 같은 후속 seller_search 요청이 부당하게 `ask_missing_node`로 튕겨나감.
     `state.get("selected_series") or state.get("last_products") or state.get("products")`로 게이트 조건 교체.
  2. **거절한 시리즈가 재시도 캐시 조회에서 다시 나올 수 있음**: `workers.py`가 재시도 시 쿼리에 붙이는
     `"exclude: A, B"` 절을 `seller_search_agent.py`(`_EXCLUDE_CLAUSE_RE`)는 제거하고 캐시 키워드를 뽑는데
     `product_search_agent.py`(`_requested_series_name` → `_raw_cache_search_keyword`)는 제거하지 않아, 거절된
     시리즈명이 substring 매칭으로 다시 검색 키워드가 되어 `load_raw_items_cache`가 그 시리즈를 재서빙했음.
     `product_search_agent.py`에 공용 `_strip_exclude_clause()`를 추가해 두 파일이 공유하도록 정리(중복 정규식 제거).
  3. **`seller_search_agent.py`의 카포스토어 도메인 오타**: `cafostore.co.kr`(오타) vs 실제 `capostore.co.kr`.
     `product_search_agent.py`는 이미 올바른 값을 쓰고 있었음(그 파일의 테스트가 `cafostore.co.kr` 금지를
     명시적으로 검증). `SELLER_DOMAINS`/`SELLER_URL`/`DOMAIN_TO_SELLER` 및 `Test/test_seller_search_agent_module.py`의
     회귀 테스트 값을 `capostore.co.kr`로 수정.
  - 검증: `Test/test_seller_search_agent_module.py`, `test_product_search_agent_module.py`,
    `test_product_search_followup_routing.py`, `test_orchestration_workers.py`, `test_orchestration_supervisor.py`,
    `test_raw_items_cache.py` 72개 전부 통과.
- [x] Product Search 답변이 여전히 markdown 표로 나오는 문제 수정: `search_products` 도구의 docstring이
  "markdown 표로 반환합니다"라고 남아있어(이전 세션에서 표→프로즈 변환 시 갱신 안 됨) `@tool` 데코레이터가
  이를 LLM의 함수 설명으로 그대로 넘겨줬고, ReAct agent가 이 설명을 근거로 최종 답변을 표로 재구성했음.
  docstring을 "번호 목록 텍스트(표 아님)"로 수정하고, `PRODUCT_SEARCH_SYSTEM_PROMPT`/`SELLER_SYSTEM`에
  "마크다운 표(|, --- 문법)로 재구성하거나 요약하지 마세요"를 명시적으로 추가(방어적 보강). 아울러 사용자
  요청에 따라 Product Search 표시 텍스트를 시리즈명 + 추천 이유 2개 필드로 단순화(`format_product_search_results`/
  `parse_product_markdown_table` 축소, 가격/URL은 내부 파이프라인 데이터에는 남지만 표시 텍스트에서는 제거 —
  카드 데이터의 URL은 `_ensure_product_links`가 자동으로 채워주므로 영향 없음).
- [x] Product Search 캐시 상품 brand_mismatch 오탐 수정 + Seller Search 캐시 조회 안정화 (사용자 실사용
  재테스트에서 발견, 계획 파일 `product-purring-walrus.md` 기준):
  1. **Product Search**: `_raw_cache_search_items()`가 만드는 캐시 상품은 `brand=None`이라 `detect_brand()`가
     `raw_name` 텍스트에 "나이키"가 문자 그대로 있는지만 확인하는데, 실제 레드사커/카포스토어류 캐시 상품
     제목은 브랜드명 없이 시리즈명만 있는 경우가 많아(예: "줌 머큐리얼 베이퍼 16 프로 TF...") `brand_mismatch`로
     잘못 거부되고 있었음. `SERIES_DESCRIPTIONS`와 동일한 13개 키로 `SERIES_BRAND` 매핑을 추가하고,
     `normalize_product_item()`에서 `detect_brand(item) or SERIES_BRAND.get(series_name)`로 시리즈명 기반
     브랜드 추론 폴백을 추가(이 카탈로그의 시리즈명은 브랜드 전용이라 안전). 명시적으로 다른 브랜드인 상품은
     기존처럼 정상 거부됨(회귀 테스트 유지).
  2. **Seller Search**: `search_sellers(keyword, min_price, max_price)`가 이 세 인자를 LLM(react agent)이
     자유 텍스트에서 직접 만들어내도록 맡겨두고 있었는데, 가이드가 전혀 없어 "판매처 추천" 같은 접미사가
     keyword에 그대로 남을 수 있었음(Tools/TODO.md의 `_RAW_CACHE_STOPWORDS` 수정과 결합된 문제). 도구를
     Product Search의 `search_products(query: str)`와 동일한 패턴으로 바꿔 `(query: str)` 하나만 받고,
     내부에서 `_extract_requested_price_range`(product_search_agent에서 재사용)로 가격을, `_seller_search_keyword`
     (신규, exclude 절과 가격 문구 제거)로 keyword를 결정적으로 추출하도록 변경. `seller_search_worker_node`의
     쿼리 빌더도 product_search와 동일하게 budget/surface 조건을 포함하도록 수정.
- [x] Product Search/Seller Search 답변을 카드 파싱용 markdown 표 대신 번호 목록 프로즈("N. 이름 — 상태" +
  들여쓴 "정보/가격/추천 이유/참고 링크" 라벨 줄)로 변경. `product_search_agent.format_product_search_results`,
  `seller_search_agent._build_cache_table`/`_build_tavily_table`을 재작성하고, 같은 결정적 파서(`parse_product_markdown_table`,
  `parse_seller_markdown_table`)를 새 포맷 기준으로 다시 작성해 LLM 폴백 없이 카드 데이터(`last_products`/`last_sellers`
  후속 참조용)를 계속 추출한다. Seller 쪽은 과거 파이프-표 포맷도 `_parse_seller_legacy_table`로 폴백 유지(회귀 테스트
  `test_seller_table_parser_enriches_legacy_price_table` 호환). 시스템 프롬프트("표를 그대로 출력")도 "표" 관련 문구 제거.
- [x] SS 카드 단일 선택 한계 + PA "모두 비교"/"판매처 제외" 후속 요청 버그 2건 수정 (사용자 프론트엔드 실사용
  재테스트에서 발견, 계획 파일 `buyer-agent-soft-hartmanis.md` 기준):
  1. **버그 A(판매처 재주입)**: `product_analysis_worker_node`가 `state["selected_seller"]`(이전 SS 선택)를
     쿼리 텍스트에 무조건 다시 박아넣어, "4곳 모두 비교해줘"라고 조건을 지워도 `product_analysis_agent`의
     `_extract_sellers()`가 쿼리 텍스트에 남은 판매처명을 스캔해 그 판매처로만 좁혀지던 문제. 쿼리 생성을
     `_build_query(conditions, latest_message)` 헬퍼로 빼서 `wants_all_comparison()`이면 판매처명을 아예
     넣지 않도록 하고, 최초 진입/`condition_update` 재시도 양쪽에서 최신 메시지 기준으로 매번 재계산하도록 수정
     (기존엔 최초 1회만 계산되어 클로저에 캡처된 stale 쿼리를 재시도에도 그대로 재사용하던 부수 버그도 같이 해결).
  2. **버그 B(reset 오분류 + 판매처 제외 표현 불가)**: "크레이지11 말고 나머지 판매처에서"가 `_RESOLUTION_SYSTEM`
     프롬프트의 `reset` 예시("아 됐고 판매처 검색해줘")와 표현이 비슷해 `reset`으로 오분류되어 `selected_series` 등
     맥락이 지워진 채 엉뚱하게 ss_review로 되돌아가던 문제. 프롬프트에 판매처 변경/제외 요청은 `condition_update`
     라는 예시를 명시하고 `reset`은 "조건 조정이 아니라 완전히 다른 요청/취소"로만 한정하도록 재작성. 또한
     `_extract_excluded_sellers()`(말고/빼고/제외 패턴 + `_SELLER_ALIASES`)를 추가해 `_apply_condition_update()`가
     제외 대상의 여집합(나머지 판매처)을 `conditions["seller"]`에 합쳐 넣도록 지원 — 기존엔 seller 조건이 단일
     포함 값만 표현 가능해 "이거 빼고 나머지" 의미 자체를 표현할 방법이 없었음.
  3. **프론트엔드**: `requirement-choices.tsx`에 `multiSelect` prop 추가 — SS 카드(`pendingAction.type ===
     "ss_review"`)에서만 체크박스로 여러 판매처를 고른 뒤 "선택 완료" 버튼으로 한 번에 확정(선택된 라벨을
     콤마로 합친 문자열 하나로 기존 `onSelect` 호출, 백엔드 포맷 변경 없음). PS/PA 카드와 조건 수집 질문은
     기존 클릭 즉시 확정 방식 유지.
  4. **(실서버 시나리오 검증 중 추가 발견)** 버그 B 수정은 리뷰 interrupt 재개 경로(`_apply_condition_update`)에만
     적용돼 있었는데, 실제로 "4곳 모두 비교해줘"가 `wants_all_comparison()`으로 인해 리뷰 없이 바로
     `status=done`으로 끝나는 케이스가 많아 그 다음 "크레이지11 말고 나머지에서" 메시지는 리뷰 재개가 아니라
     **새 턴(fresh entry)**으로 `product_analysis_worker_node`에 들어간다 — 이 경로는 `_analysis_conditions()`가
     담당하는데, 여기엔 제외 표현 지원이 없어 `_latest_message_seller_crawlers()`가 "크레이지11"을 그대로
     포함 조건으로 오인하는 반대 방향 버그가 실서버 테스트로 확인됨. `_analysis_conditions()` 최상단에도
     `_extract_excluded_sellers()` 체크를 추가해 동일한 여집합 로직을 적용 — 실서버 재검증 결과 "판매처:
     사커붐, 레드사커, 카포스토어"로 정상 확인(제외 요청 후 후속 검색이 0건인 것은 별개의 기존 이슈,
     `_extract_explicit_product_conditions`/구조화 추출기가 이전 턴 답변에 등장한 여러 상품명을 product_name에
     섞어 넣는 pre-existing LLM 추출 한계 — 132번 항목에서 이미 "보험성 조치"로만 완화해뒀던 것과 동일 현상).
  - 회귀 테스트: `Test/test_orchestration_workers.py`에 `SellerExclusionTest`/
    `ApplyConditionUpdateSellerExclusionTest` 신규 클래스 + `test_all_comparison_request_ignores_previously_selected_seller`
    + `test_analysis_conditions_excludes_named_seller_on_fresh_entry` 추가. 전체 스위트 99 passed(+4 신규 테스트) /
    pre-existing 4건(무관)은 변동 없음.
- [x] 사용자 프론트엔드 실사용 테스트에서 발견한 PS 품질 이슈 3건 수정:
  1. **스트리밍 미작동**: `product_search_agent`/`seller_search_agent`가 `create_react_agent`로 감싸져
     있어 실제 LLM 호출이 중첩된 서브그래프 안에서 일어나는데, 그 서브그래프의 `langgraph_node` 메타데이터는
     바깥 워커 노드 이름이 아니라 `create_react_agent`가 고정으로 쓰는 내부 노드명 `"agent"`로 찍힌다는 걸
     발견 — `FastAPI/main.py`의 `_STREAMING_NODE_NAMES`가 `product_search_worker_node`/
     `seller_search_worker_node`를 보고 있어서 전부 걸러지던 것이 원인. `"agent"`로 교체해 해결(실서버
     확인: 이벤트 0개 → 501개). 부수적으로 `product_search_agent`/`seller_search_agent`가 상위 `config`
     (콜백)를 받아 react agent의 `ainvoke`에 전달하도록 수정하고, `product_search_worker_node`/
     `seller_search_worker_node`의 `config` 파라미터 타입을 `RunnableConfig | None`에서 `RunnableConfig`
     (Optional 아님)로 변경 — LangGraph가 Union 타입 힌트는 config 자동 주입 대상으로 인식하지 못해
     항상 `None`이 들어오고 있었음(경고 메시지로 확인, 격리 스크립트로 재현).
  2. **시리즈명이 SKU 단위로 쪼개짐**: "머큐리얼 베이퍼 16"이 가격만 다른 여러 행으로 중복 표시되던 문제.
     `extract_series_name()`이 세대 번호(예: "16")를 일부러 붙이던 로직을 제거(시리즈 추천은 SKU 단위가
     아니라 라인업 단위여야 함), `dedupe_extracted_series()`의 dedup 키에서 가격/판매처를 빼고 같은
     시리즈+지면 중 최저가 1개만 남기도록 변경.
  3. **추천 이유가 필터 매칭 문구뿐**: "나이키 조건에 맞습니다, 10만원대 예산대에 들어옵니다" 같은 규칙
     매칭 사유만 있고 시리즈 자체 설명이 없던 문제. `SERIES_DESCRIPTIONS` 딕셔너리를 추가해 `SERIES_PATTERNS`의
     각 시리즈에 대해 직접 큐레이션한 1줄 설명(예: "머큐리얼 베이퍼: 나이키 스피드 라인의 서브 모델...")을
     `build_recommendation_reason()`이 우선 노출하도록 수정 — LLM이 즉석 생성하지 않고 고정 텍스트만
     사용해 스펙 hallucination 위험 없음.
- [x] Agentic orchestration 리팩터링 실서버 시나리오 검증(PS/SS/PA 단독 + PS→SS/SS→PA/PS→SS→PA 조합, 6종 전부 통과)
  과정에서 발견해 수정한 실버그들:
  1. **`is_no_result_answer` 접두어 충돌**: `Agent/product_search_agent.py`의 성공 응답과 실패 응답이 둘 다
     "지원 판매처 4곳의 Tavily 검색 결과에서"로 시작해, 짧은 공통 접두어만 보던 가드가 성공 응답까지
     "결과 없음"으로 오판 → `_parse_products`가 항상 빈 배열을 반환해 product_search 카드가 전혀 안 뜨던
     문제. 실패 문장 전체("...찾지 못했습니다")를 접두어로 써서 성공 응답과 구분되게 수정.
  2. **Supervisor가 `requested_capabilities`를 힌트로만 취급**: PS 단독 요청에도 LLM이 임의로 seller_search를
     먼저 고르는 등 요청 밖 capability로 이탈. `Agent/orchestration/supervisor.py`에 결정론적 백스톱 추가
     (아직 처리 안 된 요청 capability가 남아있으면 LLM이 뭘 고르든 그걸 우선).
  3. **위 백스톱의 우선순위 버그**: "이미 실행한 단계는 반복 안 함" 체크가 "아직 처리 안 된 요청이 남아있음"
     체크보다 먼저 실행돼서, SS→PA에서 LLM이 seller_search를 다시 고르면(past_steps에 있으니) PA를 건너뛰고
     바로 FINISH — 실서버 테스트로 3번 재현 확인. 우선순위를 "남은 명시적 요청 > 전부 완료시 FINISH > 자유
     판단시 반복 방지"로 재정렬.
  4. **워커 select 분기의 messages 누락 → 빈 응답 500 에러**: `product_search_worker_node`/
     `seller_search_worker_node`의 카드 선택(select) 분기가 확인 메시지를 전혀 안 남겨서, 다음에 실행할
     단계가 없으면(예: PS 단독) 그 턴에 AIMessage가 하나도 안 쌓여 `_build_chat_response`의 최종 응답이
     빈 문자열이 되고 FastAPI가 "Empty agent response" 500을 반환하던 문제. 각 select 분기에 확인 메시지
     추가(`'{name}' 시리즈로 확인했습니다.` 등). `condition_update` 분기의 재검색 결과가 빈 경우 처리도
     PS/SS/PA 세 워커 모두 일관되게 맞춤.
  5. **(코드 버그 아님, 환경 이슈)** 이번 세션 내내 `backend/venv`가 아니라 글로벌 pyenv python으로 서버/테스트를
     돌리고 있었음 — `venv`에는 이미 `playwright`+크로미움이 설치돼 있었는데 글로벌 환경엔 없어서
     product_analysis의 실제 크롤링이 `ModuleNotFoundError`로 실패. `venv`로 전환하고 `pytest`만 추가 설치
     (venv에 없었음 — `Test/TODO.md` 기존 기록과 일치).
- [x] Product Search가 요청하지 않은 브랜드/시리즈를 추천 카드로 보여주던 버그 수정: 지원 판매처 4곳 Tavily 검색이 브랜드+가격+지면 필터를 통과 못 하면 `build_product_search_fallback_answer()`가 반환하던 하드코딩 멀티브랜드 가이드 텍스트가 `_parse_products()`의 LLM 추출기를 거쳐 그대로 "추천 카드"로 둔갑하던 문제. (1) `Agent/product_search_agent.py`에 `is_no_result_answer()` 추가, `_parse_products()`가 "결과 없음" 안내 텍스트는 LLM 파싱 없이 즉시 빈 배열을 반환하도록 가드. (2) Seller Search만 쓰고 있던 `Tools/crawl_and_index.py`의 `load_raw_items_cache()`를 Product Search 파이프라인에도 연결(`_raw_cache_search_keyword`/`_raw_cache_search_items`, `build_product_search_pipeline_result(..., extra_items=...)`) — 실제로는 캐시에 이미 나이키 머큐리얼 베이퍼/수퍼플라이 100건 이상(TF/FG, 10만원대 포함)이 있었는데 라이브 Tavily 검색만 쓰다 실패해 폴백 문구로 빠지던 것이 근본 원인이었음. (3) `classify_product_item()`에 `_matches_requested_series()` 시리즈 필터 추가(브랜드/가격 필터와 동일한 opt-in 방식), `SERIES_PATTERNS`에 "머큐리얼 수퍼플라이"/"머큐리얼 베이퍼" 세부 패턴 외에 일반 "머큐리얼" 폴백 패턴 추가. 쿼리 문장에서 시리즈를 추출할 때는 `extract_series_name()`(상품명 파싱용, "10만원대"의 "10"을 모델 번호로 오인)이 아니라 번호 결합 로직이 없는 `_requested_series_name()`을 사용하도록 분리.
- [x] product_guide 라우팅 보강: "포지션별로는 어떤 스터드를 사용하는 게 좋아?" 같은 설명/사용 기준 질문이 Product Search 오케스트레이션 및 Tavily 검색으로 가지 않고 `product_guide`로 라우팅되도록 `_is_product_guide_request()` marker와 intent classifier 프롬프트에 `product_guide` 설명을 추가
- [x] Product Search 카드 null 필드 방어: 오케스트레이션 Product Search 결과의 `features`, `recommendation`, `price`, `url`이 `None`이면 빈 문자열 또는 검색 링크로 정규화해 프론트 카드 렌더링의 `split()` 오류를 방지
- [x] Product Search rule-based 필터 보정: 가격 조건을 `판매가`뿐 아니라 `소비자가`도 함께 비교하도록 수정하고, `rejection_summary`/`rejected_products`로 지면/가격/브랜드/시리즈 탈락 사유를 확인할 수 있게 추가
- [x] `Product_Search.ipynb` rule-based 파이프라인을 `Agent/product_search_agent.py`에 반영: 4개 판매처 Tavily LCEL 병렬 검색, score/URL 필터, 상품명/판매가 JSON 파싱, 브랜드/가격대/지면/시리즈 정규화, markdown 응답 생성 경로로 교체
- [x] Product Search Tavily 도구 진단 보강: Product Search include domain의 카포스토어 도메인을 `capostore.co.kr`로 수정하고, Tavily 원본 결과를 RAW/PRICE_DETECTED/PRICE_FILTERED 단계로 비교하는 `run_tavily_price_diagnostics()` 추가
- [x] Product Search 기본 실행 경로 복원: `product_search_agent()`가 지원 판매처 실제 상품/가격 검증 대신 LangGraph Tavily tool 기반 시리즈/모델군 추천을 반환하도록 수정하고, 가격 필터 없는 Tavily 원본 확인 함수 `run_unfiltered_tavily_product_search()` 추가
- [x] Product Search strict Tavily 필터 적용: Product Search에서 기존 판매처 크롤러를 호출하지 않고 Tavily `include_domains`를 4개 지원 판매처(crazy11, soccerboom, redsoccer, cafostore)로 고정. Tavily 결과 텍스트에서 가격 숫자가 확인되고 사용자 가격 범위(예: 10만원대=100,000~199,999원)에 들어오는 상품만 카드 표로 반환하며, 가격 없음/범위 밖/미지원 도메인 결과는 제외. 동일 상품명은 최저 검증 가격 1개만 유지.
- [x] Product Search 카드 파싱 안정화: `parse_product_markdown_table()`를 추가하고 메인 LangGraph `_parse_products()`가 LLM 파싱 전에 Product Search markdown 표를 deterministic하게 파싱하도록 연결해 가격/URL 누락을 방지.
- [x] 잡담 라우팅/카드 품질 수정: 저장된 `product_name`만으로 `ㅎㅇ` 같은 인사말이 seller_search로 승격되지 않도록 최신 메시지 쇼핑 신호 가드 추가, `last_products` 기반 "첫 번째 제품/저 제품" 참조 해석, Product Search 검색 링크 보강, Seller Search 추천 이유 markdown table + deterministic parser 추가, Product Analysis RAG 0건 조건 설명 메시지 추가
- [x] Multi_Agent_Orchestration.ipynb E2E 시나리오 3종 검증 (캐시 기반, 크롤 없음): A(PA 단독), B(SS→PA), C(PS→SS→PA) 모두 PASS
- [x] Multi_Agent_Orchestration.ipynb 핵심 버그 수정:
  - Plan.steps를 Literal 타입으로 제한 (LLM이 유효 에이전트명만 반환하도록 강제)
  - _clean_workflow_phrases() 추가: "판매처 비교하고 제일 싼 곳에서 상세 분석" 같은 워크플로우 지시어가 PA keyword에 섞이면 0 docs 문제 해결
  - extract_node: pre_conditions 우선 사용 (pa_exec에서 미리 정제한 값 통과)
  - pa_exec: selected_series에서 브랜드+모델계열 2토큰만 사용 (에디션/버전 제거 → ChromaDB name_matches 0 docs 방지)
  - pa_exec: human_review 노드에서만 outer interrupt 발동 (crawl_rag 오류 시 잘못된 interrupt 방지)
  - ps_review: 다중 regex 패턴 + 키워드 폴백으로 시리즈명 자동 추출 강화
- [x] Multi_Agent_Orchestration.ipynb 작성: LangGraph Supervisor 패턴으로 3개 에이전트 오케스트레이션 시연 (의도 기반 라우팅 + 에이전트 체이닝)
- [x] Prompt_Quality.ipynb 작성: 프롬프트 v1→v2→v3 버전 비교 + 할루시네이션 방지(출처 URL 검증) + 조건 준수율 정량 테스트
- [x] Product_Search.ipynb 작성: Exa MCP → LangGraph + Tavily 전환, LangGraph tool node 패턴 시연
- [x] Seller_Search.ipynb 작성: SELLER_DOMAINS 변수 분리 + Tavily include_domains 도메인 필터 시연
- [x] Product_Analysis.ipynb 작성: RAG 벡터스토어 선정(Part 1) + RAG 최적화(Part 2) + 크롤 캐시(Part 3) + E2E 파이프라인 프로파일링(Part 4)
- [x] product_analysis 후속 질문("다른 건 없어?") 동일 결과 반복 수정: similarity_search 가 결정론적이라 같은 조건이면 같은 상위 결과가 반복되던 문제. `BuyerAgentStateV2.shown_product_keys`(seller|name)에 이미 보여준 제품을 누적하고, `product_analysis_node`가 후속 "다른 거" 요청(`_is_more_request`)일 때 `product_analysis_agent(exclude_keys=...)`로 전달 → RAG 검색에서 제외 + 후보 풀 k 비례 확대. 신규 분석이면 제외셋 리셋, 후보 소진 시 "더 이상 없음" 안내. `follow_up_patterns`는 모듈 상수 `FOLLOW_UP_PATTERNS` + `_is_more_request` 헬퍼로 승격(라우팅 안전망과 공유)
- [x] (위 수정의 1차 버그) `is_more` 판정에 `active_agent`를 쓰면 안 됨: `FastAPI/main.py:_build_input_state`가 매 요청마다 `active_agent=None`(및 `intent=""`)을 입력 state 로 넣어 체크포인트 값을 덮어쓰므로, 노드 진입 시 active_agent 는 항상 None → 제외가 한 번도 실행되지 않음(같은 제품 반복). 입력에서 리셋되지 **않고** 유지되는 `shown_product_keys` 존재 여부로 후속 판정하도록 변경
- [x] 후속 질문 셀러 유실 수정: "다른 거"엔 셀러명이 없어 conditions.seller 만 보고 검색 → 첫 메시지 텍스트로만 지정된 셀러("크레이지11과 사커붐")가 후속 턴에 사라지던 문제. 명시적으로 지정된 셀러 전체를 `conditions.seller`에 보존(`_extract_sellers` + `find_seller_displays_in_query`)
  - [ ] (남은 한계) "머큐리얼 말고 팬텀 보여줘"처럼 후속 패턴 + 새 모델이 섞이면 잘못 제외될 수 있음 → 직전 product_keyword 변경 감지로 강제 리셋하는 가드 추가 검토
- [x] product_analysis 후속 질문("다른 건 없어?") 가격대/셀러 불일치 버그 수정: `product_analysis_agent`가 `search_query=original_query`(사용자 원문)만으로 RAG 검색 쿼리를 만들어 후속 질문 시 가격/상품명이 빠지던 문제 수정 — `conditions`(product_name·brand·budget·age_group·surface)를 병합한 `retrieval_base`를 만들어 `_crawl_and_search_seller`에 전달. `_extract_sellers`는 `seller` 조건의 멀티 셀러("크레이지11, 사커붐")를 구분자(,/과/와 등)로 분리해 각각 추가하도록 수정 → 전체 4곳 폴백 방지
- [x] product_analysis 이미지 미표시 버그 수정: `_parse_analysis` (LLM 텍스트 파싱, image 필드 없음) 대신 `build_analysis_cards` (ChromaDB 직접 조회, image_url 포함)를 사용하도록 변경. `AnalysisItem`에 `image` 필드 추가 (fallback 경로용)
- [x] seller_search 중복/설명/추천이유 개선: 동일 판매처 중복 카드 제거(추천 목록 섹션만 파싱 + Python seen-set dedup + regex 안전망), SellerItem에 why_recommended 필드 추가, 시스템 프롬프트 출력 포맷에 "추천 이유" 항목 추가 + 설명 3가지 이상 구체적 사실 요구, 프론트엔드 seller-cards에 amber 배경 추천 이유 블록 렌더링 + description null 가드
- [x] product_search 모델/시리즈별 추천 강화: 시스템 프롬프트에 ❌/✅ 예시 추가(개별 SKU 금지, 시리즈명만 허용), Tool Policy Override의 Exa 쿼리 지침을 "시리즈 추천/모델 비교" 형태로 강제, `_parse_products()` 파싱 지시를 시리즈·모델 단위 추출로 명확화
- [x] seller_search / product_search Exa query 의도 불일치 수정: seller_search 시 LLM이 제품명만(예: "나이키 머큐리얼 베이퍼 축구화") query로 전달하던 문제 수정 — 시스템 프롬프트 예시를 판매처 키워드 포함 형태로 교체하고 Tool Policy Override에 "판매처 의도 키워드 필수" 규칙 추가. product_search에도 동일하게 "추천/시리즈 키워드 필수" 규칙 추가.
- [x] seller_search_agent MCP 도구 통일: `web_search_exa` → `web_search_advanced_exa` 교체, `_mcp_seller_search_inner`에 `includeDomains` 래퍼 추가로 검색을 4개 판매처(crazy11·soccerboom·redsoccer·cafostore)로 고정, Tool Policy Override 섹션 및 프롬프트 업데이트
- [x] product_analysis_node 추가 질문 쿼리 재구성: cache_hit + previous_agent==product_analysis 조건 시 rag_search 쿼리를 "기존조건 + 사용자 실제 메시지"로 합쳐 재실행 ("이중에서 저렴한 제품이 뭐야?" → "크레이지11 머큐리얼 베이퍼 10만원대 이중에서 저렴한 제품이 뭐야?")
- [x] product_analysis_node AgentExecutor 제거: crawl_and_index → rag_search 직접 순차 호출로 변경 (ReAct 에이전트 LLM 라운드트립 2~3회 제거, ~10–15초 절감)
- [x] 전역 크롤 캐시 통합: `is_already_indexed()` 로 세션 로컬 캐시 + 전역 레지스트리 OR 조건으로 크롤 생략 판단, 다른 유저/새 세션에서도 재크롤 방지
- [x] _is_cache_hit에서 boot_ts 비교 제거: 전역 레지스트리가 동일 라이프사이클이므로 불필요
- [x] enable_inserts=True → False 수정 (버그 수정): 주석과 코드 불일치, save_user_memory 매 호출마다 중복 프로필 생성 가능성 제거
- [x] _parse_products/_parse_sellers/_parse_analysis 실패 시 None 반환으로 변경: 빈 배열과 파싱 오류 구분, 호출부 fallback 처리
- [x] product_analysis_node 크롤링 타임아웃 추가: asyncio.wait_for(timeout=60.0)로 최대 대기 60초 제한, TimeoutError 시 사용자 안내 메시지 반환
- [x] 크롤링 대기 피드백 추가: product_analysis_node 캐시 미스 시 adispatch_custom_event로 "판매처 상품 정보 수집 중..." / "수집 완료, 결과 분석 중..." 이벤트 발행
- [x] 세션 내 크롤 캐시 구현: product_analysis 후속 질문 시 재크롤링 방지 (_build_crawl_cache_key, _is_cache_hit, _SERVER_BOOT_TS 추가, product_analysis_node 수정)
- [x] chitchat_node에 user_profile 주입 (버그 수정): 메모리가 로드되어도 chitchat_node가 generic 프롬프트만 사용해서 유저 선호도를 모르던 문제 수정
- [x] enable_inserts=False → True 수정: 신규 유저 프로필이 한 번도 저장되지 않던 근본 원인 수정
- [x] UserProfile에 name 필드 추가: 이름 정보를 저장/로드할 수 없던 문제 수정
- [x] chitchat_node → save_user_memory 재연결: chitchat 중 언급된 이름/선호도 저장
- [x] "결과를 정리하는 중..." 메시지 제거: chitchat 후 불필요한 진행 메시지 표시 문제 수정
- [x] product_analysis_agent 시스템 프롬프트 강화: rag_search 호출 시 사용자가 명시하지 않은 조건(FG, 축구화 등) 추가 금지 규칙 추가, sys.modules alias 해킹 제거
# 이번 작업 완료
- [x] 후속 질문 3종 세트 버그 수정(판매처 쏠림 / 브랜드 조건 잔존 / 선택 대기 중 질문·재진술 무시):
  1. **판매처 쏠림**: `Agent/product_analysis_agent.py`의 판매처별 결과 병합이 `sellers` 순서대로 이어붙이는
     방식이라, 한 판매처(예: crazy11)가 하위 `build_analysis_cards_from_docs(limit=6)` 절단선을 넘는 문서를
     가지면 나머지 판매처는 카드에 아예 등장하지 못했다. `itertools.zip_longest`로 판매처별 결과를 라운드로빈
     인터리빙하도록 병합 루프 수정 — 호출자(executor.py, LangGraph 파일) 양쪽에 자동 적용.
  2. **브랜드 조건 잔존**: "저 중에서 가성비 있는 시리즈는 뭐야"처럼 `_is_fresh_product_search_request`가
     요구하는 키워드가 없는 후속 질문은 조건 리셋 대상이 아니라서, 세션 초반 브랜드 조건(예: "나이키")이 그대로
     남아 product_guide가 언급한 다른 브랜드들을 검색에서 배제했다. `Agent/orchestration/executor.py`의
     `_run_product_search`에 `_MULTI_CANDIDATE_REFERENCE_PATTERNS`("저 중에서"/"그 중에서"/"앞서 말한" 등) 매칭 시
     이번 쿼리에 한해 `brand` 조건을 제외하도록 추가(영구 상태는 그대로 유지).
  3. **선택 대기 중 질문/재진술 무시**: `pending_action`(카드 선택 대기) 상태에서는 `extract_conditions_and_intent`가
     완전히 우회되고 `resolver.py`의 순수 정규식/substring 매칭만으로 처리되어, "카포스토어에서는 안 팔아?" 같은
     질문이나 "나이키 머큐리얼 베이퍼 10만원대 말이야" 같은 부분 일치 재진술이 전부 매칭 실패 → "다시
     선택해주세요"만 반복하던 문제. 결정론적 매칭이 실패했을 때만 작은 LLM 구조화 출력 1회로 재판정하는 폴백을
     추가: `Agent/orchestration/types.py`의 `ResolutionAction`에 `question`/`condition_update` 추가,
     `resolver.py`에 `PendingFallbackClassification`/`resolve_pending_action_llm_fallback`(질문 대상 판매처는
     LLM이 추출하되 실제 답변은 pending 카드 데이터로 코드가 직접 생성해 할루시네이션 방지) 추가,
     `service.py`의 `_handle_pending_action`이 `invalid`일 때만 폴백을 호출하고 `question`(카드 유지 + 답변)/
     `condition_update`(조건 병합 후 `_retry_pending_step` 재사용) 분기를 새로 처리. 부수적으로
     `_extract_ordinal_index`의 `(\d+)\s*(?:번|번째)?` 정규식이 "10만원대"의 "10"을 서수로 오인할 수 있던
     잠재 버그를 "번/번째" 필수로 좁혀 `resolver.py`/`executor.py` 양쪽에서 수정.
  - **아키텍처 검토**: 사용자가 제안한 "전체를 create_react_agent + tool로 재설계"는 채택하지 않음 — 판매처
    쏠림은 아키텍처와 무관한 병합 버그, 브랜드 잔존은 결정론적 참조 해석으로 해결 가능, LLM 판단이 필요한 곳은
    pending_action resolver 지점 하나뿐이라 거기에만 폴백을 추가하는 것으로 충분하다고 판단.
- [x] "모두 비교" + "앞서(서) 말한 시리즈" 후속 질문 조건 오염 버그 수정: `executor.py`의 `_analysis_conditions`가 `wants_all_comparison()` 신호를 참조하지 않아, LLM 조건 추출 단계에서 새어든 단일 판매처 값(예: "사커붐")이 "4곳 모두 비교해줘" 요청에도 그대로 전달되어 `product_analysis_agent`의 "seller 없음 → 지원 판매처 4곳 전체" 폴백이 발동하지 못하던 문제 수정 — `message_sellers`도 없고 `wants_all_comparison()`이 True면 `conditions["seller"]`를 pop해 폴백이 동작하도록 분기 추가. `_PRODUCT_PRONOUN_PATTERNS`에 "앞서 말한/앞서서 말한/이전에 말한/아까 말한/말씀하신/언급한"을 추가해 `_resolve_product_reference`가 과거-턴 역참조 표현도 `last_products`/`selected_series_card`에서 정확한 상품명으로 해석하도록 수정(기존 배선은 그대로, 패턴 리스트만 확장). 보조 조치로 `extract_conditions_and_intent` 시스템 프롬프트에 "product_name/seller는 최신 발화에서 1개만 추출, 과거 응답의 여러 후보를 한 필드에 섞지 말 것"이라는 문구를 보강(결정론적 테스트 불가, 저비용 보험성 조치)
- [x] Product_Search.ipynb 및 Multi_Agent_Orchestration.ipynb Cell 6 기반 Product Search를 `Agent/product_search_agent.py`로 모듈화
- [x] Seller_Search.ipynb 및 Multi_Agent_Orchestration.ipynb Cell 8 기반 Seller Search를 `Agent/seller_search_agent.py`로 모듈화
- [x] 최신 메인 그래프와 오케스트레이션 executor가 `sub_agent_0310.py` 대신 새 PS/SS 모듈을 호출하도록 변경
- [x] Multi-Agent Orchestration 서비스 모듈화: `Agent/orchestration/` 패키지 추가(planner, resolver, executor, service) 및 PS/SS/PA 자연어 HITL 선택/재요청 흐름 구현
- [x] "판매자 4곳 모두에서 비교해줘" 오라우팅 버그 수정: `planner.py`의 `_SELLER_PATTERNS`("판매")가 "판매자"에도 매칭되어 이미 알려진 판매처가 있는 상태에서도 불필요한 `seller_search` 스텝이 다시 추가되던 문제 수정. `wants_all_comparison()` + `has_known_sellers` 플래그로 "모두/전부/전체" 비교 요청이면 `seller_search`를 건너뛰고 `product_analysis`(기본적으로 지원 판매처 4곳 전체 비교) 단일 스텝만 실행하도록 변경
- [x] "모두 비교" 요청 시 강제 단일 선택 카드(판매처 선택/상품 선택) 제거: `executor.py`의 `_run_product_analysis`가 `wants_all_comparison()`이면 분석 결과가 여러 개여도 `pa_review` pending_action(상품 선택 카드)을 띄우지 않고 바로 비교 결과를 반환하도록 수정
- [x] 선택 카드 복수 선택 지원 추가: `resolver.py`에 `_select_cards_multi`/`_select_sellers_multi` 추가, "1번이랑 3번", "크레이지11이랑 카포스토어 둘 다" 같은 응답을 판매처 다중 선택으로 해석해 `ReviewResolution.selected_list`로 반환. `service.py`의 `_continue_after_selection`이 ss_review 다중 선택 시 선택된 판매처들을 `user_conditions.seller`에 합쳐서 다음 단계(product_analysis)로 전달
- [x] "모두 비교" 요청 시에도 "판매처 선택" 카드가 계속 뜨던 버그 수정: 69번 항목에서 `_run_product_analysis`(`pa_review`)에만 `wants_all_comparison()` 가드를 추가했고 `_run_seller_search`(`ss_review`)는 빠뜨렸던 것 — `executor.py`의 `_run_seller_search` pending_action 게이트에도 동일 가드 적용
- [x] intent/plan 아키텍처 재설계: `extract_conditions_and_intent`가 `ExtractionResult.intent`(단일 Literal) 대신 `intent: shopping/product_guide/chitchat` + `requested_capabilities: list[product_search/seller_search/product_analysis]`(멀티라벨) 구조화 출력을 사용하도록 변경. 대화 히스토리(최근 6개 메시지)를 LLM에 함께 전달하고, 시스템 프롬프트를 트리거 단어 나열 대신 few-shot 5개로 교체. `orchestration/planner.py`의 `plan_orchestration_steps()`가 원문을 정규식으로 재스캔하던 로직(`_SELLER_PATTERNS` 등 키워드 상수 전부)을 삭제하고, LLM이 넘긴 `requested_capabilities`를 고정 순서(product_search→seller_search→product_analysis)로 필터/정렬만 하는 순수 함수로 축소. `has_shopping_signal`/`_is_product_guide_request`(사후 override 로직)와 follow-up 안전망 블록 삭제. `check_conditions`/`ask_missing_node`의 `plan[0] if plan else state.get("intent")` 우회 로직을 `state.get("intent")` 직접 참조로 단순화. `_SELLER_PATTERNS`에 "구매"가 들어있어 상품 추천 요청("~구매하려고 하는데 뭐가 좋을까")이 seller_search로 오분류되던 버그는 이 재설계로 자동 해소(별도 패치 없음). 구매 의도 정규식 선차단(`_looks_like_purchase_intent`)은 LLM 호출 비용/오탐 리스크 절감을 위해 메인 LLM 호출 앞으로 이동. `Test/eval_intent_extraction.py` + `Test/fixtures/intent_extraction_cases.py`로 실제 LLM 정확도 측정용 opt-in 스크립트 추가(pytest 미포함)

# Agentic orchestration 리팩터링 (Supervisor + create_react_agent + native interrupt())
사용자가 기존 orchestration이 고정 순서(planner.py)와 정규식 우선 응답 해석(resolver.py)이라 "자유롭게
질문/응답을 못 한다"고 지적, teddylee777/langchain-kr CH19(Plan-and-Execute/Multi-Agent-Supervisor/
Human-In-the-Loop/CRAG/Self-RAG) 레퍼런스를 참고해 재설계.
- [x] **Stage 0 (CRAG+Self-RAG)**: `Tools/rag_search.py`에 `grade_docs_relevance`(생성 전 문서 관련성 채점,
  CRAG)/`rewrite_analysis_query`(재검색용 질의 재작성)/`grade_answer_groundedness`(생성 후 답변의 문서 근거
  검증, Self-RAG) 추가. `Agent/product_analysis_agent.py`에 라운드로빈 병합 → relevance grading → (전부
  무관하면 재작성 후 1회만 재검색) → 답변 생성 → groundedness 검증(hallucination이면 1회만 강화 재생성) 순서로
  삽입. `_merge_docs_round_robin` 헬퍼로 병합 로직 추출·재사용. `Test/test_product_analysis_optimization.py`에
  두 채점 함수 pass-through patch 추가 + irrelevant→retry→no-result/hallucination→regenerate 신규 테스트.
- [x] **Stage 1 (create_react_agent 전환)**: `product_search_agent.py`는 `run_product_search_pipeline`을
  `@tool search_products`로 감싸 `create_react_agent`로 호출하도록 변경(크롤링/파싱은 그대로 결정적).
  `seller_search_agent.py`는 손수 만든 `StateGraph`+`bind_tools`+`ToolNode`+`route_after_cache`(~110줄)를
  전부 삭제하고 캐시→Tavily 폴백을 `search_sellers` tool 하나로 접어 `create_react_agent` 한 줄로 대체.
  `product_analysis_agent`는 카드 생성이 RAG `docs`에 의존하고 과거 AgentExecutor 제거 이력이 있어 의도적으로
  감싸지 않음. 두 sub-agent 외부 시그니처(`agent(query, user_profile=None) -> str`)는 불변이라 호출부 무수정.
- [x] **Stage 2 (Supervisor)**: 신규 `Agent/orchestration/supervisor.py`(`SupervisorDecision` 구조화 출력,
  `supervisor_node`가 매 턴 past_steps/조건을 보고 재판단, `Command(goto=...)`로 직접 라우팅).
  `planner.py`의 고정 `_STEP_ORDER`/`plan_orchestration_steps` 삭제(`wants_all_comparison`만 이식).
  `LangGraph_buyeragent_with_personalization.py`에서 이미 사실상 죽어있던(orchestration_plan이 항상
  채워져 도달 불가) `product_search_node`/`seller_search_node`/`product_analysis_node`/`orchestration_node`/
  `route_after_orchestration` 삭제, `_parse_products`/`_parse_sellers`/`ParsedProducts`/`ParsedSellers`
  등을 `workers.py`로 이전(유일한 호출부였던 구 노드들이 삭제됐으므로). `check_conditions`/`ask_missing_node`
  조건 수집 게이트는 그대로 유지. `extract_conditions_and_intent`는 `_CAPABILITY_PRIORITY` 우선순위로 게이트용
  `intent` 하나만 정하고, 실제 실행 순서는 Supervisor가 매 턴 재판단.
- [x] **Stage 3 (native interrupt())**: `orchestration/resolver.py`의 정규식 우선 게이트(`_RESET_PATTERNS`
  등)를 완전히 삭제 — 이게 "자유 응답 불가" 문제의 근본 수정. `workers.py`의 각 워커가 카드 리뷰 필요 시
  LangGraph `interrupt()`로 멈추고, 재개된 사용자 메시지는 `_resolve_resume`(LLM 구조화 분류기가 유일한 해석
  경로, 순수 서수 입력만 LLM 호출 전에 즉시 처리)로 해석. `reset`은 "취소하고 조용히 종료" 대신 "리뷰 필드만
  지우고 메시지를 그대로 들고 supervisor_node로 복귀"로 재정의해 "취소" 요청과 "리뷰 도중 다른 요청"을 같은
  경로로 자연스럽게 처리(별도 분류 카테고리 불필요). `orchestration/service.py` 삭제(로직이 각 워커로 흡수).
  `State/AgentState_personalization.py`에서 `pending_action`/`orchestration_plan` 필드 삭제. `FastAPI/main.py`
  는 매 요청 시작 시 `graph.aget_state(config)`로 중단 여부 확인 → 중단 중이면 `Command(resume=message)`,
  아니면 기존 입력 state. `_build_chat_response`에 `result["__interrupt__"]` 분기 추가(카드/메시지를 인터럽트
  payload에서 가져옴 — 그 턴 워커의 반환 dict는 아직 커밋 전이라 `result["products"]` 등은 이전 턴 값).
  `/chat/stream`은 `astream_events` 최종 출력에 `__interrupt__`가 실리지 않는 것을 실측 확인해, 스트림 종료
  후 `graph.aget_state(config)`로 폴백 확인하는 로직 추가.
- [x] 테스트 정리: `test_orchestration_planner.py`/`test_orchestration_resolver.py`/`test_orchestration_service.py`
  /`test_orchestration_executor.py` 삭제 → `test_orchestration_supervisor.py`(wants_all_comparison만 이동)/
  `test_orchestration_workers.py`(interrupt+Command(resume=...) 왕복을 실제 미니 LangGraph로 검증) 신규 작성.
  `test_product_search_followup_routing.py`/`test_fastapi_progress_events.py`/`test_fastapi_orchestration_response.py`
  를 새 필드/노드명/interrupt 응답 형태에 맞게 갱신, `test_product_analysis_optimization.py`의 삭제된
  `product_analysis_node` 참조 테스트를 `test_orchestration_workers.py`(실제 `build_analysis_cards_from_docs`
  사용)로 이동, `Test/eval_intent_extraction.py`의 `orchestration_plan` 참조를 `requested_capabilities`로 수정.
- [x] Product Search 독립 안정화: 가격 조건이 없어도 판매가(우선) 또는 소비자가가 검증된 후보만
  통과시키고, 지원 판매처 URL·null/불완전 item을 결정적으로 거부하도록 필터 보강. raw cache hit는
  Tavily를 호출하지 않고 miss일 때만 폴백하며, 결과에 `source`(`raw_cache`/`web_search`),
  `search_status`(`ok`/`no_results`/`error`), `failed_sellers`를 기록해 정상 0건과 외부 검색 전체 실패를
  구분. 실패 시 검증되지 않은 상품을 생성하지 않는 전용 안내를 반환하고, 구체적인 제외 시리즈가
  일반 상위 시리즈까지 과잉 제외하지 않도록 수정.
- [x] Seller Search 독립 안정화: 검증된 시리즈 입력만 허용하고 raw cache hit 시 웹 검색을 생략하며,
  지원 판매처의 상품 URL·판매 상태·판매가(없으면 정상가)를 모두 검증한 후보만 반환하도록 정규화.
  판매처별 웹 검색을 독립 실행해 `ok`/`no_results`/`error`/`partial_failure`를 구분하고 일부 실패 시
  성공 후보와 `failed_sellers`를 함께 유지. 사용자 제외 판매처는 검색 branch와 최종 후보에서 모두 제외.
- [x] product_analysis_agent: Stage 0의 LLM 채점(CRAG/Self-RAG)을 `filter_non_shoe_docs`/`answer_cites_only_docs`
  결정적 검사로 교체(흐름·1회 재시도 구조는 유지). 근거와 수치는 `backend/prompts/analysis_answer.yaml` changelog와
  Tools/TODO.md 참조.
- [x] 조건 추출 규칙 누락 2건 수정(실험 4 라우팅 평가 60문항 x 3회에서 발견): `BOOT_SURFACE_KEYWORDS`에 HG가 없어 새 검색
  요청에서 LLM이 잡은 surface까지 지워져 되묻던 문제, 시리즈 별칭에 '퓨처' 표기가 없어 상품명이 지워져 분석 요청을
  되묻던 문제. 현재 버전 정답률 91.7% → 96.7%(분명한 질문 78.6% → 92.9%).
- [ ] '미즈노 20만원 이하 HG 축구화 보여줘'에 요청하지 않은 seller_search가 붙는 LLM 추출 오류(3/3 재현).
- [x] supervisor: 상품 맥락(selected_series/last_products/products)이 없는데 product_search가 남아 있으면 항상 먼저 실행.
  LLM(gpt-5.4-nano)이 remaining_order에 판매처/분석을 먼저 두는 경우가 실측됨(다중 기능 정답 30회 중 8회) → 수정 후 30/30.
- [x] `_extract_ground_type`가 "TF용"처럼 한글이 붙은 지면을 못 잡던 버그 수정(`\b`가 한글을 단어 문자로 봄 → 영숫자 경계만 사용).
  처음 보는 질문 30개 x 2회 확인에서 발견: 생성에 쓴 문서의 21.1%가 지면 조건 불만족 → 수정 후 0/292.
- [ ] 라우팅: 요청하지 않은 seller_search를 붙이는 LLM 추출 오류(처음 보는 질문에서도 재현, 상품 탐색 단독 요청).
