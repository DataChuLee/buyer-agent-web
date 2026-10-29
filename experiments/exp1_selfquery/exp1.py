"""실험 1: SelfQuery(LLM이 조건을 다시 해석) vs 직접 메타데이터 필터.

  python experiments/exp1_selfquery/exp1.py run [--reps 3] [--limit N] [--out results.jsonl]
  python experiments/exp1_selfquery/exp1.py report [--inp results.jsonl]

- before: 예전 운영 방식. query_constructor(gpt-4o-mini)가 질문 문장을 필터로 바꿔 검색하고,
  파싱이 실패하면 필터 없이 검색한다. (노트북 측정의 LLM 이중 호출 결함을 고쳐 한 번만 호출)
- after: 현재 서비스의 retrieve_analysis_documents_filtered에 이미 구조화된 조건을 그대로 넣는다.
- 두 방식 모두 상위 3개 문서(서비스 기본값)를 채점하고, 실행 순서는 섞어서 시간 편향을 줄인다.
"""
import argparse
import csv
import json
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from math import comb
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
TOP_K = 3
MODEL = "gpt-4o-mini"


def load_questions():
    rows = list(csv.DictReader((HERE / "questions.csv").open(encoding="utf-8-sig")))
    for r in rows:
        r["min_price"], r["max_price"] = int(r["min_price"]), int(r["max_price"])
    return rows


def complies(meta, q):
    """문서가 질문의 4개 조건(판매처·모델·지면·가격)을 모두 만족하는가."""
    price = int(meta.get("product_price") or 0)
    return {
        "seller": not q["seller"] or meta.get("seller") == q["seller"],
        "series": q["series"].lower() in str(meta.get("product_name", "")).lower(),
        "ground": not q["ground_type"] or meta.get("ground_type") == q["ground_type"],
        "price": q["min_price"] <= price <= q["max_price"],
        # DB에 GK장갑 177건이 product_category=축구화로 들어 있어 이름으로 걸러낸다
        "shoe": not any(k in str(meta.get("product_name", "")) for k in ("장갑", "글러브")),
    }


def filter_omissions(structured, q):
    """before 방식에서 LLM이 만든 필터가 질문 조건을 빠뜨렸는지(조건별)."""
    text = str(structured.filter) if structured and structured.filter else ""
    query = str(structured.query) if structured else ""
    out = {}
    if q["seller"]:
        out["seller"] = q["seller"] not in text
    if q["ground_type"]:
        out["ground"] = f"'{q['ground_type']}'" not in text
    if (q["min_price"], q["max_price"]) != (0, 999999):
        out["price"] = "product_price" not in text
    # 모델명은 메타데이터 필드가 없어 검색어(query)에 남아야 한다. 필터에 들어가면 엉뚱한 필드에 넣은 것.
    out["series"] = q["series"].lower() not in query.lower()
    return out


def spurious_filter(structured):
    """질문에 없는 분류/연령 조건을 LLM이 덧붙였는가(질문 30개 모두 이 두 조건을 말하지 않음)."""
    text = str(structured.filter) if structured and structured.filter else ""
    return "product_category" in text or "age_group" in text


def build_before():
    from langchain_classic.chains.query_constructor.base import StructuredQueryOutputParser, get_query_constructor_prompt
    from langchain_classic.chains.query_constructor.schema import AttributeInfo
    from langchain_community.query_constructors.chroma import ChromaTranslator
    from langchain_openai import ChatOpenAI

    # 예전 운영 코드(RAG_Master_2.ipynb 셀 10)와 같은 메타데이터 설명
    info = [
        AttributeInfo(name="seller", description="제품 판매처명", type="string"),
        AttributeInfo(name="product_price", description="판매 가격 (원 단위 정수)", type="integer"),
        AttributeInfo(name="product_category", description="축구화 또는 풋살화", type="string"),
        AttributeInfo(name="age_group", description="성인용 또는 유소년용", type="string"),
        AttributeInfo(name="ground_type", description="FG, AG, HG, TF 등 지면 종류", type="string"),
    ]
    constructor = (get_query_constructor_prompt("여러 판매처에서 수집한 축구화 제품 문서", info)
                   | ChatOpenAI(model=MODEL, temperature=0) | StructuredQueryOutputParser.from_components())
    return constructor, ChromaTranslator()


def run_before(q, vectorstore, constructor, translator):
    t0 = time.perf_counter()
    structured, error = None, None
    try:
        structured = constructor.invoke(q["question"])
    except Exception as exc:  # 예전 동작: 파싱 실패 시 필터 없이 검색
        error = type(exc).__name__
    t_llm = time.perf_counter() - t0
    kwargs = {}
    search_text = q["question"]
    if structured is not None:
        search_text = structured.query or q["question"]
        _, kwargs = translator.visit_structured_query(structured)
    t1 = time.perf_counter()
    docs = vectorstore.similarity_search(search_text, k=TOP_K, filter=kwargs.get("filter"))
    t_ret = time.perf_counter() - t1
    return docs, {"llm_ms": t_llm * 1000, "retrieval_ms": t_ret * 1000, "error": error,
                  "structured": str(structured) if structured else None,
                  "omissions": filter_omissions(structured, q) if structured else None,
                  "spurious": spurious_filter(structured)}


def run_after(q, retrieve):
    t0 = time.perf_counter()
    docs = retrieve(seller_display=q["seller"] or None, product_keyword=q["series"], min_price=q["min_price"],
                    max_price=q["max_price"], limit=TOP_K, ground_type=q["ground_type"] or None)
    return docs, {"llm_ms": 0.0, "retrieval_ms": (time.perf_counter() - t0) * 1000, "error": None,
                  "structured": None, "omissions": None, "spurious": False}


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from Tools.rag_search import retrieve_analysis_documents_filtered
    from Tools.vectorstore_singleton import vectorstore

    questions = load_questions()[: args.limit]
    constructor, translator = build_before()
    # 예열: 첫 호출의 연결 초기화 시간이 한쪽 방식에만 섞이지 않게, 두 방식 모두 한 번씩 돌리고 버린다
    warm = {"question": "축구화", "seller": "", "series": "축구화", "ground_type": "", "min_price": 0, "max_price": 999999}
    run_before(warm, vectorstore, constructor, translator)
    run_after(warm, retrieve_analysis_documents_filtered)
    jobs = [(q, m, r) for q in questions for m in ("before", "after") for r in range(args.reps)]
    random.Random(7).shuffle(jobs)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    with open(HERE / args.out, "w", encoding="utf-8") as f:
        for i, (q, method, rep) in enumerate(jobs, 1):
            if method == "before":
                docs, info = run_before(q, vectorstore, constructor, translator)
            else:
                docs, info = run_after(q, retrieve_analysis_documents_filtered)
            checks = [complies(d.metadata, q) for d in docs]
            f.write(json.dumps({"id": q["id"], "method": method, "rep": rep, "n_conditions": int(q["n_conditions"]),
                                "n_docs": len(docs), "n_compliant": sum(all(c.values()) for c in checks),
                                "per_condition_ok": {k: sum(c[k] for c in checks) for k in ("seller", "series", "ground", "price", "shoe")},
                                "total_ms": info["llm_ms"] + info["retrieval_ms"], **info,
                                "model": MODEL, "commit": commit, "at": datetime.now(timezone.utc).isoformat()},
                               ensure_ascii=False) + "\n")
            print(f"[{i}/{len(jobs)}] {q['id']} {method} docs={len(docs)} ok={sum(all(c.values()) for c in checks)}", flush=True)


# ---------- 통계 (표준 라이브러리만) ----------
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(values, q):
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def bootstrap_ci(values, q, iters=2000, seed=0):
    rng = random.Random(seed)
    stats = sorted(percentile([rng.choice(values) for _ in values], q) for _ in range(iters))
    return stats[int(0.025 * iters)], stats[int(0.975 * iters)]


def exact_binomial_two_sided(b, c):
    """짝 비교(McNemar 정확검정): 한쪽만 맞힌 질문 수 b, c."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    by = {m: [r for r in rows if r["method"] == m] for m in ("before", "after")}
    print(f"runs: before={len(by['before'])}, after={len(by['after'])}, commit={rows[0]['commit']}, model={rows[0]['model']}")
    question_ok = {}
    for m, rs in by.items():
        docs = sum(r["n_docs"] for r in rs)
        ok = sum(r["n_compliant"] for r in rs)
        zero = sum(r["n_docs"] == 0 for r in rs)
        lat = [r["total_ms"] for r in rs]
        print(f"\n[{m}]")
        print(f"  정밀도(조건을 모두 만족한 문서/반환 문서): {ok}/{docs} = {ok / max(docs, 1):.1%}  95%CI {wilson(ok, docs)[0]:.1%}~{wilson(ok, docs)[1]:.1%}")
        print(f"  결과 0개 실행: {zero}/{len(rs)}")
        print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
              f"p95 {percentile(lat, .95):.0f}ms (CI {bootstrap_ci(lat, .95)[0]:.0f}~{bootstrap_ci(lat, .95)[1]:.0f})")
        if m == "before":
            errs = sum(r["error"] is not None for r in rs)
            llm = [r["llm_ms"] for r in rs]
            print(f"  파싱 실패(필터 없이 검색): {errs}/{len(rs)}")
            sp = sum(r["spurious"] for r in rs)
            print(f"  질문에 없는 조건 추가(분류/연령): {sp}/{len(rs)} = {sp / len(rs):.1%}  95%CI {wilson(sp, len(rs))[0]:.1%}~{wilson(sp, len(rs))[1]:.1%}")
            print(f"  LLM 단계 비중(평균 기준): {statistics.mean(llm) / statistics.mean(lat):.1%}")
            om = [r["omissions"] for r in rs if r["omissions"]]
            for key in ("seller", "ground", "price", "series"):
                applicable = [o[key] for o in om if key in o]
                if applicable:
                    k = sum(applicable)
                    print(f"  조건 누락 {key}: {k}/{len(applicable)} = {k / len(applicable):.1%}  95%CI {wilson(k, len(applicable))[0]:.1%}~{wilson(k, len(applicable))[1]:.1%}")
        # 질문 단위 판정: 반복 중 과반에서 상위 문서가 전부 조건을 만족하면 성공
        per_q = {}
        for r in rs:
            per_q.setdefault(r["id"], []).append(r["n_docs"] > 0 and r["n_compliant"] == r["n_docs"])
        question_ok[m] = {qid: sum(v) * 2 > len(v) for qid, v in per_q.items()}
        k = sum(question_ok[m].values())
        print(f"  질문 단위 성공(결과가 있고 전부 조건 만족, 반복 다수결): {k}/{len(per_q)}")
    ids = sorted(question_ok["before"])
    b = sum(question_ok["after"][i] and not question_ok["before"][i] for i in ids)
    c = sum(question_ok["before"][i] and not question_ok["after"][i] for i in ids)
    print(f"\n짝 비교: after만 성공 {b}, before만 성공 {c}, 정확 이항검정 p={exact_binomial_two_sided(b, c):.4f}")


def self_check():
    assert abs(exact_binomial_two_sided(6, 0) - 0.03125) < 1e-9
    assert exact_binomial_two_sided(0, 0) == 1.0 and exact_binomial_two_sided(3, 3) == 1.0
    lo, hi = wilson(9, 10)
    assert 0.59 < lo < 0.6 and 0.98 < hi < 0.99
    assert percentile([1, 2, 3, 4, 5], .5) == 3
    q = {"seller": "사커붐", "series": "팬텀", "ground_type": "", "min_price": 0, "max_price": 100000}
    assert all(complies({"seller": "사커붐", "product_name": "나이키 팬텀 GX", "ground_type": "FG", "product_price": 99000}, q).values())
    assert not complies({"seller": "사커붐", "product_name": "팬텀", "product_price": 120000}, q)["price"]
    assert not complies({"seller": "사커붐", "product_name": "팬텀 GK장갑", "ground_type": "FG", "product_price": 99000}, q)["shoe"]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글 출력
    self_check()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--out", default="results.jsonl")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="results.jsonl")
    a = p.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_report(a)
