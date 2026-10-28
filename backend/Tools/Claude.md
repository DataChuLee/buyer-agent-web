# Tools 폴더

## 역할
에이전트가 호출하는 도구 함수 모음. LangGraph 노드에서 직접 import해서 사용.

## 주요 파일
- `tool.py` → 메인 도구 모듈 (22KB, 가장 큰 파일). 에이전트 tool 함수들 정의
- `rag_search.py` → ChromaDB 기반 RAG 검색. `Agent/product_analysis_agent.py`용 CRAG/Self-RAG 채점 함수도
  포함: `grade_docs_relevance`(생성 전 검색 문서가 질문과 실제로 관련 있는지 채점), `rewrite_analysis_query`
  (관련 문서가 없을 때 재검색용 질의 재작성), `grade_answer_groundedness`(생성 후 답변의 가격/스펙 주장이
  문서에 실제로 있는지 채점, hallucination 감지)
- `crawl_and_index.py` → 크롤링 결과 → ChromaDB 인덱싱 파이프라인
- `seller_normalization.py` → 판매자 데이터 정규화
- `seller_selection.py` → 판매처 후보 검증과 최저가 선택. 지원 도메인·상품 일치·판매 상태·URL·가격·
  사용자 제외를 검사하며 판매가를 정상가보다 우선한다. 동률 정렬은 가격 → 판매처명 → URL이고,
  유효 후보가 없으면 `status=no_results`, `selected=None`이다. legacy markdown 입력도 같은 검증을 거친다.
- `condition_sanitization.py` → 사용자 입력 조건 검증/정제

## 의존성
- ChromaDB: 벡터 DB (RAG)
- `Crawling/crawling.py`: 크롤링 실행
- `Userprofile/userprofile.py`: 유저 프로필 조회
