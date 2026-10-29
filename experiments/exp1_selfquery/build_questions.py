"""실험 1 질문 30개 생성: 실제 Chroma DB에 정답 문서가 2개 이상 있는 조건 조합만 쓴다.

실행: backend/venv/Scripts/python.exe experiments/exp1_selfquery/build_questions.py
출력: experiments/exp1_selfquery/questions.csv (실행 전에 고정, 결과를 본 뒤에는 고치지 않음)
"""
import csv
import random
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("questions.csv")
SERIES = ["머큐리얼", "팬텀", "티엠포", "프레데터", "코파", "F50", "퓨처", "울트라", "모렐리아"]
SELLERS = ["크레이지11", "사커붐", "레드사커", "카포스토어"]
GROUNDS = ["FG", "TF", "AG", "MG", "HG"]
# (말로 쓴 가격 조건, min, max)
PRICES = [("10만원 이하", 0, 100000), ("15만원 이하", 0, 150000), ("20만원 이하", 0, 200000),
          ("30만원 이하", 0, 300000), ("10만원대", 100000, 199999), ("20만원대", 200000, 299999),
          ("15만원 이상", 150000, 999999), ("", 0, 999999)]
# 같은 조건이라도 말투와 어순을 바꿔 LLM 파싱 난이도를 고르게 섞는다(있는 조건만 이어 붙임)
SELLER_PHRASES = ["{}에서", "{} 기준으로", "판매처는 {}", "{}에 있는"]
GROUND_PHRASES = ["{}", "{}용", "{} 구장용"]
ENDINGS = ["보여줘", "찾아줘", "있어?", "추천해줘", "알려줘"]


def phrase(rng, seller, series, ground, price_text):
    parts = [series + rng.choice(["", " 축구화", " 시리즈"])]
    if ground:
        parts.append(rng.choice(GROUND_PHRASES).format(ground))
    if price_text:
        parts.append(price_text)
    if seller:
        parts.append(rng.choice(SELLER_PHRASES).format(seller))
    rng.shuffle(parts)
    return rng.choice([" ", ", "]).join(parts) + " " + rng.choice(ENDINGS)


def matches(meta, seller, series, ground, lo, hi):
    return ((not seller or meta.get("seller") == seller)
            and series.lower() in str(meta.get("product_name", "")).lower()
            and (not ground or meta.get("ground_type") == ground)
            and lo <= int(meta.get("product_price") or 0) <= hi)


def main(seed=20261029, out=OUT, exclude=()):
    """exclude: 이미 쓴 (series, ground, seller) 조합 — 과적합 확인용 새 세트에서 겹치지 않게 한다."""
    metas = chromadb.PersistentClient(path=str(ROOT / "backend/.chroma_store")) \
        .get_collection("soccer_shoes").get(limit=10000, include=["metadatas"])["metadatas"]
    rng = random.Random(seed)  # 질문 세트를 재현 가능하게 고정
    combos = [(s, sr, g, p) for s in SELLERS + [""] for sr in SERIES for g in GROUNDS + [""] for p in PRICES]
    rng.shuffle(combos)
    rows, seen = [], set(exclude)
    for seller, series, ground, (price_text, lo, hi) in combos:
        n_conditions = sum(map(bool, [seller, ground, price_text])) + 1
        # 조건 2~4개를 고르게: 4개 12문항, 3개 12문항, 2개 6문항
        quota = {4: 12, 3: 12, 2: 6}.get(n_conditions, 0)
        if sum(r["n_conditions"] == n_conditions for r in rows) >= quota or (series, ground, seller) in seen:
            continue
        gold = sum(matches(m, seller, series, ground, lo, hi) for m in metas)
        if gold < 2:
            continue
        rows.append({"id": f"Q{len(rows) + 1:02d}", "question": phrase(rng, seller, series, ground, price_text),
                     "seller": seller, "series": series, "ground_type": ground, "min_price": lo, "max_price": hi,
                     "n_conditions": n_conditions, "gold_matching_docs": gold})
        seen.add((series, ground, seller))
        if len(rows) == 30:
            break

    assert len(rows) == 30, len(rows)
    assert all(r["gold_matching_docs"] >= 2 for r in rows)
    assert {r["n_conditions"] for r in rows} == {2, 3, 4}
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
