"""Measure SSE first-event and completion latency against a running API server.

Run the FastAPI server separately, then invoke this script. It does not start
the server because product analysis can trigger external crawling and that
should be controlled explicitly by the benchmark operator.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] * (1 - (position - lower)) + ordered[upper] * (position - lower)


def summarise(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "mean_ms": round(statistics.mean(values), 2),
        "p50_ms": round(statistics.median(values), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
    }


async def measure_once(client: httpx.AsyncClient, url: str, message: str) -> dict[str, float]:
    started = time.perf_counter()
    first_event_ms: float | None = None
    first_token_ms: float | None = None
    completed_ms: float | None = None
    async with client.stream(
        "POST",
        url,
        json={"user_id": "benchmark", "session_id": str(uuid4()), "message": message},
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            elapsed_ms = (time.perf_counter() - started) * 1000
            if first_event_ms is None:
                first_event_ms = elapsed_ms
            if event.get("type") == "stream" and event.get("chunk") and first_token_ms is None:
                first_token_ms = elapsed_ms
            if event.get("type") in {"done", "error"}:
                completed_ms = elapsed_ms
                if event.get("type") == "error":
                    raise RuntimeError(f"Stream returned an error event: {event.get('message')}")
                break
    if first_event_ms is None or completed_ms is None:
        raise RuntimeError("Stream ended without a first event and done event.")
    return {
        "first_event_ms": first_event_ms,
        "first_token_ms": first_token_ms if first_token_ms is not None else -1.0,
        "completed_ms": completed_ms,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure Buyer Agent SSE endpoint latency.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/chat/stream")
    parser.add_argument("--message", required=True, help="Stable benchmark prompt.")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--start-local-server",
        action="store_true",
        help="Start a temporary local API server with the Windows SelectorEventLoop workaround.",
    )
    parser.add_argument(
        "--in-memory-state",
        action="store_true",
        help="When starting a local server, use LangGraph in-memory state instead of Supabase/PostgreSQL.",
    )
    return parser.parse_args()


def start_local_server(url: str, use_in_memory_state: bool) -> subprocess.Popen[str]:
    """Start uvicorn with the repository's Psycopg-compatible loop factory."""
    if not url.startswith("http://127.0.0.1:"):
        raise SystemExit("--start-local-server only supports a localhost URL.")
    port_and_path = url.removeprefix("http://127.0.0.1:")
    port = port_and_path.split("/", 1)[0]
    if not port.isdigit():
        raise SystemExit("Could not determine the localhost port from --url.")

    child_env = os.environ.copy()
    child_env["WARMUP_DISABLED"] = "1"
    child_env["LANGSMITH_TRACING"] = "false"
    if use_in_memory_state:
        # load_dotenv() does not overwrite existing environment variables, so
        # this prevents backend/.env from enabling the Supabase pools.
        child_env["DATABASE_URL"] = ""
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "FastAPI.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        port,
        "--loop",
        "FastAPI.loop_factory:selector_loop_factory",
    ]
    return subprocess.Popen(
        command,
        cwd=BACKEND_DIR,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


async def wait_for_local_server(process: subprocess.Popen[str], url: str) -> None:
    health_url = url.rsplit("/", 2)[0] + "/health"
    deadline = time.monotonic() + 90
    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read() if process.stdout else ""
                raise RuntimeError(f"Local FastAPI server exited during startup.\n{output[-4000:]}")
            try:
                response = await client.get(health_url)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    process.terminate()
    output = process.stdout.read() if process.stdout else ""
    raise RuntimeError(f"Timed out waiting for local FastAPI server.\n{output[-4000:]}")


async def async_main(args: argparse.Namespace) -> int:
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1.")
    if args.in_memory_state and not args.start_local_server:
        raise SystemExit("--in-memory-state requires --start-local-server.")
    process = start_local_server(args.url, args.in_memory_state) if args.start_local_server else None
    output_path = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"chat_stream_e2e_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    try:
        if process is not None:
            await wait_for_local_server(process, args.url)
        timeout = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            samples = [await measure_once(client, args.url, args.message) for _ in range(args.runs)]
    except Exception as exc:
        failure_report = {
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "scope": {
                "url": args.url,
                "message": args.message,
                "requested_runs": args.runs,
                "state_backend": "in_memory" if args.in_memory_state else "configured_server",
            },
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(failure_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"SSE end-to-end benchmark failed; diagnostics: {output_path}")
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    first_tokens = [sample["first_token_ms"] for sample in samples if sample["first_token_ms"] >= 0]
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "url": args.url,
            "message": args.message,
            "runs": args.runs,
            "session_policy": "A fresh session_id is used for every request.",
            "state_backend": "in_memory" if args.in_memory_state else "configured_server",
        },
        "important_interpretation": (
            "first_event_ms is the first SSE progress event, not necessarily the first LLM token. "
            "completed_ms includes the full remote-agent and crawler path for the selected prompt."
        ),
        "first_sse_event": summarise([sample["first_event_ms"] for sample in samples]),
        "first_llm_token": summarise(first_tokens) if first_tokens else None,
        "stream_completed": summarise([sample["completed_ms"] for sample in samples]),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("SSE end-to-end benchmark completed")
    print(f"  first SSE event p50 / p95: {report['first_sse_event']['p50_ms']}ms / {report['first_sse_event']['p95_ms']}ms")
    print(f"  completed p50 / p95: {report['stream_completed']['p50_ms']}ms / {report['stream_completed']['p95_ms']}ms")
    print(f"  report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main(parse_args())))
