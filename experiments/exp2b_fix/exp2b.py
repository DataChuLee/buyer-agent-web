"""실험 2-b: 채점 단계 대신 원인(생성 프롬프트)을 고치면 나아지는가.

  python experiments/exp2b_fix/exp2b.py run [--reps 2] [--limit N]
  python experiments/exp2b_fix/exp2b.py judge
  python experiments/exp2b_fix/exp2b.py report

- A: 현재 서비스 그대로(CRAG + Self-RAG, 원래 생성 프롬프트)
- B: 채점 단계 없음 + 생성 프롬프트의 '기능 키워드 2개↑' 한 줄만 '문서에 있는 지면/연령만'으로 교체
- C: B + 결정적 규칙(CRAG 자리: 비축구화 상품명 제외 / Self-RAG 자리: 답변 가격·URL이 문서에 있는지 코드로 검사,
     실패하면 서비스와 같은 강화 지시로 1회 재생성)
- 서비스 코드는 고치지 않는다. 같은 훅(grade_docs_relevance 등)을 patch로 바꿔 끼운다.
- 질문·크롤링 차단·채점·판정은 실험 2와 동일(exp2.py 함수 재사용).
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
import exp2  # noqa: E402  (exp1 경로 설정·통계 함수 포함)
from exp1 import complies, exact_binomial_two_sided, load_questions, percentile, bootstrap_ci, wilson  # noqa: E402

ARMS = ("A", "B", "C")
ORIG_FEATURE_LINE = "- 주요 특징: ground_type 해석 + age_group + 기능 키워드 2개↑"
FIXED_FEATURE_LINE = ("- 주요 특징: Context에 있는 지면(ground_type)과 연령대(age_group)만 적으세요. "
                      "Context에 없는 기능·소재·착용감·성능 표현은 쓰지 마세요")
NON_SHOE = ("장갑", "글러브", "축구공")


def fixed_generate():
    """Tools/rag_search._generate_answer와 같은 프롬프트에서 '주요 특징' 한 줄만 바꾼 버전."""
    import inspect
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    import Tools.rag_search as rs

    src = inspect.getsource(rs._generate_answer)
    start = src.index('"""') + 3
    system = src[start: src.index('"""', start)]
    assert ORIG_FEATURE_LINE in system, "서비스 프롬프트가 바뀌었음: 실험 전제 재확인 필요"
    system = system.replace(ORIG_FEATURE_LINE, FIXED_FEATURE_LINE)
    chain = ChatPromptTemplate.from_messages([("system", system), MessagesPlaceholder("messages")]) | rs.model | StrOutputParser()

    async def gen(context, messages):
        return await chain.ainvoke({"context": context, "messages": messages})
    return gen


def code_grounded(answer, docs):
    """답변 속 가격·URL이 모두 문서에 있으면 True (exp2의 결정적 채점과 같은 규칙)."""
    q = {"seller": "", "series": "", "ground_type": "", "min_price": 0, "max_price": 999999}
    s = exp2.deterministic_scores(answer, docs, q)
    return s["prices_not_in_docs"] == 0 and s["urls_not_in_docs"] == 0


async def run_one(q, arm, gen_fixed):
    import Agent.product_analysis_agent as pa

    log = {"grader_in": 0, "grader_out": 0, "llm_grader_calls": 0, "rewrites": 0, "generations": 0, "ground_verdicts": []}
    orig_grade, orig_ground, orig_rewrite, orig_gen = (
        pa.grade_docs_relevance, pa.grade_answer_groundedness, pa.rewrite_analysis_query, pa._generate_answer)
    dropped = []

    async def grade(query, docs):
        log["grader_in"] += len(docs)
        if arm == "A":
            log["llm_grader_calls"] += 1
            out = await orig_grade(query, docs)
        elif arm == "C":
            out = [d for d in docs if not any(k in str(d.metadata.get("product_name", "")) for k in NON_SHOE)]
        else:
            out = docs
        log["grader_out"] += len(out)
        dropped.extend(d.metadata for d in docs if d not in out)
        return out

    async def ground(answer, docs):
        if arm == "A":
            log["llm_grader_calls"] += 1
            verdict = await orig_ground(answer, docs)
        elif arm == "C":
            verdict = code_grounded(answer, docs)
        else:
            verdict = True
        log["ground_verdicts"].append(verdict)
        return verdict

    async def rewrite(query, conditions=None):
        log["rewrites"] += 1
        return await orig_rewrite(query, conditions)

    async def gen(context, messages):
        log["generations"] += 1
        return await (orig_gen if arm == "A" else gen_fixed)(context, messages)

    class NoCrawl:
        async def ainvoke(self, _):
            return None

    with patch.object(pa, "crawl_and_index", NoCrawl()), patch.object(pa, "grade_docs_relevance", grade), \
            patch.object(pa, "grade_answer_groundedness", ground), patch.object(pa, "rewrite_analysis_query", rewrite), \
            patch.object(pa, "_generate_answer", gen):
        t0 = time.perf_counter()
        result = await pa.product_analysis_agent(q["question"], conditions=exp2.conditions_for(q), return_result=True)
        ms = (time.perf_counter() - t0) * 1000
    return result, ms, log, dropped


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from Tools.rag_search import format_docs
    questions = load_questions()[: args.limit]
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    async def main():
        gen_fixed = fixed_generate()
        for arm in ARMS:  # 예열, 결과에서 제외
            await run_one(questions[0], arm, gen_fixed)
        jobs = [(q, arm, r) for q in questions for arm in ARMS for r in range(args.reps)]
        random.Random(7).shuffle(jobs)
        with open(HERE / args.out, "w", encoding="utf-8") as f:
            for i, (q, arm, rep) in enumerate(jobs, 1):
                result, ms, log, dropped = await run_one(q, arm, gen_fixed)
                row = {"id": q["id"], "arm": arm, "rep": rep, "total_ms": ms, **log,
                       "dropped_compliant": sum(all(complies(m, q).values()) for m in dropped),
                       "dropped_noncompliant": sum(not all(complies(m, q).values()) for m in dropped),
                       **exp2.deterministic_scores(result.answer, result.docs, q),
                       "answer": result.answer, "context": [format_docs([d]) for d in result.docs],
                       "context_meta": [d.metadata for d in result.docs],
                       "model": exp2.GEN_MODEL, "commit": commit, "at": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{i}/{len(jobs)}] {q['id']} {arm} {ms:.0f}ms ctx={row['context_docs']} shown={row['n_shown_products']} "
                      f"regen={log['generations'] - 1}", flush=True)

    asyncio.run(main())


def cmd_judge(args):
    exp2.cmd_judge(argparse.Namespace(inp=str(HERE / args.inp), out=str(HERE / args.out),
                                      human_out=str(HERE / "human_check.csv")))


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    by = {a: [r for r in rows if r["arm"] == a] for a in ARMS}
    print(f"runs: " + ", ".join(f"{a}={len(v)}" for a, v in by.items()) +
          f", commit={rows[0]['commit']}, gen={rows[0]['model']}, judge={rows[0].get('judge_model', '-')}")
    per_q = {}
    for arm, rs in by.items():
        ctx = [r for r in rs if r["context_docs"]]
        lat = [r["total_ms"] for r in rs]
        print(f"\n[{arm}]")
        print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
              f"p95 {percentile(lat, .95):.0f}ms (CI {bootstrap_ci(lat, .95)[0]:.0f}~{bootstrap_ci(lat, .95)[1]:.0f})")
        calls = [r["generations"] + r["llm_grader_calls"] + r["rewrites"] for r in rs]
        print(f"  실행당 LLM 호출 평균 {statistics.mean(calls):.2f}회")
        print(f"  결과 없음으로 끝난 실행 {len(rs) - len(ctx)}/{len(rs)}")
        for label, k, n in [("생성 문서 중 조건 불만족", "context_noncompliant", "context_docs"),
                            ("보여준 상품 중 조건 불만족", "shown_noncompliant", "n_shown_products"),
                            ("문서 중 답변에 보여준 비율", "n_shown_products", "context_docs"),
                            ("답변 링크 중 문서에 없음", "urls_not_in_docs", "n_urls"),
                            ("답변 가격 중 문서에 없음", "prices_not_in_docs", "n_prices")]:
            a, b = sum(r[k] for r in ctx), sum(r[n] for r in ctx)
            lo, hi = wilson(a, b)
            print(f"  {label}: {a}/{b} = {a / max(b, 1):.1%}  95%CI {lo:.1%}~{hi:.1%}")
        print(f"  재생성 {sum(r['generations'] > 1 for r in rs)}/{len(rs)}, 재검색 {sum(r['rewrites'] > 0 for r in rs)}/{len(rs)}, "
              f"뺀 문서 조건만족 {sum(r['dropped_compliant'] for r in rs)} / 불만족 {sum(r['dropped_noncompliant'] for r in rs)}")
        if "judge_unsupported" in rs[0]:
            counts = [len(r["judge_unsupported"]) for r in ctx]
            lo, hi = exp2.mean_ci(counts)
            bad = sum(c > 0 for c in counts)
            print(f"  LLM 판정: 답변당 근거 없는 주장 평균 {statistics.mean(counts):.2f}개 95%CI {lo:.2f}~{hi:.2f}, "
                  f"1개 이상인 답변 {bad}/{len(counts)} = {bad / max(len(counts), 1):.1%}")
            q = {}
            for r in ctx:
                q.setdefault(r["id"], []).append(len(r["judge_unsupported"]))
            per_q[arm] = {k: statistics.mean(v) for k, v in q.items()}
    for x in ("B", "C"):
        if "A" in per_q and x in per_q:
            ids = sorted(set(per_q["A"]) & set(per_q[x]))
            b = sum(per_q[x][i] < per_q["A"][i] for i in ids)
            c = sum(per_q[x][i] > per_q["A"][i] for i in ids)
            print(f"\n{x} vs A 질문 단위 근거 없는 주장 수(n={len(ids)}): {x}가 적음 {b}, A가 적음 {c}, 동률 {len(ids) - b - c}, "
                  f"부호검정 p={exact_binomial_two_sided(b, c):.4f}")


def self_check():
    from langchain_core.documents import Document
    d = Document(page_content="x", metadata={"product_price": 99000, "product_url": "https://a.com/1", "image_url": ""})
    assert code_grounded("₩99,000 [l](https://a.com/1)", [d])
    assert not code_grounded("₩120,000 [l](https://a.com/1)", [d])
    assert not code_grounded("₩99,000 [l](https://b.com/9)", [d])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    self_check()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--reps", type=int, default=2)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--out", default="results.jsonl")
    j = sub.add_parser("judge")
    j.add_argument("--inp", default="results.jsonl")
    j.add_argument("--out", default="judged.jsonl")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="judged.jsonl")
    a = p.parse_args()
    {"run": cmd_run, "judge": cmd_judge, "report": cmd_report}[a.cmd](a)
