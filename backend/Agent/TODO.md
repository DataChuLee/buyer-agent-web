# TODO - Agent

## 진행 중
- [ ]

## 버그
- [ ]

## 예정
- [ ]

## 완료
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
