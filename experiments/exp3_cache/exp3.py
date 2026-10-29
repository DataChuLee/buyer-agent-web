"""실험 3: 크롤·인덱싱 캐시(crawl_registry) 재측정.

  python experiments/exp3_cache/exp3.py run [--reps 2] [--out results.jsonl]
  python experiments/exp3_cache/exp3.py report [--inp results.jsonl]

기존 벤치마크(benchmarks/measure_crawl_index_cache.py)의 한계를 보완한다.
- 표본: 판매처 1곳 x 키워드 1개 x 3회 → 판매처 4곳 x 키워드 3개 x reps회
- 범위: 크롤 도구 시간만 → 사용자가 기다리는 분석 응답 전체(product_analysis_agent: 크롤+검색+생성)와
  그 안의 크롤 단계 시간을 함께 기록
- 정합성: hit 응답이 miss 응답과 같은 문서를 쓰는지 확인
- 서비스 캐시를 건드리지 않도록 레지스트리는 매 쌍마다 비운 임시 파일을 쓴다. miss는 실제 크롤링을 하고 로컬 Chroma에
  upsert하므로, 실행 전 .chroma_store를 백업하고 끝나면 복원한다(실험 1·2 재현성 유지).
"""
import argparse
import asyncio
import json
import random
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments/exp1_selfquery"))
from exp1 import bootstrap_ci, percentile  # noqa: E402

SELLERS = {"crazy11": "크레이지11", "soccerboom": "사커붐", "redsoccer": "레드사커", "cafostore": "카포스토어"}
KEYWORDS = ["머큐리얼", "프레데터", "팬텀"]  # 평가 질문에 자주 나오는 시리즈


async def one_call(pa, seller, keyword):
    crawl_ms = []
    orig = pa.crawl_and_index

    class TimedCrawl:
        async def ainvoke(self, payload):
            t = time.perf_counter()
            out = await orig.ainvoke(payload)
            crawl_ms.append((time.perf_counter() - t) * 1000)
            return out

    with patch.object(pa, "crawl_and_index", TimedCrawl()):
        t0 = time.perf_counter()
        result = await pa.product_analysis_agent(
            f"{SELLERS[seller]}에서 {keyword} 보여줘",
            conditions={"product_name": keyword, "seller": seller}, return_result=True)
        total = (time.perf_counter() - t0) * 1000
    keys = sorted(f"{d.metadata.get('seller')}|{d.metadata.get('product_name')}" for d in result.docs)
    return {"total_ms": total, "crawl_ms": sum(crawl_ms), "crawl_calls": len(crawl_ms), "doc_keys": keys,
            "answer_has_table": "🔗" in result.answer}


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    import Agent.product_analysis_agent as pa
    import Tools.crawl_registry as reg
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    sellers = args.sellers.split(",") if args.sellers else list(SELLERS)
    pairs = [(s, k, r) for s in sellers for k in KEYWORDS for r in range(args.reps)]
    random.Random(7).shuffle(pairs)

    async def main():
        original = reg._REGISTRY_PATH
        with tempfile.TemporaryDirectory(prefix="exp3_registry_") as tmp, open(HERE / args.out, "w", encoding="utf-8") as f:
            try:
                for i, (seller, keyword, rep) in enumerate(pairs, 1):
                    reg._REGISTRY_PATH = str(Path(tmp) / f"registry_{i}.json")  # 쌍마다 빈 캐시 → miss 보장
                    miss = await one_call(pa, seller, keyword)
                    registered = reg.is_already_indexed([seller], keyword, 0, 999999)
                    hit = await one_call(pa, seller, keyword)
                    row = {"seller": seller, "keyword": keyword, "rep": rep, "registered_after_miss": registered,
                           "miss": miss, "hit": hit, "same_docs": miss["doc_keys"] == hit["doc_keys"],
                           "commit": commit, "at": datetime.now(timezone.utc).isoformat()}
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    print(f"[{i}/{len(pairs)}] {seller} {keyword} miss={miss['total_ms']:.0f}ms (crawl {miss['crawl_ms']:.0f}) "
                          f"hit={hit['total_ms']:.0f}ms (crawl {hit['crawl_ms']:.0f}) docs={len(miss['doc_keys'])} same={row['same_docs']}",
                          flush=True)
            finally:
                reg._REGISTRY_PATH = original

    asyncio.run(main())


def stats(label, values):
    lo50, hi50 = bootstrap_ci(values, .5)
    print(f"  {label}: p50 {percentile(values, .5):.0f}ms (CI {lo50:.0f}~{hi50:.0f}), p95 {percentile(values, .95):.0f}ms, "
          f"min {min(values):.0f} / max {max(values):.0f}")


def cmd_report(args):
    rows = [json.loads(l) for name in args.inp.split(",") for l in open(HERE / name, encoding="utf-8")]
    valid = [r for r in rows if r["registered_after_miss"]]
    print(f"pairs={len(rows)} (캐시 등록 성공 {len(valid)}), commit={rows[0]['commit']}")
    print("[miss: 실제 크롤링]")
    stats("응답 전체", [r["miss"]["total_ms"] for r in valid])
    stats("크롤 단계", [r["miss"]["crawl_ms"] for r in valid])
    stats("크롤 제외 나머지", [r["miss"]["total_ms"] - r["miss"]["crawl_ms"] for r in valid])
    print("[hit: 캐시]")
    stats("응답 전체", [r["hit"]["total_ms"] for r in valid])
    stats("크롤 단계(레지스트리 확인)", [r["hit"]["crawl_ms"] for r in valid])
    ratio = [r["hit"]["total_ms"] / r["miss"]["total_ms"] for r in valid]
    print(f"  쌍별 응답 시간 감소율 중앙값 {1 - statistics.median(ratio):.1%} (최소 {1 - max(ratio):.1%}, 최대 {1 - min(ratio):.1%})")
    print(f"  hit가 miss와 같은 문서를 쓴 쌍 {sum(r['same_docs'] for r in valid)}/{len(valid)}")
    print(f"  결과 문서 0개인 쌍(miss) {sum(not r['miss']['doc_keys'] for r in valid)}/{len(valid)}")
    by_seller = {}
    for r in valid:
        by_seller.setdefault(r["seller"], []).append(r["miss"]["crawl_ms"])
    print("  판매처별 miss 크롤 p50: " + ", ".join(f"{s} {percentile(v, .5):.0f}ms(n={len(v)})" for s, v in by_seller.items()))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--out", default="results.jsonl")
    r.add_argument("--sellers", default=None, help="쉼표 구분(예: crazy11,redsoccer). 기본은 4곳 전부")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="results.jsonl", help="쉼표로 여러 파일을 합쳐 볼 수 있음")
    a = p.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)
