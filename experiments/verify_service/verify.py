"""반영한 서비스 코드(프롬프트 v2 + 결정적 검사 + 가격 범위 전달)를 실험 2/2-b와 같은 조건으로 검증한다.

  python experiments/verify_service/verify.py run [--reps 2] [--limit N] [--live] [--out results.jsonl]
  python experiments/verify_service/verify.py judge [--inp results.jsonl] [--out judged.jsonl]
  python experiments/verify_service/verify.py report [--inp judged.jsonl]

- 서비스 함수(product_analysis_agent)를 그대로 호출한다. 기본은 크롤링만 막고(로컬 Chroma), --live면 실제 크롤링까지 한다.
- 채점·판정은 exp2.py와 동일. '정답 문서가 있는데 상품을 하나도 안 보여준 실행'을 함께 센다.
"""
import argparse
import asyncio
import json
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments/exp2_graders"))
import exp2  # noqa: E402
from exp1 import bootstrap_ci, complies, load_questions, percentile, wilson  # noqa: E402


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    import Agent.product_analysis_agent as pa
    from Tools.rag_search import _ANSWER_PROMPT, format_docs
    questions = load_questions()[: args.limit]
    if args.questions:  # 과적합 확인용 새 질문 세트
        import csv
        questions = [dict(r, min_price=int(r["min_price"]), max_price=int(r["max_price"]))
                     for r in csv.DictReader(open(ROOT / args.questions, encoding="utf-8-sig"))][: args.limit]
    if args.live:
        questions = questions[::6]  # 실제 크롤링은 느리므로 고정 규칙(6번째마다)으로 5문항만
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "backend"], capture_output=True, text=True).stdout.strip())

    class NoCrawl:
        async def ainvoke(self, _):
            return None

    async def call(q):
        gens = []
        orig = pa._generate_answer

        async def counted(context, messages):
            gens.append(1)
            return await orig(context, messages)

        crawl = patch.object(pa, "crawl_and_index", pa.crawl_and_index if args.live else NoCrawl())
        with crawl, patch.object(pa, "_generate_answer", counted):
            t0 = time.perf_counter()
            result = await pa.product_analysis_agent(q["question"], conditions=exp2.conditions_for(q), return_result=True)
            return result, (time.perf_counter() - t0) * 1000, len(gens)

    async def main():
        if not args.live:
            await call(questions[0])  # 예열, 결과에서 제외
        jobs = [(q, r) for q in questions for r in range(args.reps)]
        random.Random(7).shuffle(jobs)
        with open(HERE / args.out, "w", encoding="utf-8") as f:
            for i, (q, rep) in enumerate(jobs, 1):
                result, ms, n_gen = await call(q)
                row = {"id": q["id"], "arm": "live" if args.live else "service", "rep": rep, "total_ms": ms, "generations": n_gen,
                       "has_gold_in_context": any(all(complies(d.metadata, q).values()) for d in result.docs),
                       **exp2.deterministic_scores(result.answer, result.docs, q),
                       "answer": result.answer, "context": [format_docs([d]) for d in result.docs],
                       "context_meta": [d.metadata for d in result.docs],
                       "prompt_version": _ANSWER_PROMPT["version"], "model": exp2.GEN_MODEL,
                       "commit": commit + ("+dirty" if dirty else ""), "at": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{i}/{len(jobs)}] {q['id']} {ms:.0f}ms ctx={row['context_docs']} shown={row['n_shown_products']} gen={n_gen}", flush=True)

    asyncio.run(main())


def cmd_judge(args):
    exp2.cmd_judge(argparse.Namespace(inp=str(HERE / args.inp), out=str(HERE / args.out), human_out=str(HERE / "human_check.csv")))


def cmd_report(args):
    rs = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    ctx = [r for r in rs if r["context_docs"]]
    lat = [r["total_ms"] for r in rs]
    print(f"runs={len(rs)} arm={rs[0]['arm']} commit={rs[0]['commit']} prompt_version={rs[0]['prompt_version']} "
          f"gen={rs[0]['model']} judge={rs[0].get('judge_model', '-')}")
    print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
          f"p95 {percentile(lat, .95):.0f}ms (CI {bootstrap_ci(lat, .95)[0]:.0f}~{bootstrap_ci(lat, .95)[1]:.0f})")
    print(f"  실행당 LLM 호출(생성) 평균 {statistics.mean(r['generations'] for r in rs):.2f}회, 재생성 {sum(r['generations'] > 1 for r in rs)}/{len(rs)}")
    print(f"  결과 없음으로 끝난 실행 {len(rs) - len(ctx)}/{len(rs)}")
    missed = sum(r["has_gold_in_context"] and r["n_shown_products"] == 0 for r in rs)
    print(f"  정답 문서가 있는데 상품을 하나도 안 보여준 실행 {missed}/{len(rs)}")
    for label, k, n in [("생성 문서 중 조건 불만족", "context_noncompliant", "context_docs"),
                        ("보여준 상품 중 조건 불만족", "shown_noncompliant", "n_shown_products"),
                        ("답변 링크 중 문서에 없음", "urls_not_in_docs", "n_urls"),
                        ("답변 가격 중 문서에 없음", "prices_not_in_docs", "n_prices")]:
        a, b = sum(r[k] for r in ctx), sum(r[n] for r in ctx)
        lo, hi = wilson(a, b)
        print(f"  {label}: {a}/{b} = {a / max(b, 1):.1%}  95%CI {lo:.1%}~{hi:.1%}")
    print(f"  보여준 상품 수 합계 {sum(r['n_shown_products'] for r in rs)}")
    if "judge_unsupported" in rs[0]:
        counts = [len(r["judge_unsupported"]) for r in ctx]
        lo, hi = exp2.mean_ci(counts)
        print(f"  LLM 판정: 답변당 근거 없는 주장 평균 {statistics.mean(counts):.2f}개 95%CI {lo:.2f}~{hi:.2f}, "
              f"1개 이상인 답변 {sum(c > 0 for c in counts)}/{len(counts)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--live", action="store_true")
    r.add_argument("--questions", default=None, help="저장소 루트 기준 질문 CSV 경로")
    r.add_argument("--out", default="results.jsonl")
    j = sub.add_parser("judge")
    j.add_argument("--inp", default="results.jsonl")
    j.add_argument("--out", default="judged.jsonl")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="judged.jsonl")
    a = p.parse_args()
    {"run": cmd_run, "judge": cmd_judge, "report": cmd_report}[a.cmd](a)
