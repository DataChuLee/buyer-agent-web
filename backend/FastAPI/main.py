"""
FastAPI/main.py
===============
LangGraph BuyerAgent (with personalization) FastAPI 서버

엔드포인트:
  GET  /health          → 서버 상태 확인
  POST /chat            → 대화 (user_id, session_id, message)

실행 방법 (backend/ 디렉토리에서):
  uvicorn FastAPI.main:app --reload --port 8000
"""

import json
import os
import sys

# backend/ 를 sys.path에 추가 (Agent, State, Tools 등 import를 위해)
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

load_dotenv()


# =============================================================================
# 앱 Lifespan — 서버 시작 시 그래프 1회 초기화
# =============================================================================

graph = None  # 전역 그래프 인스턴스


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    print("[Startup] LangGraph BuyerAgent 초기화 중...")
    from Agent.LangGraph_buyeragent_with_personalization import build_graph

    graph = await build_graph()
    print("[Startup] LangGraph BuyerAgent 초기화 완료")
    yield
    print("[Shutdown] 서버 종료")


# =============================================================================
# FastAPI 앱
# =============================================================================

app = FastAPI(
    title="Buyer Agent API",
    version="1.0.0",
    description="축구화 구매 에이전트 (LangGraph + LangMem 개인화)",
    lifespan=lifespan,
)


def _get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# 요청 / 응답 스키마
# =============================================================================
class ChatRequest(BaseModel):
    user_id: str = Field(..., description="유저 식별자. 예: 'user_123'")
    session_id: str = Field(..., description="세션 식별자. 예: 'session_001'")
    message: str = Field(..., min_length=1, max_length=4000, description="유저 메시지")


class ChatResponse(BaseModel):
    user_id: str
    session_id: str
    response: str
    options: list[str] | None = None          # 현재 질문의 선택지
    question_sequence: list[dict] | None = None  # 남은 전체 질문 시퀀스
    products: list[dict] | None = None        # 구조화 제품 카드 목록
    sellers: list[dict] | None = None         # 구조화 판매처 카드 목록
    analysis: list[dict] | None = None        # 구조화 제품 분석 카드 목록


# =============================================================================
# 엔드포인트
# =============================================================================


# 노드명 → 사용자에게 보여줄 진행 메시지
_NODE_PROGRESS: dict[str, str | None] = {
    "load_user_memory": "사용자 정보 불러오는 중...",
    "extract_conditions_and_intent": "요청 의도 분석 중...",
    "check_conditions": None,
    "ask_missing_node": None,
    "chitchat_node": None,
    "product_search_node": "제품을 검색하는 중...",
    "seller_search_node": "판매자를 탐색하는 중...",
    "product_analysis_node": "제품을 비교 분석하는 중...",
    "save_user_memory": "결과를 정리하는 중...",
}


def _build_input_state(payload: "ChatRequest") -> dict:
    return {
        "session_id": payload.session_id,
        "user_id": payload.user_id,
        "messages": [HumanMessage(content=payload.message)],
        "intent": "",
        "active_agent": None,
        "user_conditions": {},
        "missing_conditions": [],
        "search_result": [],
        "status": "extracting",
        "error": None,
        "retry_count": 0,
        "user_profile": None,
        "question_options": None,
        "question_sequence": None,
        "products": None,
        "sellers": None,
        "analysis": None,
    }


def _build_chat_response(result: dict) -> "ChatResponse":
    messages = result.get("messages", [])
    ai_messages = [
        m for m in messages if hasattr(m, "content") and not isinstance(m, HumanMessage)
    ]
    response_text = ai_messages[-1].content if ai_messages else ""

    status = result.get("status")
    options = result.get("question_options") if status == "waiting_input" else None
    question_sequence = result.get("question_sequence") if status == "waiting_input" else None
    products = result.get("products") if status == "done" else None
    sellers = result.get("sellers") if status == "done" else None
    analysis = result.get("analysis") if status == "done" else None

    return ChatResponse(
        user_id=result.get("user_id", ""),
        session_id=result.get("session_id", ""),
        response=response_text,
        options=options,
        question_sequence=question_sequence,
        products=products,
        sellers=sellers,
        analysis=analysis,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    if graph is None:
        raise HTTPException(
            status_code=503, detail="Agent가 아직 초기화되지 않았습니다."
        )

    thread_id = f"{payload.user_id}:{payload.session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    try:
        result = await graph.ainvoke(_build_input_state(payload), config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    chat_response = _build_chat_response(result)
    if not chat_response.response:
        raise HTTPException(status_code=500, detail="Agent가 빈 응답을 반환했습니다.")

    return chat_response


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    if graph is None:
        raise HTTPException(
            status_code=503, detail="Agent가 아직 초기화되지 않았습니다."
        )

    thread_id = f"{payload.user_id}:{payload.session_id}"
    config = {"configurable": {"thread_id": thread_id}}
    input_state = _build_input_state(payload)

    async def event_generator():
        try:
            final_result: dict = {}
            async for event in graph.astream_events(input_state, config=config, version="v2"):
                event_type: str = event.get("event", "")
                event_name: str = event.get("name", "")

                # 노드 시작 시 진행 메시지 전송
                if event_type == "on_chain_start" and event_name in _NODE_PROGRESS:
                    msg = _NODE_PROGRESS[event_name]
                    if msg:
                        yield f"data: {json.dumps({'type': 'progress', 'message': msg}, ensure_ascii=False)}\n\n"

                # chitchat_node LLM 토큰 스트리밍
                elif event_type == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name == "chitchat_node":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "content") and chunk.content:
                            yield f"data: {json.dumps({'type': 'stream', 'chunk': chunk.content}, ensure_ascii=False)}\n\n"

                # 그래프 전체 완료 시 최종 결과 캡처
                elif event_type == "on_chain_end" and event_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    if output:
                        final_result = output

            # 최종 결과 전송
            chat_response = _build_chat_response(final_result)
            done_payload = {
                "type": "done",
                "response": chat_response.response,
                "options": chat_response.options,
                "question_sequence": chat_response.question_sequence,
                "products": chat_response.products,
                "sellers": chat_response.sellers,
                "analysis": chat_response.analysis,
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

        except Exception as exc:
            error_payload = json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
