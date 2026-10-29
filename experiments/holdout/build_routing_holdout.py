"""과적합 확인용 라우팅 질문 30개(holdout/routing_questions.csv). 실험 4·5 평가셋을 보고 고친 규칙(HG 지면, '퓨처' 표기,
supervisor 순서)이 처음 보는 문장에서도 통하는지 보려는 세트다. 실행 전에 고정한다.

- 정답은 실험 4와 같은 승인 규칙(필수 조건 부족 → ask 등)을 그대로 적용한다.
- 서비스 프롬프트 예시·기존 테스트 문장, 그리고 실험 4의 60문항 모두와 문자 2-gram 유사도 0.45 미만을 assert한다.
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exp4_routing"))
from build_questions import MAX_SIM, reference_sentences, sim  # noqa: E402

ROWS = [
    # clear — 지면·표기 변형을 일부러 섞음
    ("H01", "clear", "나이키 HG 15만원 이하로 찾아줘", "product_search"),
    ("H02", "clear", "MG용 아디다스 축구화 20만원대 추천", "product_search"),
    ("H03", "clear", "푸마 IC 실내화 10만원 이하 있으면 보여줘", "product_search"),
    ("H04", "clear", "퓨처 9 프로 어디서 팔아?", "seller_search"),
    ("H05", "clear", "퓨쳐 얼티밋 파는 데 알려줘", "seller_search"),
    ("H06", "clear", "Mercurial Vapor 16 판매처 찾아줘", "seller_search"),
    ("H07", "clear", "울트라 5 플레이 가격 비교 분석 부탁해", "product_analysis"),
    ("H08", "clear", "카포스토어 모렐리아 2 재팬 분석해줘", "product_analysis"),
    # multi
    ("H09", "multi", "아디다스 HG 20만원 이하 골라주고 어디서 사는지도", "product_search+seller_search"),
    ("H10", "multi", "미즈노 MG 15만원대 추천하고 그중 하나 분석까지", "product_search+product_analysis"),
    ("H11", "multi", "퓨처 7 플레이 판매처 찾고 상세 분석도 해줘", "seller_search+product_analysis"),
    ("H12", "multi", "푸마 FG 10만원대로 고르고 파는 곳 비교에 분석까지 전부", "product_search+seller_search+product_analysis"),
    ("H13", "multi", "F50 리그 어디서 파는지랑 분석 같이 알려줘", "seller_search+product_analysis"),
    ("H14", "multi", "나이키 축구화 골라주고 분석도 해줘", "ask"),
    # ambiguous
    ("H15", "ambiguous", "HG 구장에서 신을 만한 거 골라줘", "ask"),
    ("H16", "ambiguous", "10만원 안쪽으로 괜찮은 거", "ask"),
    ("H17", "ambiguous", "미즈노 거 뭐 있어?", "ask"),
    ("H18", "ambiguous", "그거 어디서 팔아?", "ask"),
    ("H19", "ambiguous", "레드사커에서 하나 골라줘", "ask"),
    ("H20", "ambiguous", "티엠포 어때?", "product_analysis|none"),
    ("H21", "ambiguous", "칼발인데 맞는 거 있을까", "ask|none"),
    ("H22", "ambiguous", "뉴발란스 HG 20만원 이하 있어?", "product_search|none"),
    # none
    ("H23", "none", "HG랑 FG 스터드 모양 차이가 뭐야?", "none"),
    ("H24", "none", "인조잔디에서 오래 신으려면 뭘 조심해?", "none"),
    ("H25", "none", "축구화 냄새 없애는 법", "none"),
    ("H26", "none", "고마워 덕분에 잘 골랐어", "none"),
    ("H27", "none", "내일 조기축구 가는데 설렌다", "none"),
    ("H28", "none", "풋살장 바닥은 보통 뭐야?", "none"),
    ("H29", "none", "축구화 끈은 몇 번째 구멍까지 묶어?", "none"),
    ("H30", "none", "너 이름이 뭐야?", "none"),
]


def main():
    refs = reference_sentences() | {r["question"] for r in csv.DictReader((HERE.parent / "exp4_routing/questions60.csv").open(encoding="utf-8-sig"))}
    out = []
    for i, c, q, g in ROWS:
        best = max(refs, key=lambda s: sim(q, s))
        assert sim(q, best) < MAX_SIM, (i, q, best, round(sim(q, best), 2))
        out.append({"id": i, "category": c, "question": q, "gold": g, "max_ref_sim": round(sim(q, best), 2)})
    assert len({r["question"] for r in out}) == 30
    with (HERE / "routing_questions.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print("wrote routing_questions.csv (30)")


if __name__ == "__main__":
    main()
