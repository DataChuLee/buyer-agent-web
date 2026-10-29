"""실험 2: 분석 에이전트의 CRAG/Self-RAG 채점 단계 ablation (on = 현재 서비스, off = 채점 단계 통과 처리).

  python experiments/exp2_graders/exp2.py run [--reps 2] [--limit N] [--out results.jsonl]
  python experiments/exp2_graders/exp2.py judge [--inp results.jsonl] [--out judged.jsonl]
  python experiments/exp2_graders/exp2.py report [--inp judged.jsonl]

- 질문: 실험 1과 같은 30개(experiments/exp1_selfquery/questions.csv)를 그대로 쓴다.
- 실시간 크롤링(crawl_and_index)은 no-op으로 막아 로컬 Chroma만 읽는다(네트워크 편차·DB 쓰기 제거).
- off: grade_docs_relevance를 그대로 통과, grade_answer_groundedness를 항상 True로 둔다
  (= 채점 단계 도입 전 동작). 그 외 코드는 서비스 그대로.
- 채점: (1) 결정적 지표 - 답변의 가격/링크가 문서에 있는가, 답변에 나온 상품이 질문 조건을 만족하는가
        (2) LLM 판정 - 생성 모델과 다른 모델(JUDGE_MODEL)이 문서에 없는 주장을 찾는다
"""
import argparse
import asyncio
import csv
import json
import random
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments/exp1_selfquery"))
from exp1 import bootstrap_ci, complies, exact_binomial_two_sided, load_questions, percentile, wilson  # noqa: E402

GEN_MODEL = "gpt-4o-mini"  # Tools/rag_search.py의 model
JUDGE_MODEL = "gpt-4o"
URL_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
PRICE_RE = re.compile(r"₩\s?([\d,]+)|([\d,]{5,})\s*원")


def conditions_for(q):
    # 서비스에서 앞 단계가 넘겨주는 조건 형태. 가격/지면은 서비스와 같게 질문 문장에서 파싱된다.
    return {k: v for k, v in {"product_name": q["series"], "seller": q["seller"]}.items() if v}


async def run_one(q, arm):
    import Agent.product_analysis_agent as pa

    log = {"grader_in": 0, "grader_out": 0, "grader_calls": 0, "rewrites": 0, "ground_verdicts": [], "generations": 0}
    orig_grade, orig_ground, orig_rewrite, orig_gen = (
        pa.grade_docs_relevance, pa.grade_answer_groundedness, pa.rewrite_analysis_query, pa._generate_answer)

    async def grade(query, docs):
        log["grader_calls"] += 1
        log["grader_in"] += len(docs)
        out = await orig_grade(query, docs) if arm == "on" else docs
        log["grader_out"] += len(out)
        log.setdefault("dropped", []).extend(d.metadata for d in docs if d not in out)
        return out

    async def ground(answer, docs):
        verdict = await orig_ground(answer, docs) if arm == "on" else True
        log["ground_verdicts"].append(verdict)
        return verdict

    async def rewrite(query, conditions=None):
        log["rewrites"] += 1
        return await orig_rewrite(query, conditions)

    async def gen(context, messages):
        log["generations"] += 1
        return await orig_gen(context, messages)

    class NoCrawl:
        async def ainvoke(self, _):
            return None

    with patch.object(pa, "crawl_and_index", NoCrawl()), patch.object(pa, "grade_docs_relevance", grade), \
            patch.object(pa, "grade_answer_groundedness", ground), patch.object(pa, "rewrite_analysis_query", rewrite), \
            patch.object(pa, "_generate_answer", gen):
        t0 = time.perf_counter()
        result = await pa.product_analysis_agent(q["question"], conditions=conditions_for(q), return_result=True)
        ms = (time.perf_counter() - t0) * 1000
    return result, ms, log


def deterministic_scores(answer, docs, q):
    metas = [d.metadata for d in docs]
    doc_urls = {str(m.get("product_url", "")) for m in metas} | {str(m.get("image_url", "")) for m in metas}
    doc_text = " ".join(d.page_content for d in docs)
    doc_prices = {int(m.get("product_price") or 0) for m in metas} | {int(p.replace(",", "")) for p in re.findall(r"[\d,]{5,}", doc_text) if p.replace(",", "").isdigit()}
    urls = URL_RE.findall(answer)
    prices = [int((a or b).replace(",", "")) for a, b in PRICE_RE.findall(answer) if (a or b).replace(",", "").isdigit()]
    by_url = {str(m.get("product_url", "")): m for m in metas}
    shown = [by_url[u] for u in urls if u in by_url]
    return {
        "n_urls": len(urls), "urls_not_in_docs": sum(u not in doc_urls for u in urls),
        "n_prices": len(prices), "prices_not_in_docs": sum(p not in doc_prices for p in prices),
        "n_shown_products": len(shown), "shown_noncompliant": sum(not all(complies(m, q).values()) for m in shown),
        "context_docs": len(metas), "context_noncompliant": sum(not all(complies(m, q).values()) for m in metas),
    }


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    questions = load_questions()[: args.limit]
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    async def main():
        await run_one(questions[0], "off")  # 예열(연결 초기화), 결과에서 제외
        jobs = [(q, arm, r) for q in questions for arm in ("on", "off") for r in range(args.reps)]
        random.Random(7).shuffle(jobs)
        with open(HERE / args.out, "w", encoding="utf-8") as f:
            for i, (q, arm, rep) in enumerate(jobs, 1):
                result, ms, log = await run_one(q, arm)
                dropped = log.pop("dropped", [])
                row = {"id": q["id"], "arm": arm, "rep": rep, "total_ms": ms, **log,
                       "dropped_compliant": sum(all(complies(m, q).values()) for m in dropped),
                       "dropped_noncompliant": sum(not all(complies(m, q).values()) for m in dropped),
                       **deterministic_scores(result.answer, result.docs, q),
                       # 판정자도 생성 모델과 같은 형식(본문 + 상품/이미지 URL)의 문서를 보게 한다
                       "answer": result.answer, "context": [format_docs([d]) for d in result.docs],
                       "context_meta": [d.metadata for d in result.docs],
                       "model": GEN_MODEL, "commit": commit, "at": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"[{i}/{len(jobs)}] {q['id']} {arm} {ms:.0f}ms ctx={row['context_docs']} "
                      f"drop={row['dropped_compliant']}+{row['dropped_noncompliant']} regen={log['generations'] - 1}", flush=True)

    from Tools.rag_search import format_docs
    asyncio.run(main())


JUDGE_PROMPT = """너는 RAG 답변의 사실 근거를 검사하는 채점자다. 아래 [문서]만 사실로 인정한다.
[답변]에 있는 주장(가격, 사이즈, 지면/연령, 기능·소재 등 특징, 판매처, 상품명) 중 [문서]에서 확인할 수 없는 것을
모두 찾아라. 표현만 다르고 뜻이 같으면 근거 있음으로 본다. "결과를 찾을 수 없다"는 안내 문장은 주장이 아니다.

[문서]
{docs}

[답변]
{answer}"""


def cmd_judge(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from langchain_openai import ChatOpenAI
    from pydantic import BaseModel, Field

    class Verdict(BaseModel):
        unsupported_claims: list[str] = Field(description="문서에서 확인할 수 없는 주장 원문 목록(없으면 빈 목록)")
        n_claims_checked: int = Field(description="검사한 주장 개수(대략)")

    judge = ChatOpenAI(model=JUDGE_MODEL, temperature=0).with_structured_output(Verdict)
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    with open(HERE / args.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows, 1):
            if r["context"]:
                v = judge.invoke(JUDGE_PROMPT.format(docs="\n\n".join(r["context"]), answer=r["answer"]))
                r["judge_unsupported"], r["judge_n_claims"] = v.unsupported_claims, v.n_claims_checked
            else:
                r["judge_unsupported"], r["judge_n_claims"] = [], 0
            r["judge_model"] = JUDGE_MODEL
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(rows)}] {r['id']} {r['arm']} unsupported={len(r['judge_unsupported'])}", flush=True)
    # 사람 검수용 표본 10건(판정 신뢰도 확인). 순서는 고정 시드.
    sample = random.Random(11).sample([r for r in rows if r["context"]], min(10, len(rows)))
    with open(HERE / getattr(args, "human_out", "human_check.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "arm", "rep", "judge_unsupported", "human_agrees(Y/N)", "note"])
        for r in sample:
            w.writerow([r["id"], r["arm"], r["rep"], " | ".join(r["judge_unsupported"]) or "(없음)", "", ""])


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    by = {a: [r for r in rows if r["arm"] == a] for a in ("off", "on")}
    print(f"runs: off={len(by['off'])}, on={len(by['on'])}, commit={rows[0]['commit']}, gen={rows[0]['model']}, "
          f"judge={rows[0].get('judge_model', '-')}")
    per_q_clean = {}
    for arm, rs in by.items():
        lat = [r["total_ms"] for r in rs]
        print(f"\n[{arm}]")
        print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
              f"p95 {percentile(lat, .95):.0f}ms (CI {bootstrap_ci(lat, .95)[0]:.0f}~{bootstrap_ci(lat, .95)[1]:.0f})")
        for label, k, n in [
            ("답변 생성에 쓴 문서 중 조건 불만족", "context_noncompliant", "context_docs"),
            ("답변에 보여준 상품 중 조건 불만족", "shown_noncompliant", "n_shown_products"),
            ("답변의 링크 중 문서에 없는 것", "urls_not_in_docs", "n_urls"),
            ("답변의 가격 중 문서에 없는 것", "prices_not_in_docs", "n_prices"),
        ]:
            # 결과 없음 안내문의 "200,000원 이하" 같은 조건 문구가 가격으로 잡히지 않게, 문서가 있던 실행만 센다
            a, b = sum(r[k] for r in rs if r["context_docs"]), sum(r[n] for r in rs if r["context_docs"])
            lo, hi = wilson(a, b)
            print(f"  {label}: {a}/{b} = {a / max(b, 1):.1%}  95%CI {lo:.1%}~{hi:.1%}")
        if "judge_unsupported" in rs[0]:
            bad = sum(bool(r["judge_unsupported"]) for r in rs if r["context"])
            n = sum(bool(r["context"]) for r in rs)
            lo, hi = wilson(bad, n)
            print(f"  LLM 판정: 근거 없는 주장이 1개 이상인 답변 {bad}/{n} = {bad / max(n, 1):.1%}  95%CI {lo:.1%}~{hi:.1%}")
            counts = [len(r["judge_unsupported"]) for r in rs if r["context"]]
            lo, hi = mean_ci(counts)
            print(f"  LLM 판정: 답변당 근거 없는 주장 평균 {statistics.mean(counts):.2f}개  95%CI {lo:.2f}~{hi:.2f} (합계 {sum(counts)})")
        if arm == "on":
            dc, dn = sum(r["dropped_compliant"] for r in rs), sum(r["dropped_noncompliant"] for r in rs)
            print(f"  CRAG가 뺀 문서: 조건 만족 {dc}건(과잉 제거) / 조건 불만족 {dn}건(올바른 제거), 채점 입력 {sum(r['grader_in'] for r in rs)}건")
            print(f"  재검색(rewrite) 실행 {sum(r['rewrites'] > 0 for r in rs)}/{len(rs)}, "
                  f"Self-RAG 재생성 {sum(r['generations'] > 1 for r in rs)}/{len(rs)}")
            print(f"  결과 없음으로 끝난 실행 {sum(r['context_docs'] == 0 for r in rs)}/{len(rs)}")
            if "judge_unsupported" in rs[0]:
                # 첫 답변 기준 Self-RAG 판정과 외부 판정 비교(재생성 안 된 실행만: 최종 답변 = 첫 답변)
                first = [r for r in rs if r["ground_verdicts"] and r["generations"] == 1]
                missed = sum(r["ground_verdicts"][0] and bool(r["judge_unsupported"]) for r in first)
                flagged = sum(bool(r["judge_unsupported"]) for r in first)
                print(f"  Self-RAG가 통과시켰지만 외부 판정은 근거 없음: {missed}/{flagged} (재생성 없던 실행 {len(first)}건 중)")
        else:
            print(f"  결과 없음으로 끝난 실행 {sum(r['context_docs'] == 0 for r in rs)}/{len(rs)}")
        print(f"  평균 LLM 호출(생성+채점) {statistics.mean(r['generations'] + r['grader_calls'] * (arm == 'on') + len(r['ground_verdicts']) * (arm == 'on') + r['rewrites'] for r in rs):.2f}회")
        if "judge_unsupported" in rs[0]:
            per_q = {}
            for r in rs:
                if r["context"]:
                    per_q.setdefault(r["id"], []).append(len(r["judge_unsupported"]))
            per_q_clean[arm] = {k: statistics.mean(v) for k, v in per_q.items()}
    if len(per_q_clean) == 2:
        # 질문별 평균 '근거 없는 주장 수'를 짝지어 부호검정(동률 제외)
        ids = sorted(set(per_q_clean["on"]) & set(per_q_clean["off"]))
        b = sum(per_q_clean["on"][i] < per_q_clean["off"][i] for i in ids)
        c = sum(per_q_clean["on"][i] > per_q_clean["off"][i] for i in ids)
        print(f"\n질문 단위 근거 없는 주장 수 짝 비교(n={len(ids)}): on이 적음 {b}, off가 적음 {c}, 동률 {len(ids) - b - c}, "
              f"부호검정 p={exact_binomial_two_sided(b, c):.4f}")


def mean_ci(values, iters=2000, seed=0):
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choice(values) for _ in values) for _ in range(iters))
    return means[int(0.025 * iters)], means[int(0.975 * iters)]


def self_check():
    assert mean_ci([2, 2, 2]) == (2, 2)
    from langchain_core.documents import Document
    q = {"seller": "사커붐", "series": "팬텀", "ground_type": "", "min_price": 0, "max_price": 100000}
    doc = Document(page_content="나이키 팬텀 GX 가격 99,000원",
                   metadata={"seller": "사커붐", "product_name": "나이키 팬텀 GX", "product_price": 99000,
                             "product_url": "https://a.com/1", "image_url": "https://a.com/1.jpg"})
    s = deterministic_scores("| 사커붐 | 팬텀 | ₩99,000 | [🔗](https://a.com/1) | ₩120,000 [x](https://b.com/2)", [doc], q)
    assert (s["n_urls"], s["urls_not_in_docs"], s["n_prices"], s["prices_not_in_docs"]) == (2, 1, 2, 1), s
    assert (s["n_shown_products"], s["shown_noncompliant"], s["context_noncompliant"]) == (1, 0, 0), s


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
