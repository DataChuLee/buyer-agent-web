"""실험 3-b: 판매처 장애 중 실패 캐시(negative cache) 효과 — 장애 주입 측정.

  python experiments/exp3_cache/exp3b_negative.py run [--out negative.jsonl]
  python experiments/exp3_cache/exp3b_negative.py report [--inp negative.jsonl]

- 장애 재현: 실제 사이트 장애를 일부러 만들 수 없어, 크롤러(crawl_multiple_sellers)를 '실험 3에서 실제로 관측한
  타임아웃 시간(results.jsonl의 등록 실패 크롤 시간 중앙값)만큼 기다린 뒤 실패'하도록 바꿔 끼운다.
- before: 실패 캐시 끔(recently_failed 항상 False) / after: 현재 서비스 그대로.
- 시나리오: 판매처 1곳이 다운된 동안 같은 사용자가 시리즈를 바꿔가며 연속 6번 분석 요청(판매처 2곳 각각).
  검색·답변 생성은 실제로 실행하고 응답 전체 시간을 잰다. 성공 캐시는 매 요청 비운 임시 레지스트리로 꺼 둔다.
"""
import argparse
import asyncio
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments/exp1_selfquery"))
from exp1 import bootstrap_ci, percentile  # noqa: E402

DOWN_SELLERS = {"crazy11": "크레이지11", "redsoccer": "레드사커"}
REQUESTS = ["머큐리얼", "프레데터", "팬텀", "머큐리얼", "프레데터", "팬텀"]


def observed_timeout_ms():
    rows = [json.loads(l) for l in open(HERE / "results.jsonl", encoding="utf-8")]
    failed = [r[side]["crawl_ms"] for r in rows if not r["registered_after_miss"] for side in ("miss", "hit")]
    assert failed, "실험 3에서 관측된 크롤 실패가 없음"
    return statistics.median(failed), len(failed)


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    import Agent.product_analysis_agent as pa
    import Tools.crawl_registry as reg
    timeout_ms, n_obs = observed_timeout_ms()
    print(f"주입할 장애 시간 {timeout_ms:.0f}ms (실험 3 실패 크롤 {n_obs}건 중앙값)")

    async def failing_crawl(sellers, **_):
        await asyncio.sleep(timeout_ms / 1000)
        return {"items": [], "errors": {s: "TimeoutError (장애 주입)" for s in sellers}}

    async def main():
        with tempfile.TemporaryDirectory() as tmp, open(HERE / args.out, "w", encoding="utf-8") as f:
            for arm in ("before", "after"):
                for seller, display in DOWN_SELLERS.items():
                    reg._recent_failures.clear()
                    for i, keyword in enumerate(REQUESTS):
                        reg._REGISTRY_PATH = str(Path(tmp) / f"{arm}_{seller}_{i}.json")  # 성공 캐시는 끈 상태
                        patches = [patch("Crawling.seller_total_test.crawl_multiple_sellers", failing_crawl)]
                        if arm == "before":
                            patches.append(patch("Tools.crawl_and_index.recently_failed", lambda s: False))
                        for p in patches:
                            p.start()
                        try:
                            t0 = time.perf_counter()
                            result = await pa.product_analysis_agent(
                                f"{display}에서 {keyword} 보여줘",
                                conditions={"product_name": keyword, "seller": seller}, return_result=True)
                            ms = (time.perf_counter() - t0) * 1000
                        finally:
                            for p in reversed(patches):
                                p.stop()
                        row = {"arm": arm, "seller": seller, "request_index": i, "keyword": keyword, "total_ms": ms,
                               "docs": len(result.docs), "injected_timeout_ms": timeout_ms}
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                        f.flush()
                        print(f"{arm} {seller} #{i + 1} {keyword} {ms:.0f}ms docs={len(result.docs)}", flush=True)

    asyncio.run(main())


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    print(f"주입한 장애 시간 {rows[0]['injected_timeout_ms']:.0f}ms, 판매처 {len(DOWN_SELLERS)}곳 x 연속 요청 {len(REQUESTS)}번")
    for arm in ("before", "after"):
        rs = [r for r in rows if r["arm"] == arm]
        first = [r["total_ms"] for r in rs if r["request_index"] == 0]
        later = [r["total_ms"] for r in rs if r["request_index"] > 0]
        print(f"[{arm}] 첫 요청 평균 {statistics.mean(first):.0f}ms (n={len(first)}) | "
              f"이후 요청 p50 {percentile(later, .5):.0f}ms (CI {bootstrap_ci(later, .5)[0]:.0f}~{bootstrap_ci(later, .5)[1]:.0f}), "
              f"p95 {percentile(later, .95):.0f}ms (n={len(later)}) | 결과 문서 0개 {sum(r['docs'] == 0 for r in rs)}/{len(rs)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default="negative.jsonl")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="negative.jsonl")
    a = p.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)
