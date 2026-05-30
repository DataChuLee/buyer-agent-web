# Tools 폴더

## 역할
에이전트가 호출하는 도구 함수 모음. LangGraph 노드에서 직접 import해서 사용.

## 주요 파일
- `tool.py` → 메인 도구 모듈 (22KB, 가장 큰 파일). 에이전트 tool 함수들 정의
- `rag_search.py` → ChromaDB 기반 RAG 검색 (17KB)
- `crawl_and_index.py` → 크롤링 결과 → ChromaDB 인덱싱 파이프라인
- `seller_normalization.py` → 판매자 데이터 정규화
- `condition_sanitization.py` → 사용자 입력 조건 검증/정제

## 의존성
- ChromaDB: 벡터 DB (RAG)
- `Crawling/crawling.py`: 크롤링 실행
- `Userprofile/userprofile.py`: 유저 프로필 조회
