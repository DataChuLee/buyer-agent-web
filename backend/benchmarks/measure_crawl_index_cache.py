"""Measure the production crawl-and-index registry cache.

Each sample is an exact same-request pair:
1. cache miss: live seller crawl + product document upsert;
2. cache hit: ``crawl_and_index`` recognises the fresh registry entry and
   skips the crawl/index operation.

The benchmark puts its registry JSON in a temporary directory, so it neither
reads nor changes the service's existing cache entries.  The cache-miss side
does use the production vector store, just like the service does, and may
upsert products returned by the live seller site.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarise(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "mean_ms": round(statistics.mean(values), 2),
        "p50_ms": round(statistics.median(values), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


def added_count(summary: str) -> int | None:
    match = re.search(r"(?:총\s*)?(\d+)\s*개", summary or "")
    return int(match.group(1)) if match else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure crawl-and-index cache miss/hit latency.")
    parser.add_argument("--seller", default="soccerboom", choices=["crazy11", "soccerboom", "redsoccer", "cafostore"])
    parser.add_argument("--keyword", default="나이키 머큐리얼")
    parser.add_argument("--min-price", type=int, default=0)
    parser.add_argument("--max-price", type=int, default=999_999)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def timed_invoke(tool: Any, payload: dict[str, Any]) -> tuple[float, str]:
    started_at = time.perf_counter()
    result = await tool.ainvoke(payload)
    return (time.perf_counter() - started_at) * 1000, str(result)


async def async_main(args: argparse.Namespace) -> int:
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1.")
    if args.min_price < 0 or args.max_price < args.min_price:
        raise SystemExit("Price range is invalid.")

    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required because cache misses upsert into Chroma.")

    crawl_module = importlib.import_module("Tools.crawl_and_index")
    registry_module = importlib.import_module("Tools.crawl_registry")
    payload = {
        "sellers": [args.seller],
        "product_keyword": args.keyword,
        "min_price": args.min_price,
        "max_price": args.max_price,
    }
    registry_request = {
        "sellers": payload["sellers"],
        "keyword": payload["product_keyword"],
        "min_price": payload["min_price"],
        "max_price": payload["max_price"],
    }
    original_registry_path = registry_module._REGISTRY_PATH
    miss_latencies: list[float] = []
    hit_latencies: list[float] = []
    samples: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="buyer_agent_crawl_cache_benchmark_") as temp_dir:
        registry_module._REGISTRY_PATH = str(Path(temp_dir) / "crawl_registry.json")
        try:
            for run_index in range(1, args.runs + 1):
                # Delete only this benchmark's temporary cache before each
                # first request.  It guarantees a real cache-miss sample.
                registry_path = Path(registry_module._REGISTRY_PATH)
                if registry_path.exists():
                    registry_path.unlink()

                miss_ms, miss_summary = await timed_invoke(crawl_module.crawl_and_index, payload)
                registered_after_miss = registry_module.is_already_indexed(**registry_request)
                if not registered_after_miss:
                    raise RuntimeError(
                        "Cache-miss call did not create a usable registry entry; "
                        "a cache-hit comparison would be invalid."
                    )
                hit_ms, hit_summary = await timed_invoke(crawl_module.crawl_and_index, payload)
                registered_after_hit = registry_module.is_already_indexed(**registry_request)
                if not registered_after_hit:
                    raise RuntimeError("Registry entry unexpectedly disappeared before the cache-hit call.")

                miss_latencies.append(miss_ms)
                hit_latencies.append(hit_ms)
                samples.append(
                    {
                        "run": run_index,
                        "cache_miss": {
                            "latency_ms": round(miss_ms, 2),
                            "summary": miss_summary,
                            "reported_document_count": added_count(miss_summary),
                        },
                        "cache_hit": {
                            "latency_ms": round(hit_ms, 2),
                            "summary": hit_summary,
                        },
                    }
                )
        finally:
            registry_module._REGISTRY_PATH = original_registry_path

    miss_stats = summarise(miss_latencies)
    hit_stats = summarise(hit_latencies)
    p50_reduction = (1 - hit_stats["p50_ms"] / miss_stats["p50_ms"]) * 100
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "request": payload,
            "runs": args.runs,
            "cache": {
                "implementation": "Tools.crawl_registry (persistent crawl-and-index registry)",
                "matching": "same request key; benchmark uses an exact repeated request",
                "ttl": "24 hours (default)",
                "storage": "temporary registry file; existing service cache entries were not read or changed",
            },
            "cache_miss": "live seller crawl plus production Chroma document upsert",
            "cache_hit": "same crawl_and_index tool; skips live crawling and document upsert",
            "excluded": ["LangGraph orchestration", "RAG retrieval", "CRAG/Self-RAG", "LLM answer generation", "HTTP/SSE"],
        },
        "important_interpretation": (
            "Live seller response time is externally variable. Compare cache-miss and cache-hit p50/p95 "
            "only within this exact request and execution environment; do not present this as full chat E2E latency."
        ),
        "cache_miss": miss_stats,
        "cache_hit": hit_stats,
        "p50_latency_reduction_percent": round(p50_reduction, 2),
        "p50_speedup_x": round(miss_stats["p50_ms"] / hit_stats["p50_ms"], 2),
        "samples": samples,
    }
    output = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"crawl_index_cache_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Crawl/index cache benchmark completed")
    print(f"  miss p50 / p95: {miss_stats['p50_ms']}ms / {miss_stats['p95_ms']}ms")
    print(f"  hit p50 / p95: {hit_stats['p50_ms']}ms / {hit_stats['p95_ms']}ms")
    print(f"  p50 reduction: {report['p50_latency_reduction_percent']}% ({report['p50_speedup_x']}x)")
    print(f"  report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main(parse_args())))
