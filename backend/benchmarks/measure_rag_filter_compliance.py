"""Compare condition compliance before and after metadata-filtered RAG retrieval.

Cases are sampled from the currently indexed Chroma product metadata, so the
script never needs a hand-maintained list that can become stale.  It compares
plain similarity search with `retrieve_analysis_documents_filtered` and writes
coverage and condition-compliance metrics to a JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@dataclass(frozen=True)
class GoldenCase:
    seller: str
    product_keyword: str
    min_price: int
    max_price: int
    ground_type: str | None
    size: str | None


def normalise(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def size_from_metadata(metadata: dict[str, Any]) -> str | None:
    size_text = str(metadata.get("size_text") or "")
    match = re.search(r"(?<!\d)(\d{3})(?!\d)", size_text)
    if not match:
        return None
    if metadata.get("size_min") is None or metadata.get("size_max") is None:
        return None
    return match.group(1)


def build_cases(metadatas: list[dict[str, Any]], limit: int) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    seen: set[tuple[str, str]] = set()
    for metadata in metadatas:
        seller = str(metadata.get("seller") or "").strip()
        product_name = str(metadata.get("product_name") or "").strip()
        try:
            price = int(metadata.get("product_price"))
        except (TypeError, ValueError):
            continue
        if not seller or not product_name or price <= 0:
            continue
        key = (seller, product_name)
        if key in seen:
            continue
        seen.add(key)
        margin = max(5_000, int(price * 0.1))
        cases.append(
            GoldenCase(
                seller=seller,
                product_keyword=product_name,
                min_price=max(0, price - margin),
                max_price=price + margin,
                ground_type=str(metadata.get("ground_type") or "").strip() or None,
                size=size_from_metadata(metadata),
            )
        )
        if len(cases) == limit:
            return cases
    return cases


def document_matches(document: Any, case: GoldenCase) -> bool:
    metadata = document.metadata or {}
    try:
        price = int(metadata.get("product_price"))
    except (TypeError, ValueError):
        return False
    if str(metadata.get("seller") or "").strip() != case.seller:
        return False
    if not case.min_price <= price <= case.max_price:
        return False
    if case.ground_type and str(metadata.get("ground_type") or "").upper() != case.ground_type.upper():
        return False
    if case.size:
        available_sizes = {part.strip() for part in str(metadata.get("size_text") or "").split(",")}
        if case.size not in available_sizes:
            return False
    requested_tokens = [token for token in normalise(case.product_keyword).split() if token]
    product_name = normalise(metadata.get("product_name"))
    return all(token in product_name for token in requested_tokens)


def metrics(results: list[list[Any]], cases: list[GoldenCase]) -> dict[str, Any]:
    document_count = sum(len(documents) for documents in results)
    matching_count = sum(
        1
        for documents, case in zip(results, cases)
        for document in documents
        if document_matches(document, case)
    )
    nonempty_cases = sum(bool(documents) for documents in results)
    fully_compliant_cases = sum(
        bool(documents) and all(document_matches(document, case) for document in documents)
        for documents, case in zip(results, cases)
    )
    return {
        "cases": len(cases),
        "nonempty_cases": nonempty_cases,
        "coverage": round(nonempty_cases / len(cases), 4) if cases else 0.0,
        "returned_documents": document_count,
        "matching_documents": matching_count,
        "document_condition_compliance": round(matching_count / document_count, 4) if document_count else 0.0,
        "fully_compliant_nonempty_cases": fully_compliant_cases,
        "case_condition_compliance": round(fully_compliant_cases / nonempty_cases, 4) if nonempty_cases else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure metadata-filtered RAG condition compliance.")
    parser.add_argument("--cases", type=int, default=20, help="Number of sampled metadata cases (default: 20).")
    parser.add_argument("--k", type=int, default=20, help="Candidate count for unfiltered similarity search.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.cases < 1 or args.k < 1:
        raise SystemExit("--cases and --k must be positive integers.")
    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required; no measurement was run.")

    from Tools.rag_search import retrieve_analysis_documents_filtered
    from Tools.vectorstore_singleton import CHROMA_PERSIST_DIR, vectorstore

    raw = vectorstore._collection.get(include=["metadatas"], limit=vectorstore._collection.count())
    cases = build_cases(raw.get("metadatas") or [], args.cases)
    if len(cases) < args.cases:
        raise SystemExit(f"Only {len(cases)} usable cases were found in the collection.")

    unfiltered_results = [
        vectorstore.similarity_search(case.product_keyword, k=args.k)
        for case in cases
    ]
    direct_filter_results = [
        retrieve_analysis_documents_filtered(
            seller_display=case.seller,
            product_keyword=case.product_keyword,
            min_price=case.min_price,
            max_price=case.max_price,
            ground_type=case.ground_type,
            size=case.size,
            limit=6,
        )
        for case in cases
    ]

    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "collection_document_count": vectorstore._collection.count(),
            "persist_directory": str(CHROMA_PERSIST_DIR),
            "case_generation": "Sampled from indexed product metadata; one case per seller/product pair.",
            "unfiltered_top_k": args.k,
            "cases": [asdict(case) for case in cases],
        },
        "important_interpretation": (
            "This evaluates structured-condition compliance, not semantic recommendation relevance. "
            "Empty direct-filter results count as coverage misses, not compliant answers."
        ),
        "unfiltered_similarity_search": metrics(unfiltered_results, cases),
        "metadata_direct_filter": metrics(direct_filter_results, cases),
    }
    output_path = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"rag_filter_compliance_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    unfiltered = report["unfiltered_similarity_search"]
    filtered = report["metadata_direct_filter"]
    print("RAG filter-compliance benchmark completed")
    print(f"  cases / indexed documents: {len(cases)} / {report['scope']['collection_document_count']}")
    print(
        "  unfiltered compliance: "
        f"documents={unfiltered['document_condition_compliance']:.1%}, "
        f"nonempty cases={unfiltered['case_condition_compliance']:.1%}"
    )
    print(
        "  direct-filter compliance: "
        f"documents={filtered['document_condition_compliance']:.1%}, "
        f"nonempty cases={filtered['case_condition_compliance']:.1%}, "
        f"coverage={filtered['coverage']:.1%}"
    )
    print(f"  report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
