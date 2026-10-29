# Tools 폴더

## 역할
에이전트가 호출하는 도구 함수 모음. LangGraph 노드에서 직접 import해서 사용.

## 주요 파일
- `rag_search.py` → ChromaDB 기반 RAG 검색. `Agent/product_analysis_agent.py`용 결정적 검사도 포함:
  `filter_non_shoe_docs`(생성 전 장갑·축구공 등 비축구화 제외), `answer_cites_only_docs`(생성 후 답변의
  가격·URL이 문서에 있는지 코드로 검사), `rewrite_analysis_query`(문서가 하나도 안 남았을 때 재검색 질의 재작성).
  예전 LLM 채점(CRAG/Self-RAG)은 ablation에서 효과가 없어 대체됨. 답변 생성 프롬프트는
  `backend/prompts/analysis_answer.yaml`(버전·changelog)에서 읽고, 버전을 trace 메타데이터로 남긴다.
- `crawl_and_index.py` → 크롤링 결과 → ChromaDB 인덱싱 파이프라인
- `seller_normalization.py` → 판매자 데이터 정규화
- `seller_selection.py` → 판매처 후보 검증과 최저가 선택. 지원 도메인·상품 일치·판매 상태·URL·가격·
  사용자 제외를 검사하며 판매가를 정상가보다 우선한다. 동률 정렬은 가격 → 판매처명 → URL이고,
  유효 후보가 없으면 `status=no_results`, `selected=None`이다.
- `condition_sanitization.py` → 사용자 입력 조건 검증/정제

## 의존성
- ChromaDB: 벡터 DB (RAG)
- `Crawling/seller_total_test.py`: 판매처별 크롤러 통합 실행(`crawl_multiple_sellers`)
