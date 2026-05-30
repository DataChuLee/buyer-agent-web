import json
import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

load_dotenv()

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    from Agent.LangGraph_buyeragent_with_personalization import build_graph

    graph = await build_graph()
    yield


app = FastAPI(
    title="Buyer Agent API",
    version="1.0.0",
    description="Buyer Agent backend",
    lifespan=lifespan,
)


def _get_cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [item.strip() for item in raw.split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    user_id: str = Field(...)
    session_id: str = Field(...)
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    user_id: str
    session_id: str
    response: str
    options: list[str] | None = None
    question_sequence: list[dict] | None = None
    products: list[dict] | None = None
    sellers: list[dict] | None = None
    analysis: list[dict] | None = None
    purchase_status: str | None = None
    selected_product: dict | None = None
    checkout_session: dict | None = None
    required_fields: list[str] | None = None


_NODE_PROGRESS: dict[str, str | None] = {
    "load_user_memory": "사용자 정보를 불러오는 중...",
    "extract_conditions_and_intent": "요청을 분석하는 중...",
    "check_conditions": None,
    "ask_missing_node": None,
    "product_search_node": "상품을 찾는 중...",
    "seller_search_node": "판매처를 찾는 중...",
    "product_analysis_node": "상품을 분석하는 중...",
    "purchase_prepare_node": "주문 준비 정보를 확인하는 중...",
    "chitchat_node": None,
    "save_user_memory": None,
}


def _build_input_state(payload: ChatRequest) -> dict:
    return {
        "session_id": payload.session_id,
        "user_id": payload.user_id,
        "messages": [HumanMessage(content=payload.message)],
        "intent": "",
        "active_agent": None,
        "missing_conditions": [],
        "status": "extracting",
        "error": None,
        "retry_count": 0,
        "question_options": None,
        "question_sequence": None,
        "products": None,
        "sellers": None,
        "analysis": None,
    }


def _build_chat_response(result: dict) -> ChatResponse:
    messages = result.get("messages", [])
    ai_messages = [message for message in messages if hasattr(message, "content") and not isinstance(message, HumanMessage)]
    response_text = ai_messages[-1].content if ai_messages else ""
    status = result.get("status")
    return ChatResponse(
        user_id=result.get("user_id", ""),
        session_id=result.get("session_id", ""),
        response=response_text,
        options=result.get("question_options") if status == "waiting_input" else None,
        question_sequence=result.get("question_sequence") if status == "waiting_input" else None,
        products=result.get("products") if status == "done" else None,
        sellers=result.get("sellers") if status == "done" else None,
        analysis=result.get("analysis") if status == "done" else None,
        purchase_status=result.get("purchase_status"),
        selected_product=result.get("selected_product"),
        checkout_session=result.get("checkout_session"),
        required_fields=result.get("purchase_missing_fields") or None,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph is not initialized")
    config = {"configurable": {"thread_id": f"{payload.user_id}:{payload.session_id}"}}
    try:
        result = await graph.ainvoke(_build_input_state(payload), config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    response = _build_chat_response(result)
    if not response.response:
        raise HTTPException(status_code=500, detail="Empty agent response")
    return response


@app.post("/chat/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    if graph is None:
        raise HTTPException(status_code=503, detail="Graph is not initialized")

    config = {"configurable": {"thread_id": f"{payload.user_id}:{payload.session_id}"}}
    input_state = _build_input_state(payload)

    async def event_generator():
        final_result: dict = {}
        try:
            async for event in graph.astream_events(input_state, config=config, version="v2"):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                if event_type == "on_chain_start" and event_name in _NODE_PROGRESS:
                    message = _NODE_PROGRESS[event_name]
                    if message:
                        yield f"data: {json.dumps({'type': 'progress', 'message': message}, ensure_ascii=False)}\n\n"
                elif event_type == "on_chat_model_stream":
                    node_name = event.get("metadata", {}).get("langgraph_node", "")
                    if node_name == "chitchat_node":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and getattr(chunk, "content", None):
                            yield f"data: {json.dumps({'type': 'stream', 'chunk': chunk.content}, ensure_ascii=False)}\n\n"
                elif event_type == "on_chain_end" and event_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    if output:
                        final_result = output

            response = _build_chat_response(final_result)
            done_payload = {
                "type": "done",
                "response": response.response,
                "options": response.options,
                "question_sequence": response.question_sequence,
                "products": response.products,
                "sellers": response.sellers,
                "analysis": response.analysis,
                "purchase_status": response.purchase_status,
                "selected_product": response.selected_product,
                "checkout_session": response.checkout_session,
                "required_fields": response.required_fields,
            }
            yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
