"""실험 5: 단일 ReAct 에이전트(S1) vs 현재 구조(S2: 조건 추출 → 조건 점검 → supervisor 루프).

  python experiments/exp5_single_agent/exp5.py run --split tune|eval [--arms s1,s2] [--reps 3] [--prompt v0] [--out ...]
  python experiments/exp5_single_agent/exp5.py report [--inp results.jsonl]

- 질문: 실험 4와 같은 60문항(experiments/exp4_routing/questions60.csv). S1 프롬프트 다듬기는 tune 6문항
  (experiments/questions_draft.csv의 T1~T6)으로만 최대 2회 한다. 버전별 프롬프트는 PROMPTS에 남긴다.
- S1: create_react_agent(gpt-4o-mini, temp 0) + 가짜 도구 4개. ask_user는 return_direct라 부르면 턴이 끝난다
  (S2의 되묻기/interrupt와 같은 효과). 한 턴 동안 부른 도구 집합·순서로 채점.
- S2: 서비스의 extract_conditions_and_intent → check_conditions → supervisor_node(실제 gpt-5.4-nano)를
  past_steps를 쌓아가며 FINISH/ask_user까지 반복 호출. 워커는 실행하지 않는다(supervisor가 보는 상태만 갱신).
- S1 프롬프트 = S2 의도 분류 프롬프트 원문(서비스 소스에서 읽음) + supervisor 순서·요청 외 기능 금지 규칙 +
  서비스의 필수 조건 규칙. S1을 일부러 약하게 만들지 않기 위해서다.
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "experiments/exp1_selfquery"))
sys.path.insert(0, str(ROOT / "experiments/exp4_routing"))
from exp1 import bootstrap_ci, exact_binomial_two_sided, percentile, wilson  # noqa: E402
from exp4 import correct  # noqa: E402

CAPS = ("product_search", "seller_search", "product_analysis")
TOOL_TO_CAP = {"search_products": "product_search", "search_sellers": "seller_search",
               "analyze_product": "product_analysis", "ask_user": "ask"}


def s2_intent_prompt():
    """서비스의 의도 분류 system_prompt 원문을 소스에서 읽어 첫 턴 값(previous_intent/profile 없음)으로 채운다."""
    src = (ROOT / "backend/Agent/LangGraph_buyeragent_with_personalization.py").read_text(encoding="utf-8")
    block = re.search(r"    system_prompt = \(\n(.*?)\n    \)\n    history", src, re.S).group(1)
    text = eval("(" + block + ")", {"previous_intent": "", "structured_items": []})  # 서비스 소스(신뢰 가능)의 문자열 리터럴
    assert "requested_capabilities" in text and "## Examples" in text
    return text


TOOL_RULES = """

## 도구 사용 규칙 (당신은 위 분류를 직접 도구 호출로 실행하는 단일 에이전트입니다)
- shopping이면 requested_capabilities에 해당하는 도구만 부르세요:
  product_search → search_products, seller_search → search_sellers, product_analysis → analyze_product.
  요청되지 않은 기능의 도구는 부르지 마세요.
- 여러 기능을 요청하면 product_search → seller_search → product_analysis 순서로 부르세요.
- product_guide/chitchat이면 도구를 부르지 말고 바로 한국어로 답하세요.
- 필수 조건(서비스 정책): search_products는 브랜드·예산·지면(FG/AG/TF/HG/IC/MG/SG)이 모두 있어야 합니다.
  search_sellers와 analyze_product는 상품명(모델/시리즈명)이 있어야 합니다.
  첫 번째로 필요한 기능의 필수 조건이 하나라도 없으면 다른 도구를 부르지 말고 ask_user로 부족한 조건을 물으세요."""

PROMPTS = {"v0": TOOL_RULES}  # 다듬기 결과는 아래에 v1, v2로 추가(변경 이유를 주석으로)


def make_tools():
    from langchain_core.tools import tool

    @tool
    def search_products(brand: str, budget: str, surface: str) -> str:
        """조건(브랜드·예산·지면)에 맞는 축구화 시리즈/모델을 추천 검색한다."""
        return f"검색 결과: 1) {brand} 모델 A ({surface}, 129,000원) 2) {brand} 모델 B ({surface}, 99,000원)"

    @tool
    def search_sellers(product_name: str) -> str:
        """상품을 파는 판매처(크레이지11/사커붐/레드사커/카포스토어)와 가격을 찾는다."""
        return f"{product_name} 판매처: 크레이지11 129,000원, 사커붐 125,000원"

    @tool
    def analyze_product(product_name: str, seller: str = "") -> str:
        """특정 상품(판매처 지정 가능)의 가격·사이즈·특징을 상세 비교·분석한다."""
        return f"{product_name} 분석: 가격 125,000~129,000원, 사이즈 250~280"

    @tool(return_direct=True)
    def ask_user(question: str) -> str:
        """필수 조건이 부족할 때 사용자에게 되묻는다. 부르면 이번 턴이 끝난다."""
        return question

    return [search_products, search_sellers, analyze_product, ask_user]


def label_from_sequence(seq):
    caps = [c for c in seq if c != "ask"]
    if "ask" in seq and not caps:
        return "ask"
    if not seq:
        return "none"
    return "+".join(sorted(set(seq)))


def in_canonical_order(seq):
    caps = [c for c in seq if c in CAPS]
    idx = [CAPS.index(c) for c in caps]
    return idx == sorted(idx)


async def s1_route(question, agent):
    from langchain_core.messages import HumanMessage
    out = await agent.ainvoke({"messages": [HumanMessage(content=question)]}, config={"recursion_limit": 12})
    seq = []
    for m in out["messages"]:
        for tc in getattr(m, "tool_calls", None) or []:
            cap = TOOL_TO_CAP.get(tc["name"], tc["name"])
            if cap not in seq:
                seq.append(cap)
    llm_calls = sum(1 for m in out["messages"] if m.type == "ai")
    return seq, {"llm_calls": llm_calls}


async def s2_route(question, g, supervisor_node):
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END
    state = {"messages": [HumanMessage(content=question)], "user_profile": {}, "user_conditions": {}}
    state.update(await g.extract_conditions_and_intent(state))
    check = g.check_conditions(state)
    intent = state["intent"]
    if intent not in CAPS:
        return [], {"intent": intent, "llm_calls": 1}
    if check["missing_conditions"]:
        return ["ask"], {"intent": intent, "missing": check["missing_conditions"], "llm_calls": 1}
    seq, calls = [], 1
    node_to_cap = {"product_search_worker_node": "product_search", "seller_search_worker_node": "seller_search",
                   "product_analysis_worker_node": "product_analysis"}
    for _ in range(4):
        cmd = await supervisor_node(state)
        calls += 1
        if cmd.goto in node_to_cap:
            step = node_to_cap[cmd.goto]
            seq.append(step)
            state["past_steps"] = list(state.get("past_steps") or []) + [step]
            continue
        if cmd.goto == END and (cmd.update or {}).get("status") == "waiting_input":
            seq.append("ask")
        break
    return seq, {"intent": intent, "caps": state.get("requested_capabilities"), "llm_calls": calls}


def load_split(split):
    if split == "tune":
        rows = [r for r in csv.DictReader((ROOT / "experiments/questions_draft.csv").open(encoding="utf-8-sig")) if r["split"] == "tune"]
        return [{"id": r["id"], "category": r["category"], "question": r["question"], "gold": r["gold_candidate"]} for r in rows]
    name = "holdout/routing_questions.csv" if split == "holdout" else "exp4_routing/questions60.csv"
    return list(csv.DictReader((ROOT / "experiments" / name).open(encoding="utf-8-sig")))


def cmd_run(args):
    from dotenv import load_dotenv
    load_dotenv(ROOT / "backend/.env")
    from langchain_community.callbacks import get_openai_callback
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent
    import Agent.LangGraph_buyeragent_with_personalization as g
    from Agent.orchestration.supervisor import supervisor_node
    questions = load_split(args.split)[: args.limit]
    system = s2_intent_prompt() + PROMPTS[args.prompt]
    agent = create_react_agent(ChatOpenAI(model="gpt-4o-mini", temperature=0), make_tools(), prompt=system)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    arms = args.arms.split(",")

    async def call(arm, q):
        with get_openai_callback() as cb:
            t0 = time.perf_counter()
            seq, info = await (s1_route(q, agent) if arm == "s1" else s2_route(q, g, supervisor_node))
            ms = (time.perf_counter() - t0) * 1000
        return seq, info, ms, cb.prompt_tokens, cb.completion_tokens

    async def main():
        for arm in arms:
            await call(arm, "안녕")  # 예열, 결과에서 제외
        jobs = [(q, a, r) for q in questions for a in arms for r in range(args.reps)]
        random.Random(7).shuffle(jobs)
        with open(HERE / args.out, "w", encoding="utf-8") as f:
            for i, (q, arm, rep) in enumerate(jobs, 1):
                seq, info, ms, pt, ct = await call(arm, q["question"])
                pred = label_from_sequence(seq)
                row = {"id": q["id"], "category": q["category"], "arm": arm, "rep": rep, "seq": seq, "pred": pred,
                       "gold": q["gold"], "correct": correct(pred, q["gold"]), "order_ok": in_canonical_order(seq),
                       "info": info, "ms": ms, "prompt_tokens": pt, "completion_tokens": ct,
                       "prompt_version": args.prompt if arm == "s1" else "service", "commit": commit,
                       "at": datetime.now(timezone.utc).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                print(f"[{i}/{len(jobs)}] {q['id']} {arm} seq={seq} gold={q['gold']} {'O' if row['correct'] else 'X'}", flush=True)

    asyncio.run(main())


def cmd_report(args):
    rows = [json.loads(l) for l in open(HERE / args.inp, encoding="utf-8")]
    arms = sorted({r["arm"] for r in rows})
    print(f"runs={len(rows)} commit={rows[0]['commit']} s1_prompt={sorted({r['prompt_version'] for r in rows if r['arm'] == 's1'})}")
    subsets = {"전체": lambda r: True,
               "의도 파악(정답에 ask 없음)": lambda r: "ask" not in r["gold"].split("|"),
               "규칙 준수(정답이 ask)": lambda r: "ask" in r["gold"].split("|")}
    for cat in ("clear", "multi", "ambiguous", "none"):
        subsets[f"범주 {cat}"] = (lambda c: lambda r: r["category"] == c)(cat)
    maj = {}
    for arm in arms:
        rs = [r for r in rows if r["arm"] == arm]
        per_q = {}
        for r in rs:
            per_q.setdefault(r["id"], []).append(r["correct"])
        maj[arm] = {k: sum(v) * 2 > len(v) for k, v in per_q.items()}
        print(f"\n[{arm}]")
        for name, f in subsets.items():
            sub = [r for r in rs if f(r)]
            if not sub:
                continue
            k = sum(r["correct"] for r in sub)
            lo, hi = wilson(k, len(sub))
            print(f"  {name}: 실행 {k}/{len(sub)} = {k / len(sub):.1%} (95%CI {lo:.1%}~{hi:.1%})")
        multi_ok = [r for r in rs if r["category"] == "multi" and r["correct"] and "+" in r["pred"]]
        if multi_ok:
            print(f"  다중 기능 정답 중 순서도 맞음 {sum(r['order_ok'] for r in multi_ok)}/{len(multi_ok)}")
        lat = [r["ms"] for r in rs]
        print(f"  지연 p50 {percentile(lat, .5):.0f}ms (CI {bootstrap_ci(lat, .5)[0]:.0f}~{bootstrap_ci(lat, .5)[1]:.0f}), "
              f"p95 {percentile(lat, .95):.0f}ms | LLM 호출 평균 {statistics.mean(r['info']['llm_calls'] for r in rs):.2f}회 | "
              f"토큰 평균 입력 {statistics.mean(r['prompt_tokens'] for r in rs):.0f} / 출력 {statistics.mean(r['completion_tokens'] for r in rs):.0f}")
        wrong = Counter((r["gold"], r["pred"]) for r in rs if not r["correct"])
        print("  오답 유형: " + "; ".join(f"{g} → {p}: {n}" for (g, p), n in wrong.most_common(8)))
        preds = {}
        for r in rs:
            preds.setdefault(r["id"], set()).add(r["pred"])
        print(f"  반복 예측이 모두 같은 질문 {sum(len(p) == 1 for p in preds.values())}/{len(preds)}")
    if set(arms) >= {"s1", "s2"}:
        for name, f in subsets.items():
            if name.startswith("범주"):
                continue
            ids = sorted({r["id"] for r in rows if f(r)})
            b = sum(maj["s2"][i] and not maj["s1"][i] for i in ids)
            c = sum(maj["s1"][i] and not maj["s2"][i] for i in ids)
            print(f"\n짝 비교 [{name}] (n={len(ids)}): S2만 정답 {b}, S1만 정답 {c}, 정확 이항검정 p={exact_binomial_two_sided(b, c):.4f}")


def self_check():
    assert label_from_sequence([]) == "none"
    assert label_from_sequence(["ask"]) == "ask"
    assert label_from_sequence(["seller_search", "product_search"]) == "product_search+seller_search"
    assert label_from_sequence(["product_search", "ask"]) == "ask+product_search"
    assert in_canonical_order(["product_search", "seller_search"]) and not in_canonical_order(["product_analysis", "seller_search"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    self_check()
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--split", choices=["tune", "eval", "holdout"], required=True)
    r.add_argument("--arms", default="s1,s2")
    r.add_argument("--reps", type=int, default=3)
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--prompt", default="v0")
    r.add_argument("--out", default="results.jsonl")
    rp = sub.add_parser("report")
    rp.add_argument("--inp", default="results.jsonl")
    a = p.parse_args()
    {"run": cmd_run, "report": cmd_report}[a.cmd](a)
