"""실험 4·5 평가 질문 60개(questions60.csv) 생성. 실행 전에 고정하고, 결과를 본 뒤에는 고치지 않는다.

- E01~E30: experiments/questions_draft.csv(1단계에서 승인). 애매한 8개는 승인한 정답(허용 답 여러 개)을 반영.
  E01·E13은 서비스 프롬프트 예시/기존 테스트 문장과 거의 같아(문자 2-gram 유사도 0.57~0.58) 뜻·정답은 두고 문장만 바꿈.
- E31~E60: 같은 범주 비율로 추가. 애매한 질문의 정답은 승인한 규칙을 그대로 따른다
  (필수 조건 부족 → ask, 상품명만 있는 '어때?' → product_analysis 또는 none, 체형 고민 → ask 또는 none,
   비지원 브랜드 → product_search 또는 none, 판매처 평판 → none).
- gold 형식: 허용 답을 '|'로 나열, 한 답 안의 기능 여러 개는 '+'(순서 무관).
"""
import csv
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

APPROVED = {"E13": "ask", "E14": "ask", "E15": "product_analysis|none", "E20": "ask",
            "E21": "product_analysis|none", "E22": "ask|none", "E23": "product_search|none", "E24": "none"}
REWORDED = {"E01": "TF 풋살화로 나이키 거 10만원대에서 골라줘", "E13": "나이키 걸로 하나 골라주고 판매처도 같이 알려줘"}
NEW = [
    # clear
    ("E31", "clear", "아디다스 15만원 이하 TF 풋살화 찾아줘", "product_search"),
    ("E32", "clear", "미즈노 20만원대 FG 축구화 추천 부탁해", "product_search"),
    ("E33", "clear", "나이키 10만원 이하 AG 아동용 축구화 있어?", "product_search"),
    ("E34", "clear", "모렐리아 네오 4 베타 판매하는 곳 알려줘", "seller_search"),
    ("E35", "clear", "프레데터 리그 TF 어디서 살 수 있어?", "seller_search"),
    ("E36", "clear", "레드사커에 있는 티엠포 레전드 10 분석 좀", "product_analysis"),
    ("E37", "clear", "퓨처 8 플레이 사이즈랑 가격 비교해줘", "product_analysis"),
    # multi
    ("E38", "multi", "미즈노 15만원 이하 HG 추천해주고 파는 곳도 알려줘", "product_search+seller_search"),
    ("E39", "multi", "코파 퓨어 3 판매처 찾아서 분석까지 해줘", "seller_search+product_analysis"),
    ("E40", "multi", "나이키 20만원 이하 TF로 추천하고 판매처 비교에 상세 분석까지", "product_search+seller_search+product_analysis"),
    ("E41", "multi", "아디다스 10만원대 FG 골라주고 그중에 하나 자세히 분석해줘", "product_search+product_analysis"),
    ("E42", "multi", "팬텀 6 엘리트 파는 데 알려주고 비교 분석도 부탁", "seller_search+product_analysis"),
    ("E43", "multi", "푸마 축구화 추천하고 판매처도 알려줘", "ask"),
    # ambiguous
    ("E44", "ambiguous", "아디다스 축구화 괜찮은 거 있어?", "ask"),
    ("E45", "ambiguous", "15만원대 FG 보여줘", "ask"),
    ("E46", "ambiguous", "AG용으로 하나 골라줘", "ask"),
    ("E47", "ambiguous", "어디서 사는 게 제일 싸?", "ask"),
    ("E48", "ambiguous", "이거 판매처 알려줘", "ask"),
    ("E49", "ambiguous", "사커붐에서 추천해줘", "ask"),
    ("E50", "ambiguous", "프레데터 괜찮아?", "product_analysis|none"),
    ("E51", "ambiguous", "머큐리얼이랑 팬텀 비교하면 어때?", "product_analysis|none"),
    ("E52", "ambiguous", "평발인데 어떤 축구화가 맞을까?", "ask|none"),
    ("E53", "ambiguous", "언더아머 20만원 이하 FG 있어?", "product_search|none"),
    ("E54", "ambiguous", "크레이지11 배송 빨라?", "none"),
    # none
    ("E55", "none", "천연잔디용이랑 인조잔디용은 뭐가 달라?", "none"),
    ("E56", "none", "축구화 사이즈는 평소보다 크게 신어야 해?", "none"),
    ("E57", "none", "가죽 축구화 관리는 어떻게 해?", "none"),
    ("E58", "none", "안녕! 반가워", "none"),
    ("E59", "none", "오늘 비 와서 경기 취소됐어", "none"),
    ("E60", "none", "축구화 길들이는 방법 있어?", "none"),
]
MAX_SIM = 0.45


def bigrams(s):
    s = re.sub(r"\s", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def sim(a, b):
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / max(1, len(A | B))


def reference_sentences():
    """서비스 프롬프트 예시와 기존 의도 분류 테스트 문장(S2를 다듬을 때 쓰였을 수 있는 문장)."""
    src = (ROOT / "backend/Agent/LangGraph_buyeragent_with_personalization.py").read_text(encoding="utf-8") + \
        (ROOT / "backend/Test/fixtures/intent_extraction_cases.py").read_text(encoding="utf-8")
    found = set(re.findall(r"'([^'\n]*[가-힣][^'\n]*)'", src)) | set(re.findall(r'"([^"\n]*[가-힣][^"\n]*)"', src))
    return {s for s in found if len(s) >= 6}


def main():
    draft = [r for r in csv.DictReader((HERE.parent / "questions_draft.csv").open(encoding="utf-8-sig")) if r["split"] == "eval"]
    rows = [{"id": r["id"], "category": r["category"], "question": REWORDED.get(r["id"], r["question"]),
             "gold": APPROVED.get(r["id"], r["gold_candidate"])} for r in draft]
    rows += [{"id": i, "category": c, "question": q, "gold": g} for i, c, q, g in NEW]
    refs = reference_sentences()
    for r in rows:
        best = max(refs, key=lambda s: sim(r["question"], s))
        r["max_ref_sim"] = round(sim(r["question"], best), 2)
        assert r["max_ref_sim"] < MAX_SIM, (r["id"], r["question"], best)
    assert len(rows) == 60 and len({r["id"] for r in rows}) == 60
    assert len({r["question"] for r in rows}) == 60
    valid = {"product_search", "seller_search", "product_analysis", "ask", "none"}
    assert all(set(part.split("+")) <= valid for r in rows for part in r["gold"].split("|"))
    with (HERE / "questions60.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print("wrote questions60.csv", Counter(r["category"] for r in rows))


if __name__ == "__main__":
    main()
