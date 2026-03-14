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


# =============================================================================
# 엔드포인트
# =============================================================================


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    if graph is None:
        raise HTTPException(status_code=503, detail="Agent가 아직 초기화되지 않았습니다.")

    thread_id = f"{payload.user_id}:{payload.session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    # 첫 턴: state 전체 전달 (user_profile=None → load_user_memory 트리거)
    # 이후 턴: checkpointer가 state를 복원하므로 messages만 전달
    # → 두 경우 모두 동일 코드로 처리 가능 (checkpointer가 자동 판단)
    input_state = {
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
        "user_profile": None,  # None → load_user_memory 실행 트리거
    }

    try:
        result = await graph.ainvoke(input_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # 마지막 AI 메시지 추출
    messages = result.get("messages", [])
    ai_messages = [m for m in messages if hasattr(m, "content") and not isinstance(m, HumanMessage)]
    response_text = ai_messages[-1].content if ai_messages else ""

    if not response_text:
        raise HTTPException(status_code=500, detail="Agent가 빈 응답을 반환했습니다.")

    return ChatResponse(
        user_id=payload.user_id,
        session_id=payload.session_id,
        response=response_text,
    )
