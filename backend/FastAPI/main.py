import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langchain_teddynote import logging as langsmith_logging
from langgraph.types import Command
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

load_dotenv()

graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    # Agent 모듈 import(및 그 안의 ChatOpenAI 생성)보다 먼저 실행되어야 첫 그래프 빌드부터
    # 추적된다. .env의 LANGCHAIN_API_KEY/LANGCHAIN_PROJECT를 사용. 서버 기동 시(lifespan)에만
    # 실행되므로 유닛 테스트가 미리 꺼둔 LANGSMITH_TRACING=false를 덮어쓰지 않는다.
    langsmith_logging.langsmith("buyer-agent_0706")

    from Agent.LangGraph_buyeragent_with_personalization import build_graph

    graph = await build_graph()

    # 인기 키워드 사전 크롤 워밍업 — 비차단 백그라운드 태스크.
    # WARMUP_DISABLED=1 으로 끄거나 yaml 미존재 시 자동 스킵됨.
    if os.getenv("WARMUP_DISABLED", "").lower() not in {"1", "true", "yes"}:
        from Tools.warmup_crawler import warmup

        asyncio.create_task(warmup())

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
    status: str | None = None
    active_agent: str | None = None
    pending_action: dict | None = None
    request_id: str | None = None
    options: list[Any] | None = None
    question_sequence: list[dict] | None = None
    products: list[dict] | None = None
    sellers: list[dict] | None = None
    analysis: list[dict] | None = None
    purchase_status: str | None = None
    selected_product: dict | None = None
    checkout_session: dict | None = None
    required_fields: list[str] | None = None


_NODE_PROGRESS: dict[str, dict | None] = {
    "load_user_memory": {
        "agent": "system",
        "step": "loading_memory",
        "message": "사용자 정보를 불러오는 중...",
    },
    "extract_conditions_and_intent": {
        "agent": "system",
        "step": "analyzing_request",
        "message": "요청 내용을 분석하는 중...",
    },
    "check_conditions": {
        "agent": "system",
        "step": "checking_conditions",
        "message": "필요한 정보가 모두 있는지 확인하는 중...",
    },
    "ask_missing_node": {
        "agent": "product_search",
        "step": "collecting_conditions",
        "message": "부족한 정보를 확인하는 중...",
    },
    "supervisor_node": {
        "agent": "system",
        "step": "planning_next_step",
        "message": "다음에 할 일을 판단하는 중...",
    },
    "product_search_worker_node": {
        "agent": "product_search",
        "step": "searching_products",
        "message": "조건에 맞는 축구화/풋살화를 검색하는 중...",
    },
    "seller_search_worker_node": {
        "agent": "seller_search",
        "step": "searching_sellers",
        "message": "구매 가능한 판매처를 검색하는 중...",
    },
    "product_analysis_worker_node": {
        "agent": "product_analysis",
        "step": "collecting_product_pages",
        "message": "상품 페이지를 수집하고 분석하는 중...",
    },
    "product_guide_node": {
        "agent": "product_guide",
        "step": "generating_guide",
        "message": "축구화 선택 기준을 정리하는 중...",
    },
    "purchase_prepare_node": {
        "agent": "purchase_prepare",
        "step": "preparing_purchase",
        "message": "주문 준비 정보를 확인하는 중...",
    },
    "chitchat_node": None,
    "save_user_memory": None,
    "queue_user_memory_save": None,
}

_STREAMING_NODE_NAMES = {
    "chitchat_node",
    # product_guide_node는 chitchat_node와 동일하게 .ainvoke()로 직접 호출되므로
    # (create_react_agent를 쓰지 않음) 이벤트의 langgraph_node에 자기 노드 이름 그대로 찍힌다.
    "product_guide_node",
    # "agent"(product_search_worker_node/seller_search_worker_node의 react agent 내부 노드)는
    # 의도적으로 뺐다: 이 두 워커는 모델의 생성 텍스트를 버리고 도구(ToolMessage) 원문을 최종
    # 답변으로 쓰므로(product_search_agent.py/seller_search_agent.py), 모델이 실제로 생성하는
    # 텍스트는 "도구 결과를 베껴 쓰고 완료라고 답하라"는 시스템 프롬프트를 무시하고 목록을 다시
    # 베껴 쓴 뒤 "완료"라고 말하는, 사용자에게 보여줄 일이 없는 텍스트다. 과거엔 워커가 그 호출에
    # config={"callbacks": []}를 넘겨 스트리밍 자체를 막았지만, 이후 langchain-core/langgraph
    # 업그레이드로 그 뮤트가 더 이상 이벤트를 막지 못하는 게 실측(raw SSE 캡처)으로 확인됐다 —
    # config 레이어의 뮤트에 의존하는 대신 이 화이트리스트에서 아예 빼서 SSE 방출 단계에서
    # 차단한다(라이브러리 버전에 안전).
    # product_analysis_worker_node 제거: 내부 RAG query_constructor JSON 및 비교표 텍스트가
    # 사용자에게 새어 나가는 문제 차단. 진행 메시지(progress)와 최종 카드(done)는 유지.
}


def _build_progress_payload(node_name: str) -> dict | None:
    progress = _NODE_PROGRESS.get(node_name)
    if not progress:
        return None
    return {"type": "progress", **progress}


def _extract_stream_chunk(event: dict) -> str | None:
    if event.get("event", "") != "on_chat_model_stream":
        return None

    node_name = event.get("metadata", {}).get("langgraph_node", "")
    if node_name not in _STREAMING_NODE_NAMES:
        return None

    chunk = event.get("data", {}).get("chunk")
    content = getattr(chunk, "content", None)
    return content or None


async def _resolve_graph_input(payload: ChatRequest, config: dict) -> dict | Command:
    # 워커 노드가 interrupt() 로 멈춰있는 스레드면, 새 입력 state를 만드는 대신 사용자의
    # 자유 응답을 Command(resume=...)로 그 노드 안에 그대로 이어서 넣어준다.
    snapshot = await graph.aget_state(config)
    if snapshot.interrupts:
        return Command(resume=payload.message)
    return _build_input_state(payload)


def _build_input_state(payload: ChatRequest) -> dict:
    return {
        "session_id": payload.session_id,
        "user_id": payload.user_id,
        "request_id": str(uuid4()),
        "messages": [HumanMessage(content=payload.message)],
        "intent": "",
        "active_agent": None,
        "missing_conditions": [],
        "status": "extracting",
        "error": None,
        "retry_count": 0,
        "question_options": None,
        # question_sequence는 체크포인터에서 복원된 값을 유지해야 함.
        # 리셋하면 조건 수집 중 턴에서 question_sequence가 사라져 seller_search로 잘못 라우팅됨.
        "products": None,
        "sellers": None,
        "analysis": None,
    }


_PENDING_TYPE_TO_AGENT = {
    "ps_review": "product_search",
    "ss_review": "seller_search",
    "pa_review": "product_analysis",
}
_PENDING_TYPE_TO_FIELD = {
    "ps_review": "products",
    "ss_review": "sellers",
    "pa_review": "analysis",
}


def _build_interrupted_response(result: dict, pending_action: dict) -> ChatResponse:
    # 워커 노드가 interrupt() 로 멈춘 시점에는 그 턴의 반환 dict가 아직 커밋되지 않았으므로,
    # 이번에 보여줄 카드/메시지는 result가 아니라 인터럽트 payload에서 가져와야 한다.
    field = _PENDING_TYPE_TO_FIELD.get(pending_action.get("type"))
    return ChatResponse(
        user_id=result.get("user_id", ""),
        session_id=result.get("session_id", ""),
        # answer(에이전트가 생성한 시리즈/판매처별 정보+추천 이유 서술)가 있으면 그걸 노출한다.
        # 이미 "stream" 이벤트로 토큰 단위 스트리밍된 바로 그 텍스트이므로, done 시점에 일반
        # 안내 문구(message)로 덮어써서 사라지지 않도록 한다.
        response=pending_action.get("answer") or pending_action.get("message", ""),
        status="waiting_input",
        active_agent=_PENDING_TYPE_TO_AGENT.get(pending_action.get("type")),
        pending_action=pending_action,
        request_id=result.get("request_id"),
        options=pending_action.get("options"),
        **({field: pending_action.get("cards")} if field else {}),
    )


def _build_chat_response(result: dict) -> ChatResponse:
    if interrupts := result.get("__interrupt__"):
        return _build_interrupted_response(result, interrupts[0].value)

    messages = result.get("messages", [])
    ai_messages = [message for message in messages if hasattr(message, "content") and not isinstance(message, HumanMessage)]
    response_text = ai_messages[-1].content if ai_messages else ""
    status = result.get("status")
    return ChatResponse(
        user_id=result.get("user_id", ""),
        session_id=result.get("session_id", ""),
        response=response_text,
        status=status,
        active_agent=result.get("active_agent"),
        pending_action=None,
        request_id=result.get("request_id"),
        options=result.get("question_options") if status == "waiting_input" else None,
        question_sequence=result.get("question_sequence") if status == "waiting_input" else None,
        products=result.get("products") if status in {"done", "waiting_input"} else None,
        sellers=result.get("sellers") if status in {"done", "waiting_input"} else None,
        analysis=result.get("analysis") if status in {"done", "waiting_input"} else None,
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
        graph_input = await _resolve_graph_input(payload, config)
        result = await graph.ainvoke(graph_input, config=config)
    except Exception as exc:
        logger.exception("chat endpoint failed")
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
    graph_input = await _resolve_graph_input(payload, config)

    async def event_generator():
        final_result: dict = {}
        try:
            async for event in graph.astream_events(graph_input, config=config, version="v2"):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                if event_type == "on_chain_start" and event_name in _NODE_PROGRESS:
                    payload = _build_progress_payload(event_name)
                    if payload:
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif event_type == "on_chat_model_stream":
                    chunk = _extract_stream_chunk(event)
                    if chunk:
                        yield f"data: {json.dumps({'type': 'stream', 'chunk': chunk}, ensure_ascii=False)}\n\n"
                elif event_type == "on_chain_end" and event_name == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    if output:
                        final_result = output

            if "__interrupt__" not in final_result:
                # astream_events의 최종 LangGraph 출력에는 __interrupt__가 실리지 않으므로
                # (ainvoke와 달리), 스트림 종료 후 체크포인트 상태를 직접 확인해 보충한다.
                snapshot = await graph.aget_state(config)
                if snapshot.interrupts:
                    final_result = {**final_result, "__interrupt__": list(snapshot.interrupts)}

            response = _build_chat_response(final_result)
            done_payload = {
                "type": "done",
                "response": response.response,
                "status": response.status,
                "active_agent": response.active_agent,
                "pending_action": response.pending_action,
                "request_id": response.request_id,
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
            logger.exception("chat/stream endpoint failed")
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
