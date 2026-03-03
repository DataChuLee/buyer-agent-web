import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_teddynote import logging
from pydantic import BaseModel, Field

load_dotenv()
logging.langsmith("buyer-agent-saas-test_0221")

app = FastAPI(title="Buyer Agent Backend", version="0.1.0")


def _get_cors_origins() -> list[str]:
    raw_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BuyerAgentRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    thread_id: str = Field(default="user-001", min_length=1, max_length=200)


class BuyerAgentResponse(BaseModel):
    response: str
    agent: str
    intent: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/buyer-agent/buyer_agent_0221", response_model=BuyerAgentResponse)
async def run_buyer_agent(payload: BuyerAgentRequest) -> BuyerAgentResponse:
    try:
        try:
            from Agent.orchestrator_agent import orchestrator_agent
        except ModuleNotFoundError:
            from backend.Agent.orchestrator_agent import orchestrator_agent

        result = await orchestrator_agent(
            query=payload.query,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Orchestrator returned invalid payload")

    response = str(result.get("response", "")).strip()
    agent = str(result.get("agent", "")).strip()
    intent = str(result.get("intent", "")).strip()

    if not response:
        raise HTTPException(status_code=500, detail="Agent returned an empty response")
    if not agent:
        agent = "orchestrator"
    if not intent:
        intent = "unknown"

    return BuyerAgentResponse(
        response=response,
        agent=agent,
        intent=intent,
    )
