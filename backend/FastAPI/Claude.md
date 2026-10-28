# FastAPI 폴더

## 역할
REST API 서버 (현재 사용 버전). LangGraph 에이전트를 HTTP로 노출.

## 엔드포인트
- `GET /health` → 헬스체크
- `POST /chat` → 일반 응답
- `POST /chat/stream` → SSE 스트리밍 응답

## 실행 보조 파일
- `loop_factory.py` → Windows 로컬 실행에서 uvicorn이 ProactorEventLoop를 선택하면 async Psycopg/Supabase checkpointer가 기동하지 못할 수 있어, `--loop FastAPI.loop_factory:selector_loop_factory`로 넘길 SelectorEventLoop factory를 제공한다.

## Request Schema
```python
ChatRequest:
  user_id: str        # 유저 식별자
  session_id: str     # 세션 식별자
  message: str        # 메시지 (1-4000자)
```

## Response Schema
```python
ChatResponse:
  user_id, session_id
  response: str                    # 응답 텍스트
  options: list[str] | None        # 현재 질문 선택지
  question_sequence: list[dict] | None
  products: list[dict] | None      # 상품 카드
  sellers: list[dict] | None       # 판매자 카드
  analysis: list[dict] | None      # 분석 카드
```

## SSE 스트림 이벤트 (chat/stream)
`progress` → `stream` → `done`

## 노드 진행 단계
load_user_memory, extract_conditions_and_intent, check_conditions,
ask_missing_node, chitchat_node, supervisor_node, product_search_worker_node,
seller_search_worker_node, product_analysis_worker_node, save_user_memory

## 주의
- 서버 시작 시 lifespan으로 graph 초기화
- CORS 설정 포함 (프론트 연동)
- `main.py` (루트)는 레거시 버전 → 사용 X

# Orchestration API 메타데이터
- `ChatResponse`와 SSE `done` 이벤트는 `status`, `active_agent`, `pending_action`, `request_id`를 포함한다.
- `pending_action`은 PS/SS/PA Human-in-the-Loop 대기 상태를 표현하며, 다음 `ChatRequest.message`가 자연어 resume 입력으로 처리된다.
- **내부 구현은 LangGraph 네이티브 `interrupt()`/`Command(resume=...)`로 바뀌었지만 이 API 계약은 그대로다.**
  `/chat`·`/chat/stream` 모두 요청 시작 시 `graph.aget_state(config)`로 스레드가 중단(interrupt) 상태인지
  먼저 확인한다(`_resolve_graph_input`) — 중단 중이면 `Command(resume=payload.message)`로 그 워커 노드
  안에서 그대로 이어서 실행하고, 아니면 평소처럼 새 입력 state를 만든다. `_build_chat_response`는
  `result["__interrupt__"]`가 있으면 그 안의 `Interrupt.value`(=`PendingAction` 모양 dict)에서 `message`/
  `cards`/`options`를 꺼내 응답을 만든다(그 턴 워커의 반환 dict는 아직 커밋되지 않았으므로 `result["products"]`
  등 일반 필드는 이전 턴 값이라 쓸 수 없음). `/chat/stream`은 `astream_events`의 최종 `LangGraph` 출력에
  `__interrupt__`가 실리지 않는 것을 확인했으므로, 스트림 종료 후 `graph.aget_state(config)`를 한 번 더
  확인해 보충한다.
