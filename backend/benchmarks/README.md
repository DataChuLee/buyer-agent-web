# RAG Benchmarks

`measure_rag_embedding_cache.py` measures the retrieval-only effect of an
in-memory query-embedding cache against the project's persisted Chroma
collection. It does not mutate the collection or change the running service.

Run it from `backend/` after setting `OPENAI_API_KEY` and indexing documents:

```powershell
venv\Scripts\python.exe benchmarks\measure_rag_embedding_cache.py --runs 15
```

The output JSON is written to `benchmarks/results/` (gitignored). Keep the
report when writing a portfolio, and record its collection size, query set,
sample count, mean, p50, p95, and cache hit rate.

Interpret the result carefully:

- The uncached and warm-cache paths use the same Chroma collection and `top-k`.
- The warm-cache result only applies to exact repeated queries in one process.
- It excludes crawling, agent orchestration, LLM grading/generation, and UI
  streaming; do not describe it as end-to-end chat latency.
- The benchmark wrapper is deliberately isolated from production. Promote a
  cache into `Tools/vectorstore_singleton.py` only after reviewing cache size,
  eviction, TTL, and multi-worker behaviour.

## Condition compliance

`measure_rag_filter_compliance.py` samples indexed product metadata and
compares plain similarity search against the production metadata-filtered
retrieval path. It reports condition compliance and result coverage separately:

```powershell
venv\Scripts\python.exe benchmarks\measure_rag_filter_compliance.py --cases 20
```

This is a structured-filter test, not a semantic-relevance evaluation. A later
human-labelled golden set is needed to claim recommendation relevance.

## Indexed RAG Agent E2E

`measure_indexed_rag_agent_e2e.py` runs the production Product Analysis Agent
with real LLM calls and already indexed product data. It measures metadata
retrieval, CRAG relevance grading, answer generation, and Self-RAG grounding,
while replacing live seller crawling with Chroma retrieval:

```powershell
venv\Scripts\python.exe benchmarks\measure_indexed_rag_agent_e2e.py --runs 5
```

If a one-run diagnosis has already found a retrievable case, reuse it to avoid
repeating discovery calls:

```powershell
venv\Scripts\python.exe benchmarks\measure_indexed_rag_agent_e2e.py --runs 5 `
  --case-report benchmarks\results\indexed_rag_agent_e2e_<timestamp>.json
```

This is the appropriate RAG E2E metric when live crawl latency would make
results non-repeatable. It is not HTTP/SSE or live-crawling E2E.

## Crawl-and-index cache

`measure_crawl_index_cache.py` measures the production `crawl_and_index`
tool's 24-hour crawl registry. Each sample intentionally runs one live
cache-miss call and then the exact same cache-hit call. The registry file is
temporary, so the benchmark does not change or depend on existing cache
entries; the miss path may upsert freshly crawled documents into the production
Chroma collection, exactly as the service does.

```powershell
venv\Scripts\python.exe benchmarks\measure_crawl_index_cache.py --runs 3
```

The result is stage latency, not full chat E2E: it includes live crawling and
Chroma upsert on the miss path, while the hit path skips both. It excludes
LangGraph, RAG retrieval, LLM grading/generation, and HTTP/SSE. Seller sites
are externally variable, so use p50/p95 from the same request and environment.

## API streaming end-to-end latency

Start the API with warm-up disabled in one terminal, then run the benchmark in
another terminal. Use a fixed prompt and record cache hit/miss state separately.

```powershell
$env:WARMUP_DISABLED = "1"
venv\Scripts\python.exe -m uvicorn FastAPI.main:app --port 8000

venv\Scripts\python.exe benchmarks\measure_chat_stream_e2e.py `
  --message "크레이지11에서 머큐리얼 베이퍼 TF 20만원 이하를 비교해줘" --runs 10
```

`first_sse_event` is progress-feedback latency; it must not be labelled TTFT
unless the endpoint actually emits an LLM token for that request type.

Use `--runs 1` only to diagnose a new prompt. For portfolio metrics, use a
stable successful prompt with at least 5 runs; a failed run still writes a JSON
diagnostic report rather than silently discarding the server error.

On Windows, Psycopg requires a selector event loop. Use the included loop
factory when starting uvicorn manually:

```powershell
venv\Scripts\python.exe -m uvicorn FastAPI.main:app --port 8000 `
  --loop FastAPI.loop_factory:selector_loop_factory
```

Alternatively, the benchmark can create and tear down the local server itself:

```powershell
venv\Scripts\python.exe benchmarks\measure_chat_stream_e2e.py `
  --start-local-server --in-memory-state --message "안녕" --runs 5
```

`--in-memory-state` is for measuring the local API/agent/SSE path when a
Supabase connection is unavailable. The report records this scope, so it must
not be presented as a database-persistence benchmark.
