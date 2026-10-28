"""Measure the retrieval latency impact of an in-memory embedding cache.

This script intentionally does not modify the running Buyer Agent. It opens
the same persisted Chroma collection twice: once with the production embedding
function and once with a small cache wrapper. That makes the report useful for
deciding whether the cache should be promoted into the service path.

Example (run from the backend directory):
    python benchmarks/measure_rag_embedding_cache.py --runs 15

The script needs OPENAI_API_KEY and an existing .chroma_store collection.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
from langchain_chroma import Chroma


DEFAULT_QUERIES = [
    "나이키 머큐리얼 FG 성인용",
    "크레이지11 30만원 이하 축구화",
    "사커붐 AG 축구화",
    "풋살화 TF 성인용",
    "아디다스 프레데터 주니어용",
]


class CachedEmbeddingFunction:
    """A transparent query-embedding cache used only by this benchmark."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._cache: dict[str, list[float]] = {}
        self.hits = 0
        self.misses = 0

    def clear(self) -> None:
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def embed_query(self, text: str) -> list[float]:
        cached = self._cache.get(text)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        vector = self._delegate.embed_query(text)
        self._cache[text] = vector
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Read-only benchmark, but this preserves the normal embedding API.
        return self._delegate.embed_documents(texts)


@dataclass(frozen=True)
class Sample:
    query: str
    elapsed_ms: float


def percentile(values: list[float], fraction: float) -> float:
    """Return an interpolated percentile without requiring a large sample."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a percentile from an empty sample.")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarise(samples: list[Sample]) -> dict[str, float | int]:
    latencies = [sample.elapsed_ms for sample in samples]
    return {
        "samples": len(latencies),
        "mean_ms": round(statistics.mean(latencies), 2),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "min_ms": round(min(latencies), 2),
        "max_ms": round(max(latencies), 2),
    }


def measure(search: Callable[[str], None], queries: list[str], runs: int) -> list[Sample]:
    samples: list[Sample] = []
    for query in queries:
        for _ in range(runs):
            started_at = time.perf_counter()
            search(query)
            samples.append(Sample(query=query, elapsed_ms=(time.perf_counter() - started_at) * 1000))
    return samples


def make_search(store: Chroma, k: int, metadata_filter: dict[str, Any] | None) -> Callable[[str], None]:
    def search(query: str) -> None:
        store.similarity_search(query, k=k, filter=metadata_filter)

    return search


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare uncached, cache-cold, and cache-warm Chroma retrieval latency."
    )
    parser.add_argument("--runs", type=int, default=10, help="Samples per query and mode (default: 10).")
    parser.add_argument("--k", type=int, default=5, help="Chroma top-k value (default: 5).")
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Query to benchmark. Specify multiple times to replace the default query set.",
    )
    parser.add_argument(
        "--filter-json",
        help='Optional Chroma metadata filter, for example: {"seller":{"$eq":"크레이지11"}}',
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path for the JSON report. Defaults to benchmarks/results/<timestamp>.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 2:
        raise SystemExit("--runs must be at least 2 so p95 is meaningful.")
    if args.k < 1:
        raise SystemExit("--k must be at least 1.")
    # The project keeps its optional local credentials in backend/.env. Loading
    # it here (rather than at import time) keeps `--help` usable without a key.
    load_dotenv(BACKEND_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is required; no measurement was run.")

    try:
        metadata_filter = json.loads(args.filter_json) if args.filter_json else None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--filter-json must be valid JSON: {exc}") from exc

    from Tools.vectorstore_singleton import CHROMA_PERSIST_DIR, _embedding, vectorstore

    document_count = vectorstore._collection.count()
    if document_count == 0:
        raise SystemExit(
            f"The Chroma collection is empty at {CHROMA_PERSIST_DIR}. "
            "Index product documents before running this benchmark."
        )

    queries = args.queries or DEFAULT_QUERIES
    cached_embeddings = CachedEmbeddingFunction(_embedding)
    cached_store = Chroma(
        embedding_function=cached_embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
        collection_name="soccer_shoes",
    )

    uncached_search = make_search(vectorstore, args.k, metadata_filter)
    cached_search = make_search(cached_store, args.k, metadata_filter)

    # Repeat the same queries deliberately: this is the request pattern for
    # which query-embedding caching can help.
    uncached_samples = measure(uncached_search, queries, args.runs)

    # Cache misses and hits are reported separately. The reset prevents the
    # cold sample from being influenced by the uncached baseline.
    cached_embeddings.clear()
    cold_samples = measure(cached_search, queries, 1)
    cold_hits = cached_embeddings.hits
    cold_misses = cached_embeddings.misses
    warm_samples = measure(cached_search, queries, args.runs)

    uncached_summary = summarise(uncached_samples)
    warm_summary = summarise(warm_samples)
    improvement = uncached_summary["mean_ms"] / warm_summary["mean_ms"]
    warm_hits = cached_embeddings.hits - cold_hits
    warm_misses = cached_embeddings.misses - cold_misses
    warm_total = warm_hits + warm_misses

    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "collection": "soccer_shoes",
            "collection_document_count": document_count,
            "persist_directory": str(CHROMA_PERSIST_DIR),
            "queries": queries,
            "top_k": args.k,
            "metadata_filter": metadata_filter,
            "runs_per_query": args.runs,
        },
        "important_interpretation": (
            "This is retrieval-only latency. It excludes crawling, LangGraph orchestration, "
            "CRAG/Self-RAG grading, answer generation, and network/UI overhead. "
            "The warm-cache figure applies only to exact repeated queries within one process."
        ),
        "uncached_retrieval": uncached_summary,
        "cache_cold_retrieval": summarise(cold_samples),
        "cache_warm_retrieval": warm_summary,
        "cache": {
            "cold": {"hits": cold_hits, "misses": cold_misses},
            "warm": {
                "hits": warm_hits,
                "misses": warm_misses,
                "hit_rate": round(warm_hits / warm_total, 4) if warm_total else 0.0,
            },
        },
        "mean_speedup_uncached_to_warm": round(improvement, 2),
    }

    output_path = args.output or (
        Path(__file__).resolve().parent
        / "results"
        / f"rag_embedding_cache_{datetime.now().strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("RAG embedding-cache benchmark completed")
    print(f"  documents: {document_count:,}")
    print(f"  uncached mean / p95: {uncached_summary['mean_ms']}ms / {uncached_summary['p95_ms']}ms")
    print(f"  cache cold mean: {report['cache_cold_retrieval']['mean_ms']}ms")
    print(f"  cache warm mean / p95: {warm_summary['mean_ms']}ms / {warm_summary['p95_ms']}ms")
    print(f"  warm-cache speedup: {report['mean_speedup_uncached_to_warm']}x")
    print(f"  warm-cache hit rate: {report['cache']['warm']['hit_rate']:.1%}")
    print(f"  report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
