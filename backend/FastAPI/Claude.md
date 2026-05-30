# FastAPI 폴더

## 역할
REST API 서버 (현재 사용 버전). LangGraph 에이전트를 HTTP로 노출.

## 엔드포인트
- `GET /health` → 헬스체크
- `POST /chat` → 일반 응답
- `POST /chat/stream` → SSE 스트리밍 응답

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

## 노드 진행 단계 (9개)
load_user_memory, extract_conditions_and_intent, check_conditions,
ask_missing_node, chitchat_node, product_search_node,
seller_search_node, product_analysis_node, save_user_memory

## 주의
- 서버 시작 시 lifespan으로 graph 초기화
- CORS 설정 포함 (프론트 연동)
- `main.py` (루트)는 레거시 버전 → 사용 X
