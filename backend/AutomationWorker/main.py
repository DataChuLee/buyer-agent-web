from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from AutomationWorker.models import AutomationRun, CheckoutSessionPayload
from AutomationWorker.service import LocalAutomationService


def _cors_origins() -> list[str]:
    raw = os.getenv("LOCAL_AUTOMATION_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [item.strip() for item in raw.split(",") if item.strip()]


service = LocalAutomationService()

app = FastAPI(
    title="Buyer Agent Local Automation Worker",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "agent_browser_available": service.runner.is_available(),
        "browser_profile": getattr(service.runner, "profile_name", None),
    }


@app.post("/sessions/start", response_model=AutomationRun)
async def start_session(payload: CheckoutSessionPayload) -> AutomationRun:
    return await service.start_session(payload)


@app.get("/sessions/{run_id}", response_model=AutomationRun)
def get_session(run_id: str) -> AutomationRun:
    try:
        return service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Automation run not found.") from exc


@app.post("/sessions/{run_id}/approve", response_model=AutomationRun)
async def approve_session(run_id: str) -> AutomationRun:
    try:
        return await service.approve_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Automation run not found.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/sessions/{run_id}/cancel", response_model=AutomationRun)
async def cancel_session(run_id: str) -> AutomationRun:
    try:
        return await service.cancel_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Automation run not found.") from exc


@app.get("/sessions/{run_id}/artifacts/{filename}")
def get_artifact(run_id: str, filename: str) -> FileResponse:
    try:
        run = service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Automation run not found.") from exc

    if run.artifact_path is None or run.artifact_path.name != filename or not run.artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    return FileResponse(run.artifact_path)
