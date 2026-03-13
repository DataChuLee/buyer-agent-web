import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langchain_teddynote import logging
from pydantic import BaseModel, Field

load_dotenv()
logging.langsmith("buyer-agent-saas_0313")

app = FastAPI(title="Buyer Agent Fast API", version="0.1.0")


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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/buyer-agent/buyer_agent_0313", response_model=BuyerAgentResponse)
async def run_buyer_agent(payload: BuyerAgentRequest) -> BuyerAgentResponse:
    try:
        from Agent.orchestrator_agent_0310 import orchestrator_agent

        result = await orchestrator_agent(
            query=payload.query,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response = str(result).strip() if result else ""

    if not response:
        raise HTTPException(status_code=500, detail="Agent returned an empty response")

    return BuyerAgentResponse(response=response)
