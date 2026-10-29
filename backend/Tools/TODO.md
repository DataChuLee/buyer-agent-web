# TODO - Tools

## 진행 중
- [ ] 

## 버그
- [ ] 레드사커 `머큐리얼 베이퍼 15 TF` exact raw item이 현재 캐시에 없어 Seller Search 캐시 기준 결과에는 레드사커가 포함되지 않음

## 예정
- [ ] 

## 완료
- [x] `build_analysis_cards_from_docs`의 `limit`을 전역 카드 개수 제한 → 판매처당 최대 개수로 변경,
  결과를 판매처별로 묶어서 반환하도록 수정 (Product Analysis 카드가 판매처별로 안 묶여 뒤섞여
  보이던 문제, 호출부는 `Agent/orchestration/workers.py` 참고).
- [x] `/code-review high` findings 정리 (`Tools/` 관련분):
  1. `rag_search.py`에서 아무도 안 부르는 죽은 코드 삭제 — 자기 자신을 덮어쓰던 중복 정의 4쌍
     (`extract_sellers_from_query`/`parallel_retrieve`/`retrieve_analysis_documents`/`retrieve_node`),
     미사용 `SelfQueryRetriever`/`StateGraph`(`classify_intent`~`run_rag_search`/`@tool rag_search`)
     전체 제거. 735줄 → 약 275줄. 실제 사용되는 7개 함수(`_generate_answer`, `format_docs`,
     `grade_docs_relevance`, `grade_answer_groundedness`, `retrieve_analysis_documents_filtered`,
     `rewrite_analysis_query`, `build_analysis_cards_from_docs`)만 남김.
  2. `grade_docs_relevance`/`rewrite_analysis_query`/`grade_answer_groundedness`/`_generate_answer`를
     동기 `.invoke()`에서 비동기 `.ainvoke()`로 전환(`async def`) — 기존엔 `product_analysis_agent`
     (async) 안에서 이 4개를 동기로 호출해 매 product_analysis 턴마다 최대 4번 이벤트 루프를
     블로킹, 다른 사용자 요청까지 멈추게 했음. 호출부(`Agent/product_analysis_agent.py`)에 `await`
     추가, `Test/test_product_analysis_optimization.py`의 관련 mock을 `AsyncMock`으로 교체.
  3. `crawl_and_index.py`의 `is_already_indexed`/`register_crawl`(동기 파일 I/O)을
     `asyncio.to_thread`로 감싸 — `product_analysis_agent`가 판매처별로 `asyncio.gather`하는 동안
     이 동기 I/O가 이벤트 루프를 막아 병렬 크롤을 부분적으로 직렬화하던 문제 수정.
  - 검증: 전체 테스트 스위트(무관한 pre-existing 실패 4건 제외) 통과.
- [x] `crawl_and_index.py`의 `_RAW_CACHE_STOPWORDS`에 `"추천"` 추가: seller-search 쿼리에 붙는
  "판매처 추천" 같은 안내성 접미사 단어가 `_raw_item_matches_keyword`의 필수 매칭 토큰으로 남아
  캐시 상품이 전부 탈락(→ `load_raw_items_cache`가 `None` 반환 → Tavily 폴백)하던 문제 수정.
- [x] `rag_search.py`에 CRAG/Self-RAG 채점 함수 추가: `grade_docs_relevance`(생성 전 문서 관련성 채점),
  `rewrite_analysis_query`(전부 무관할 때 재검색용 질의 재작성), `grade_answer_groundedness`(생성 후 답변의
  가격/스펙 hallucination 채점). 이미 있었지만 미사용이던 `rewrite_query` 노드의 재작성 로직만 재사용하고,
  그 노드가 속한 미사용 `StateGraph`(`classify_intent`/`respond_directly`/`ask_clarification` 등)는 그대로 둠.
  `Agent/product_analysis_agent.py`에서 각 1회 재시도로 소비.
- [x] `seller_selection.py` 추가: Seller Search markdown 표에서 `✅ 판매 중` 행의 최저가를 파싱해 auto_select가 가장 싼 판매처를 고르도록 지원
- [x] `seller_selection.py` 검증/선택 강화: 지원 도메인, 상품 일치, 판매 중, URL, 가격, 사용자 제외를
  순서대로 검증하고 판매가 우선·정상가 fallback으로 최저가를 선택. 동률은 `(가격, 판매처명, URL)`
  안정 정렬하며 유효 후보가 없으면 임의 기본 판매처 대신 `no_results`/`None` 반환.
- [x] `load_raw_items_cache` 가격 범위 매칭 수정: 요청 범위가 캐시 범위 안에 완전히 포함되어야만 hit 되던 조건을 겹침 기준으로 완화하고, 여러 raw cache entry를 병합하도록 변경
- [x] `load_raw_items_cache` 상품명 토큰 필터/중복 제거 추가: 넓은 키워드 캐시에서 다른 모델이 섞이지 않도록 item product_name을 요청 토큰으로 재필터링하고, 동일 판매처+상품명 중복을 제거
- [x] crawl_registry.py 퍼지 매칭 확인: entry_keyword ⊆ request_keyword (entry가 request의 부분집합) AND 가격 범위 포함 조건으로 캐시 HIT → "머큐리얼"로 "나이키 머큐리얼" 쿼리 HIT 확인
- [x] rag_search.py name_matches 토큰 필터 확인: _keyword_tokens가 ALL 토큰을 상품명에 요구 → 에디션 토큰("슈퍼플라이10") 제거 후 2토큰만 사용해야 0 docs 방지 (Multi_Agent_Orchestration.ipynb pa_exec에 적용)
- [x] `_document_id` 기준 변경: `product_url` 해시 → `seller + product_name` 해시 (URL 불안정 문제 해결)
- [x] `_add_new_documents` upsert 방식 적용: 기존 문서 스킵 → 삭제 후 재삽입 (가격·재고 24h 갱신 보장)
- [x] `warmup_keywords.yaml` 개선: 브랜드+시리즈명 → 시리즈명만으로 단축 (판매처별 표기 차이 대응), 가격대 경계값 중복 제거 ([0,100000]+[100000,200000] → [0,99999]+[100000,199999])
- [x] `retrieve_analysis_documents_filtered`에 `exclude_keys: set[str]` 추가: 후속 "다른 거" 질문 시 이미 보여준 제품(seller|name 복합 키)을 후처리에서 제외. 제외분만큼 후보 풀 k 를 비례 확대(`max((limit+len(exclude_keys))*5, 20)`)해 새 후보 확보
- [x] vectorstore 인스턴스 분리 버그 수정: `vectorstore_singleton.py` 신규 생성, `rag_search.py`·`crawl_and_index.py` 모두 singleton에서 import하도록 변경 (import 경로 차이로 인한 별도 Chroma 인스턴스 생성 문제 해결)
- [x] 전역 크롤 레지스트리 추가 (`_CRAWL_INDEX_REGISTRY`): 세션·유저 무관하게 동일 (판매자+키워드+가격) 조합 재크롤 방지, 서버 재시작 시 vectorstore와 동일 라이프사이클로 자동 초기화
- [x] 크롤 병렬성 증가: `crawl_multiple_sellers` 호출 시 `seller_parallelism=len(seller_list)` 전달 → 판매자 수만큼 동시 크롤 (기존 Semaphore(2) 제한 해제)
- [x] 디스크 캐시 timestamp 내구성 보강: raw item/crawl registry/web search cache가 timezone 없는 ISO
  timestamp 또는 손상된 entry를 만나도 전체 조회를 중단하지 않고 UTC로 정규화하거나 해당 entry만
  건너뛰도록 수정. L1/L2 hit, TTL 만료, fuzzy registry hit 회귀 테스트 추가.
- [x] LLM 채점(CRAG `grade_docs_relevance`, Self-RAG `grade_answer_groundedness`)을 결정적 검사로 대체:
  `filter_non_shoe_docs`(장갑·글러브·축구공 상품명 제외), `answer_cites_only_docs`(답변 가격·URL이 문서에 있는지).
  같은 질문 30개 x 2회 ablation에서 LLM 채점은 근거 없는 주장 수를 줄이지 못했고(부호검정 p=1.0) 정상 문서 91건을
  과잉 제거해 정답 있는 질문을 '결과 없음'으로 만들었음. 실행당 LLM 호출 3회 → 1회.
- [x] 답변 생성 프롬프트를 `backend/prompts/analysis_answer.yaml`로 분리(version/changelog). v2에서 원인이던
  '주요 특징: 기능 키워드 2개↑' 규칙을 '문서에 있는 지면/연령대만'으로 교체. trace 메타데이터에 prompt_version 기록.
- [x] 비축구화 제외를 검색 단계(`retrieve_analysis_documents_filtered`)로 당겨 limit 자리를 차지하지 않게 하고, 키워드를
  DB 전수(1902건) 확인으로 확장(장갑·축구공·신가드·유니폼·가방 등 334건, 이 중 상품명에 축구화·풋살화가 들어간 문서 0건). 사은품 표기 '전용쌕/주걱/양말'은 제외 키워드에서 뺌.
- [ ] DB 데이터 품질: 비축구화가 product_category=축구화로 들어옴(크롤 단계 분류가 근본 해결, 키워드 목록 밖 상품은
  여전히 통과 — 예: 'WE 베이스 티'), 상품명 '쥬니어'인데 age_group=성인용인 문서 존재.
- [x] 생성 모델이 '10만원대/20만원대'를 잘못 해석해 필터를 통과한 문서를 버리고 '찾을 수 없습니다'로 답하던 문제:
  `product_analysis_agent`가 파싱한 가격 범위를 숫자로 함께 전달 + 문서가 있는데 거절하면 1회 재생성.
  (원인 확인과 수정안은 평가셋 Q11·Q20으로 찾았으므로 평가셋 과적합 가능성 있음)
- [x] 비축구화 제외를 Chroma 후보 단계(`where_document` `$not_contains`)로 이동: 결과에서만 거르면 신가드·축구공이 유사도
  상위 20개 후보를 독차지해 축구화가 0건이 됐음(사커붐 머큐리얼). 판매처 5 x 시리즈 9 = 45개 조합에서 원래 서비스는
  15개 조합에 비축구화가 섞였고, 수정 후 0개(결과 0개 조합 8개는 모두 DB에 해당 축구화가 없는 경우).
- [x] 실패 캐시(negative cache): 접속 예외/타임아웃이 난 판매처는 10분간 재크롤을 건너뛰고 기존 인덱스로 검색
  (`crawl_registry.mark_seller_failed`/`recently_failed`). 장애 주입 측정(실험 3 실제 타임아웃 중앙값 23.1초 주입,
  판매처 2곳 x 연속 6요청)에서 장애 중 이후 요청 응답 p50 28.6초 → 5.5초.
- [x] 일부 판매처만 실패한 크롤에서 실패 판매처까지 성공 캐시(24h)에 등록되던 버그 수정 — 실제 성공한 판매처만 등록.
- [ ] 실패 캐시는 프로세스 메모리 기준이라 워커가 여러 개면 워커마다 1회씩 타임아웃을 겪음(필요 시 레지스트리 파일로 이동).
