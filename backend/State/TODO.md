# TODO - State

## 진행 중
- [ ] 

## 버그
- [ ] 

## 예정
- [ ] 

## 완료
- [x] BuyerAgentStateV2에 `last_products`, `last_sellers`, `last_analysis` 내부 상태 필드 추가: 최신 응답에는 노출하지 않지만 "첫 번째 제품", "저 제품" 후속 참조를 실제 카드명으로 해석하기 위한 체크포인트 보존용
- [x] BuyerAgentStateV2에 crawled_context 필드 추가: 세션 내 크롤 캐시 키 저장용
# 이번 작업 완료
- [x] BuyerAgentStateV2에 멀티에이전트 오케스트레이션 상태 필드 추가: plan, past_steps, pending_action, selected/rejected 항목, request_id
