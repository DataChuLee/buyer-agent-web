# TODO - FastAPI

## 진행 중
- [ ] 

## 버그
- [ ] 

## 예정
- [ ] 

## 완료
- [x] 크롤링 진행 SSE 이벤트 처리 추가: on_custom_event / crawl_progress → progress 타입으로 프론트 전달
- [x] _build_input_state에 crawled_context: None 추가
- [x] user_profile: None 매 턴 리셋 버그 수정: _build_input_state에서 user_profile 필드 제거 → checkpointer가 이전 턴 값 유지
