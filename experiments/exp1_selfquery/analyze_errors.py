"""실험 1 before 방식의 실패 원인 분류: LLM이 만든 필터를 조건별로 '정상/누락/엉뚱한 필드/값 오류'로 판정한다.

실행: backend/venv/Scripts/python.exe experiments/exp1_selfquery/analyze_errors.py
"""
import collections
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CMP = re.compile(r"comparator=<Comparator\.\w+: '(\w+)'>, attribute='(\w+)', value=('?)(.*?)\3\)")


def comparisons(structured):
    return [(op, attr, val) for op, attr, _, val in CMP.findall(structured or "")]


def price_range(cmps):
    lo, hi = 0, 999999
    for op, attr, val in cmps:
        if attr != "product_price":
            continue
        v = int(float(val))
        if op in ("gte", "eq"):
            lo = max(lo, v)
        if op == "gt":
            lo = max(lo, v + 1)
        if op in ("lte", "eq"):
            hi = min(hi, v)
        if op == "lt":
            hi = min(hi, v - 1)
    return lo, hi


def classify(q, structured):
    """조건별 판정. 값: ok / missing / wrong_field / wrong_value."""
    cmps = comparisons(structured)
    query = (re.search(r"query='(.*?)'", structured or "") or [None, ""])[1]
    out = {}
    for key, gold, attr in (("seller", q["seller"], "seller"), ("ground", q["ground_type"], "ground_type")):
        if not gold:
            continue
        hits = [a for _, a, v in cmps if v == gold]
        out[key] = "ok" if attr in hits else ("wrong_field" if hits else "missing")
    gold_range = (int(q["min_price"]), int(q["max_price"]))
    if gold_range != (0, 999999):
        if not any(a == "product_price" for _, a, _ in cmps):
            out["price"] = "missing"
        else:
            lo, hi = price_range(cmps)
            if (lo, hi) == gold_range:
                out["price"] = "ok"
            elif abs(lo - gold_range[0]) <= 1 and abs(hi - gold_range[1]) <= 1:
                out["price"] = "boundary"  # '이하'를 '미만'으로: 경계 가격 상품만 빠지는 경미한 오류
            else:
                out["price"] = "wrong_value"
    in_filter = any(q["series"].lower() in v.lower() for _, _, v in cmps)
    out["series"] = "ok" if q["series"].lower() in query.lower() else ("wrong_field" if in_filter else "missing")
    out["spurious"] = any(a in ("product_category", "age_group") for _, a, _ in cmps)
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    qs = {r["id"]: r for r in csv.DictReader((HERE / "questions.csv").open(encoding="utf-8-sig"))}
    rows = [json.loads(l) for l in open(HERE / "results.jsonl", encoding="utf-8")]
    before = [r for r in rows if r["method"] == "before"]

    per_cond = collections.defaultdict(collections.Counter)
    fail_causes = collections.Counter()
    fail_runs = 0
    for r in before:
        c = classify(qs[r["id"]], r["structured"])
        for k, v in c.items():
            if k != "spurious":
                per_cond[k][v] += 1
        failed = r["n_docs"] == 0 or r["n_compliant"] < r["n_docs"]
        if failed:
            fail_runs += 1
            causes = [f"{k}:{v}" for k, v in c.items() if k != "spurious" and v != "ok"]
            if c["spurious"]:
                causes.append("spurious_filter")
            # 필터가 모두 맞는데 실패하면 검색 단계(벡터 유사도) 문제
            fail_causes.update(causes or ["filter_ok_retrieval_miss"])
    print(f"before 실행 {len(before)}회 중 실패(결과 0개 또는 조건 불만족 문서 포함) {fail_runs}회")
    print("\n조건별 LLM 필터 판정:")
    for k, cnt in per_cond.items():
        print(f"  {k}: " + ", ".join(f"{v} {n}" for v, n in cnt.most_common()) + f" (n={sum(cnt.values())})")
    print("\n실패 실행의 원인(한 실행에 여러 원인 가능):")
    for cause, n in fail_causes.most_common():
        print(f"  {cause}: {n}")


def self_check():
    q = {"seller": "레드사커", "ground_type": "AG", "series": "머큐리얼", "min_price": "100000", "max_price": "199999"}
    s = ("query='AG 머큐리얼' filter=Operation(operator=<Operator.AND: 'and'>, arguments=[Comparison(comparator=<Comparator.EQ: 'eq'>, "
         "attribute='product_price', value=100000), Comparison(comparator=<Comparator.EQ: 'eq'>, attribute='product_category', value='레드사커')]) limit=None")
    c = classify(q, s)
    assert c == {"seller": "wrong_field", "ground": "missing", "price": "wrong_value", "series": "ok", "spurious": True}, c
    assert price_range([("gte", "product_price", "100000"), ("lt", "product_price", "200000")]) == (100000, 199999)
    s2 = "query='머큐리얼' filter=Comparison(comparator=<Comparator.LT: 'lt'>, attribute='product_price', value=200000) limit=None"
    assert classify(dict(q, seller="", ground_type="", min_price="0", max_price="200000"), s2)["price"] == "boundary"


if __name__ == "__main__":
    self_check()
    main()
