"""Measure the real Product Analysis Agent over already indexed RAG data.

The measurement calls the production `product_analysis_agent` and its CRAG,
answer-generation, and groundedness stages.  Only crawling is replaced with a
read from the existing Chroma collection, so this isolates the indexed RAG
agent path from volatile seller-site latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
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


def candidate_cases(metadatas: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    cases: list[dict[str, str]] = []
    for metadata in metadatas:
        seller = str(metadata.get("seller") or "").strip()
        name = str(metadata.get("product_name") or "").strip()
        key = (seller, name)
        if not seller or len(name) < 3 or key in seen:
            continue
        seen.add(key)
        cases.append({"seller": seller, "product_name": name})
    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure the indexed Product Analysis Agent E2E path.")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--case-report",
        type=Path,
        help="Reuse scope.request_case from a previous successful JSON report to skip case discovery.",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1.")
    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required; no measurement was run.")

    import Agent.product_analysis_agent as analysis_agent
    from Tools.rag_search import retrieve_analysis_documents_filtered
    from Tools.seller_normalization import normalize_seller_display
    from Tools.vectorstore_singleton import CHROMA_PERSIST_DIR, vectorstore

    metadata_rows = vectorstore._collection.get(include=["metadatas"], limit=vectorstore._collection.count())
    if args.case_report:
        previous_report = json.loads(args.case_report.read_text(encoding="utf-8"))
        case = previous_report.get("scope", {}).get("request_case")
        if not isinstance(case, dict) or not case.get("seller") or not case.get("product_name"):
            raise SystemExit("--case-report does not contain scope.request_case with seller and product_name.")
    else:
        case = None
        for candidate in candidate_cases(metadata_rows.get("metadatas") or []):
            # The preflight is intentionally outside the measured samples. It
            # ensures every recorded run exercises CRAG, generation, and grounding
            # rather than taking the early "no matching document" return path.
            docs = retrieve_analysis_documents_filtered(
                seller_display=candidate["seller"],
                product_keyword=candidate["product_name"],
                min_price=0,
                max_price=999_999,
            )
            if docs:
                case = candidate
                break
    if case is None:
        raise RuntimeError("No retrievable product case was found in the indexed collection.")
    retrieval_latencies: list[float] = []

    async def indexed_search_only(
        seller: str,
        product_keyword: str,
        min_price: int,
        max_price: int,
        base_query: str,
        ground_type: str | None = None,
        size: str | None = None,
        exclude_keys: set[str] | None = None,
    ) -> list[Any]:
        del base_query
        started_at = time.perf_counter()
        docs = retrieve_analysis_documents_filtered(
            seller_display=normalize_seller_display(seller),
            product_keyword=product_keyword,
            min_price=min_price,
            max_price=max_price,
            # The sampled product title can contain a ground/size-like token
            # that is absent or differently normalized in stored metadata.
            # This benchmark's filter-compliance test is separate; keep this
            # agent E2E case focused on an indexed RAG response path.
            ground_type=None,
            size=None,
            exclude_keys=exclude_keys,
        )
        retrieval_latencies.append((time.perf_counter() - started_at) * 1000)
        return docs

    original_search = analysis_agent._crawl_and_search_seller
    analysis_agent._crawl_and_search_seller = indexed_search_only
    totals: list[float] = []
    response_lengths: list[int] = []
    document_counts: list[int] = []
    try:
        for _ in range(args.runs):
            started_at = time.perf_counter()
            result = await analysis_agent.product_analysis_agent(
                query=f"{case['product_name']} 비교 분석",
                conditions={"seller": case["seller"], "product_name": case["product_name"]},
                return_result=True,
            )
            totals.append((time.perf_counter() - started_at) * 1000)
            response_lengths.append(len(result.answer or ""))
            document_counts.append(len(result.docs))
    finally:
        analysis_agent._crawl_and_search_seller = original_search

    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "collection_document_count": vectorstore._collection.count(),
            "persist_directory": str(CHROMA_PERSIST_DIR),
            "runs": args.runs,
            "request_case": case,
            "crawler": "replaced by indexed Chroma retrieval",
            "executed_stages": ["metadata-filtered retrieval", "CRAG relevance grading", "answer generation", "Self-RAG groundedness grading"],
        },
        "important_interpretation": (
            "This is the indexed RAG agent E2E path, not HTTP/SSE or live crawling E2E. "
            "It uses the production product_analysis_agent and real LLM calls while excluding seller-site latency."
        ),
        "retrieval_stage": summarise(retrieval_latencies),
        "indexed_rag_agent_total": summarise(totals),
        "returned_document_counts": document_counts,
        "response_lengths": response_lengths,
    }
    output_path = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"indexed_rag_agent_e2e_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Indexed RAG agent E2E benchmark completed")
    print(f"  retrieval p50 / p95: {report['retrieval_stage']['p50_ms']}ms / {report['retrieval_stage']['p95_ms']}ms")
    print(f"  total p50 / p95: {report['indexed_rag_agent_total']['p50_ms']}ms / {report['indexed_rag_agent_total']['p95_ms']}ms")
    print(f"  report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main(parse_args())))
