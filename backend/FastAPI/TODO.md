# TODO - FastAPI

## 진행 중
- [ ] 

## 버그
- [ ] 

## 예정
- [ ] 

## 완료
- [x] LangSmith 트레이싱 활성화: `langchain_teddynote.logging.langsmith("buyer-agent_0706")`을
  `lifespan`(서버 기동 시, `build_graph()`/Agent 모듈 import보다 먼저) 안에 추가. 모듈 최상단에
  `from langchain_teddynote import logging as langsmith_logging`로 별칭 임포트(표준 `logging` 모듈과
  이름 충돌 방지). 모듈 최상단이 아니라 `lifespan` 안에 둔 이유: 여러 테스트 파일이 `FastAPI.main`을
  임포트하기 전에 `os.environ.setdefault("LANGSMITH_TRACING", "false")`로 트레이싱을 미리 꺼두는데,
  `langsmith()`가 `.env`의 실제 `LANGCHAIN_API_KEY`를 보고 `LANGSMITH_TRACING`을 무조건 `"true"`로
  덮어쓰므로 최상단에 두면 테스트 실행 중에도 실제 LangSmith로 트레이스가 나갈 위험이 있었음 —
  `lifespan`은 앱이 실제로 기동될 때만 실행되고 단순 임포트로는 트리거되지 않아 안전.
- [x] `/chat`, `/chat/stream` 예외 핸들러에 `logger.exception()` 추가 — 이전엔 예외를 `str(exc)`로만
  프론트에 보내고 서버 콘솔엔 트레이스백을 전혀 남기지 않아 실사용 중 발생한 "cannot unpack
  non-iterable NoneType object" 에러의 발생 지점을 알 수 없었음. 이 로깅으로 확보한 트레이스백으로
  근본 원인을 찾아 `Agent/orchestration/workers.py`에서 수정함(자세한 내용은 `Agent/TODO.md` 참고).
- [x] Product Search/Seller Search/product_guide 스트리밍 텍스트 노출 버그 수정: `_STREAMING_NODE_NAMES`에
  `product_guide_node` 추가(조건 부족 안내 텍스트도 chitchat처럼 토큰 스트리밍). `_build_interrupted_response`가
  `pending_action["message"]`(일반 "선택해주세요" 문구) 대신 `pending_action["answer"]`(에이전트가 생성한 시리즈/
  판매처별 정보+추천 이유 서술, 이미 "stream" 이벤트로 스트리밍된 바로 그 텍스트)를 우선 사용하도록 수정 —
  기존엔 done 시점에 일반 문구로 덮어써서 카드 뒤에 숨어 사라지던 문제. 프론트 `ProductCards`/`SellerCards` 렌더링도
  제거해 텍스트만 노출(Product Analysis 카드는 유지).
- [x] Windows uvicorn 실행 안정화: async Psycopg/Supabase checkpointer가 ProactorEventLoop에서 기동하지 못하는 문제를 피하기 위해 `FastAPI/loop_factory.py`에 SelectorEventLoop factory 추가. Windows 로컬 실행/검증 시 `--loop FastAPI.loop_factory:selector_loop_factory`로 실행 가능.
- [x] product_analysis JSON 노출 버그 수정: `_STREAMING_NODE_NAMES`에서 `product_analysis_node` 제거 → 내부 RAG query_constructor의 구조화 쿼리 JSON(`{"query":"", "filter":"eq(\"seller\",...)"}` + ```json)과 마크다운 비교표 텍스트가 채팅창에 스트리밍되던 문제 차단. 진행 메시지(progress)와 최종 카드(done)는 유지(카드만 표시)
- [x] 크롤링 진행 SSE 이벤트 처리 추가: on_custom_event / crawl_progress → progress 타입으로 프론트 전달
- [x] _build_input_state에 crawled_context: None 추가
- [x] user_profile: None 매 턴 리셋 버그 수정: _build_input_state에서 user_profile 필드 제거 → checkpointer가 이전 턴 값 유지
# 이번 작업 완료
- [x] ChatResponse와 SSE done payload에 서비스형 오케스트레이션 메타데이터 추가: status, active_agent, pending_action, request_id
- [x] 모듈화 API 응답의 프론트 연결 확인 및 대시보드 pending_action 선택/재요청 UI 연결
- [x] `_NODE_PROGRESS` 메시지 문구 다듬기: `ask_missing_node`가 다른 노드와 달리 "~중..." 진행형이 아니라
  완료형 문장이었던 톤 불일치 수정, `seller_search_worker_node`의 "지원 판매처"(어색한 표현) →
  "구매 가능한 판매처", `check_conditions`의 모호한 "추천 조건" → "필요한 정보", `product_search_worker_node`의
  장황한 문구 축약. 노드 매핑 구조는 그대로, 표시 문구만 변경.
- [x] PS/SS "완료"/"완료완료" 스트리밍 노출 버그(재발) 수정: `_STREAMING_NODE_NAMES`에서 `"agent"` 제거.
  `product_search_worker_node`/`seller_search_worker_node`가 여전히 `config={"callbacks": []}`로
  호출 중인데도, 이후 langchain-core/langgraph 업그레이드로 이 뮤트가 더 이상 스트리밍 이벤트를
  막지 못하는 것을 raw SSE 캡처(`/chat/stream` 직접 curl)로 확인 — 모델이 "완료"만 답하라는 지시를
  무시하고 도구 결과를 다시 베껴 쓴 뒤 "완료"라고 말하는 텍스트가 `stream` 이벤트로 그대로 새어
  나오고 있었음(`_run_search`의 `@task` None-fallback이 거의 매번 걸려 두 번 실행되어 "완료완료"
  패턴으로 보임). config 레이어의 뮤트에 더 의존하지 않고 SSE 방출 화이트리스트에서 `"agent"`를
  아예 빼서 라이브러리 버전과 무관하게 차단(`done.response`는 원래도 `ToolMessage.content`를 직접
  쓰므로 영향 없음). 수정 후 동일 시나리오 재현 curl에서 `stream` 이벤트 0건, `done.response`는
  정상 확인. `_run_search`의 이중 실행 자체(비용/지연 낭비, 정확성엔 무영향)는 별도 이슈로 남김.
