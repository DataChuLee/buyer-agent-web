"""Diagnose filter values passed by the Product Analysis RAG path.

This script deliberately performs no crawling and no LLM generation.  It makes
the same seller/product/price/ground/size decisions as ``product_analysis_agent``
and writes the exact Chroma retrieval result for those values.  It exists to
keep an E2E benchmark from silently measuring the agent's early no-result path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _case_from_report(path: Path) -> dict[str, str]:
    report = json.loads(path.read_text(encoding="utf-8"))
    case = report.get("scope", {}).get("request_case")
    if not isinstance(case, dict) or not case.get("seller") or not case.get("product_name"):
        raise SystemExit("--case-report must contain scope.request_case.seller and product_name.")
    return {"seller": str(case["seller"]), "product_name": str(case["product_name"])}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose Product Analysis RAG filter alignment.")
    parser.add_argument("--case-report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def document_summary(doc: Any) -> dict[str, Any]:
    metadata = doc.metadata or {}
    return {
        "seller": metadata.get("seller"),
        "product_name": metadata.get("product_name"),
        "product_price": metadata.get("product_price"),
        "ground_type": metadata.get("ground_type"),
        "size_text": metadata.get("size_text"),
        "product_url": metadata.get("product_url"),
    }


def main(args: argparse.Namespace) -> int:
    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required because Chroma query embeddings are live.")

    import Agent.product_analysis_agent as analysis_agent
    from Tools.rag_search import RagRetrievalError, retrieve_analysis_documents_filtered
    from Tools.seller_normalization import normalize_seller_display

    case = _case_from_report(args.case_report)
    query = f"{case['product_name']} 비교 분석"
    conditions = {"seller": case["seller"], "product_name": case["product_name"]}
    crawl_query_text = " ".join([query, *conditions.values()])
    min_price, max_price = analysis_agent._extract_price_range(crawl_query_text)
    sellers = analysis_agent._extract_sellers(query, conditions)
    product_keyword = analysis_agent._extract_product_keyword(query, conditions)
    ground_type = analysis_agent._extract_ground_type(query, conditions)
    size = analysis_agent._extract_size(query, conditions)

    seller_results: list[dict[str, Any]] = []
    for seller in sellers:
        seller_display = normalize_seller_display(seller)
        try:
            strict_docs = retrieve_analysis_documents_filtered(
                seller_display=seller_display,
                product_keyword=product_keyword,
                min_price=min_price,
                max_price=max_price,
                ground_type=ground_type,
                size=size,
            )
            strict_error = None
        except RagRetrievalError as exc:
            strict_docs = []
            strict_error = {"type": type(exc.__cause__).__name__, "message": str(exc.__cause__)}
        try:
            without_optional_docs = retrieve_analysis_documents_filtered(
                seller_display=seller_display,
                product_keyword=product_keyword,
                min_price=min_price,
                max_price=max_price,
            )
            without_optional_error = None
        except RagRetrievalError as exc:
            without_optional_docs = []
            without_optional_error = {"type": type(exc.__cause__).__name__, "message": str(exc.__cause__)}
        seller_results.append(
            {
                "crawler_seller": seller,
                "seller_display_filter": seller_display,
                "strict_filter_document_count": len(strict_docs),
                "strict_filter_documents": [document_summary(doc) for doc in strict_docs],
                "strict_filter_error": strict_error,
                "without_ground_or_size_document_count": len(without_optional_docs),
                "without_ground_or_size_documents": [document_summary(doc) for doc in without_optional_docs],
                "without_ground_or_size_error": without_optional_error,
            }
        )

    report = {
        "diagnosed_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "indexed Chroma retrieval only; no crawl and no LLM generation",
        "input_case": case,
        "agent_derived_filters": {
            "query": query,
            "conditions": conditions,
            "sellers": sellers,
            "product_keyword": product_keyword,
            "min_price": min_price,
            "max_price": max_price,
            "ground_type": ground_type,
            "size": size,
        },
        "seller_results": seller_results,
    }
    output = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"product_analysis_filter_alignment_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Filter-alignment diagnostic completed: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(parse_args()))
