"""실험 4: 라우팅(의도 파악 + 조건 점검) 옛 버전 vs 현재 버전.

  python experiments/exp4_routing/exp4.py run [--reps 3] [--limit N] [--out results.jsonl]
  python experiments/exp4_routing/exp4.py report [--inp results.jsonl]

- old: git 4306179^ 의 extract_conditions_and_intent / check_conditions를 그대로 옮겨 씀(단일 intent, 아래 OLD_*).
  삭제된 모듈(sub_agent_0310, langmem)을 import하던 파일이라 라우팅 부분만 원문 그대로 복사했다.
- new: 현재 서비스의 extract_conditions_and_intent → check_conditions를 직접 호출.
- 채점 단위: 이번 턴에 부르는 기능 집합(product_search/seller_search/product_analysis), 되묻기(ask), 도구 없음(none).
  supervisor_node는 순서와 ask_user만 정하고 집합은 위 두 단계에서 정해지므로 측정에서 뺐다(한계에 명시).
- 운영 DB는 쓰지 않는다(그래프·체크포인터를 만들지 않고 노드 함수만 호출).
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments/exp1_selfquery"))
from exp1 import bootstrap_ci, exact_binomial_two_sided, percentile, wilson  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

CAPS = ("product_search", "seller_search", "product_analysis")


# ---------- old: git show 4306179^:backend/Agent/LangGraph_buyeragent_with_personalization.py (원문 복사) ----------
class OldExtractedConditions(BaseModel):
    brand: str | None = Field(None)
    budget: str | None = Field(None)
    surface: str | None = Field(None)
    position: str | None = Field(None)
    age_group: str | None = Field(None)
    product_name: str | None = Field(None)
    seller: str | None = Field(None)


class OldExtractionResult(BaseModel):
    intent: Literal["product_search", "seller_search", "product_analysis", "chitchat"]
    conditions: OldExtractedConditions


def old_looks_like_purchase_intent(message):
    patterns = [r"이걸로\s*살게", r"이거로\s*살게", r"구매해줘", r"주문해줘", r"결제\s*직전", r"주문\s*진행", r"살게"]
    return any(re.search(p, message) for p in patterns)


async def old_route(question, llm, sanitize_condition_map):
    from langchain_core.messages import HumanMessage, SystemMessage
    system_prompt = (
        "You are a Korean shopping intent classifier for soccer shoes.\n"
        f"Current intent: {'none'}\n"
        f"Known profile: {'none'}\n"
        "Classify intent as one of product_search, seller_search, product_analysis, chitchat.\n"
        "Extract only conditions explicitly stated in the latest user request."
    )
    result = await llm.with_structured_output(OldExtractionResult).ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=question)])
    conditions = sanitize_condition_map(result.conditions.model_dump())
    intent = "purchase_prepare" if old_looks_like_purchase_intent(question) else result.intent
    missing = []  # old check_conditions (search_result는 첫 턴이라 비어 있음)
    if intent == "product_search" and not conditions:
        missing.append("brand, budget, surface 중 하나 이상")
    elif intent in ("seller_search", "product_analysis") and not conditions.get("product_name"):
        missing.append("상품명 또는 이전 검색 결과")
    if missing:
        return "ask", {"intent": intent, "conditions": conditions}
    label = intent if intent in CAPS else ("purchase" if intent == "purchase_prepare" else "none")
    return label, {"intent": intent, "conditions": conditions}


# ---------- new: 현재 서비스 코드 ----------
async def new_route(question, graph_module):
    from langchain_core.messages import HumanMessage
    state = {"messages": [HumanMessage(content=question)], "user_profile": {}, "user_conditions": {}}
    out = await graph_module.extract_conditions_and_intent(state)
    state.update(out)
    check = graph_module.check_conditions(state)
    intent = out["intent"]
    if intent in CAPS and check["missing_conditions"]:
        return "ask", {"intent": intent, "caps": out.get("requested_capabilities"), "missing": check["missing_conditions"]}
    if intent in CAPS:
        return "+".join(sorted(out.get("requested_capabilities") or [intent])), {"intent": intent, "caps": out.get("requested_capabilities")}
    return ("purchase" if intent == "purchase_prepare" else "none"), {"intent": intent}


def correct(pred, gold):
    return any(set(pred.split("+")) == set(g.split("+")) for g in gold.split("|"))


def load_questions(path=None):
    return list(csv.DictReader((Path(path) if path else HERE / "questions60.csv").open(encoding="utf-8-sig")))


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from langchain_community.callbacks import get_openai_callback
    import Agent.LangGraph_buyeragent_with_personalization as g
    from Tools.condition_sanitization import sanitize_condition_map
    questions = load_questions(args.questions)[: args.limit]
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()

    async def call(version, q):
        with get_openai_callback() as cb:
            t0 = time.perf_counter()
            pred, info = await (old_route(q, g.llm, sanitize_condition_map) if version == "old" else new_route(q, g))
            ms = (time.perf_counter() - t0) * 1000
        return pred, info, ms, cb.prompt_tokens, cb.completion_tokens

    async def main():
        versions = args.versions.split(",")
        for v in versions:
            await call(v, "안녕")  # 예열, 결과에서 제외
        jobs = [(q, v, r) for q in questions for v in versions for r in range(args.reps)]
        random.Random(7).shuffle(jobs)
        with open(HERE / args.out, "w", encoding="utf-8") as f:
            for i, (q, v, rep) in enumerate(jobs, 1):
                pred, info, ms, pt, ct = await call(v, q["question"])
                row = {"id": q["id"], "category": q["category"], "version": v, "rep": rep, "pred": pred, "gold": q["gold"],
                       "correct": correct(pred, q["gold"]), "info": info, "ms": ms, "prompt_tokens": pt,
                       "completion_tokens": ct, "model": "gpt-4o-mini", "commit": commit,
                       "at": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                print(f"[{i}/{len(jobs)}] {q['id']} {v} pred={pred} gold={q['gold']} {'O' if row['correct'] else 'X'}", flush=True)

    asyncio.run(main())


APPROVED_AMBIGUOUS = {"E13", "E14", "E15", "E20", "E21", "E22", "E23", "E24"}


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    if args.replace_new:  # 수정 후 재측정한 new 결과로 바꿔 비교(old는 같은 실행 결과 재사용)
        rows = [r for r in rows if r["version"] != "new"] + [json.loads(l) for l in open(HERE / args.replace_new, encoding="utf-8")]
    print(f"runs={len(rows)} commit={rows[0]['commit']} model={rows[0]['model']}")
    subsets = {
        "전체": lambda r: True,
        "의도 파악(정답에 ask 없음)": lambda r: "ask" not in r["gold"].split("|"),
        "규칙 준수(정답이 ask)": lambda r: "ask" in r["gold"].split("|"),
        "다중 기능(multi)": lambda r: r["category"] == "multi",
        "승인한 애매한 8개": lambda r: r["id"] in APPROVED_AMBIGUOUS,
    }
    for cat in ("clear", "multi", "ambiguous", "none"):
        subsets[f"범주 {cat}"] = (lambda c: lambda r: r["category"] == c)(cat)
    maj = {}
    for v in ("old", "new"):
        rs = [r for r in rows if r["version"] == v]
        per_q = {}
        for r in rs:
            per_q.setdefault(r["id"], []).append(r["correct"])
        maj[v] = {k: sum(x) * 2 > len(x) for k, x in per_q.items()}
        print(f"\n[{v}]")
        for name, f in subsets.items():
            sub = [r for r in rs if f(r)]
            k = sum(r["correct"] for r in sub)
            lo, hi = wilson(k, len(sub))
            qids = {r["id"] for r in sub}
            print(f"  {name}: 실행 {k}/{len(sub)} = {k / max(len(sub), 1):.1%} (95%CI {lo:.1%}~{hi:.1%}) | "
                  f"질문 다수결 {sum(maj[v][q] for q in qids)}/{len(qids)}")
        lat = [r["ms"] for r in rs]
        print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
              f"p95 {percentile(lat, .95):.0f}ms | 입력 토큰 평균 {statistics.mean(r['prompt_tokens'] for r in rs):.0f}")
        # 오류 분석: (정답 → 예측) 쌍
        wrong = Counter((r["gold"], r["pred"]) for r in rs if not r["correct"])
        print("  오답 유형(정답 → 예측, 실행 수): " + "; ".join(f"{g} → {p}: {n}" for (g, p), n in wrong.most_common(8)))
        # 반복 간 일관성: 3회 예측이 모두 같은 질문 비율
        preds = {}
        for r in rs:
            preds.setdefault(r["id"], set()).add(r["pred"])
        print(f"  반복 3회 예측이 모두 같은 질문 {sum(len(p) == 1 for p in preds.values())}/{len(preds)}")
    for name, f in [("전체", subsets["전체"]), ("의도 파악", subsets["의도 파악(정답에 ask 없음)"]),
                    ("규칙 준수", subsets["규칙 준수(정답이 ask)"])]:
        ids = sorted({r["id"] for r in rows if f(r)})
        b = sum(maj["new"][i] and not maj["old"][i] for i in ids)
        c = sum(maj["old"][i] and not maj["new"][i] for i in ids)
        print(f"\n짝 비교 [{name}] (n={len(ids)}): new만 정답 {b}, old만 정답 {c}, 정확 이항검정 p={exact_binomial_two_sided(b, c):.4f}")


def self_check():
    assert correct("seller_search+product_search", "product_search+seller_search")
    assert correct("none", "product_analysis|none")
    assert not correct("product_search", "product_search+seller_search")
    assert not correct("ask", "none")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    self_check()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--out", default="results.jsonl")
    r.add_argument("--versions", default="old,new")
    r.add_argument("--questions", default=None)
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="results.jsonl")
    rp.add_argument("--replace-new", default=None)
    a = p.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)
