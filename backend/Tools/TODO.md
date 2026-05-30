# TODO - Tools

## 진행 중
- [ ] 

## 버그
- [ ] 

## 예정
- [ ] 

## 완료
- [x] vectorstore 인스턴스 분리 버그 수정: `vectorstore_singleton.py` 신규 생성, `rag_search.py`·`crawl_and_index.py` 모두 singleton에서 import하도록 변경 (import 경로 차이로 인한 별도 Chroma 인스턴스 생성 문제 해결)
- [x] 전역 크롤 레지스트리 추가 (`_CRAWL_INDEX_REGISTRY`): 세션·유저 무관하게 동일 (판매자+키워드+가격) 조합 재크롤 방지, 서버 재시작 시 vectorstore와 동일 라이프사이클로 자동 초기화
- [x] 크롤 병렬성 증가: `crawl_multiple_sellers` 호출 시 `seller_parallelism=len(seller_list)` 전달 → 판매자 수만큼 동시 크롤 (기존 Semaphore(2) 제한 해제)
