# State 폴더

## 역할
LangGraph 에이전트의 상태(State) 스키마 정의.

## 주요 파일
- `AgentState_personalization.py` → **현재 사용** (개인화 포함 최신 버전)
- `AgentState.py` → 기본 버전 (구버전)

## AgentState 주요 필드
- 사용자 메시지 / 대화 히스토리
- 추출된 조건 (상품 조건, 판매자 조건 등)
- 질문 시퀀스 (조건 수집용)
- 검색 결과 (상품, 판매자, 분석)
- 유저 프로필 / 메모리

## 주의
- 새 필드 추가 시 FastAPI Response Schema와 함께 수정 필요
- `AgentState.py`는 레거시, 수정 X
# Orchestration 상태 필드
- `BuyerAgentStateV2`는 멀티에이전트 진행 상태를 위해 `requested_capabilities`, `past_steps`, `selected_series`, `selected_seller`, rejected 항목들, `request_id`를 포함한다.
- `requested_capabilities`는 `extract_conditions_and_intent`가 LLM 구조화 출력에서 받은 원본 멀티라벨 결과(`product_search`/`seller_search`/`product_analysis` 부분집합)를 그대로 보관하는 디버깅/관측용 내부 필드다. 응답 스키마로는 노출하지 않는다.
- **`orchestration_plan`/`pending_action` 필드는 삭제되었다.** 실행 순서는 더 이상 턴 시작 시 고정 계산하지 않고 `Agent/orchestration/supervisor.py`의 `supervisor_node`가 매 턴 재판단하며(`past_steps`만 참고), HITL 대기 상태는 커스텀 state 필드 대신 LangGraph 네이티브 `interrupt()`(체크포인터가 관리)로 표현한다. `Agent/orchestration/types.py`의 `PendingAction` TypedDict는 그대로 `interrupt()` payload/`ChatResponse.pending_action` 모양으로 재사용된다.
- `last_products`, `last_sellers`, `last_analysis`는 응답 스키마로 노출하지 않는 내부 체크포인트 필드다. 직전 카드 결과를 보존해 "첫 번째 제품", "저 제품" 같은 후속 참조를 실제 상품/판매처/분석 카드명으로 해석하는 데 사용한다.
