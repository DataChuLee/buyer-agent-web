"""README용 실험 결과 차트(SVG, 라이트/다크) 생성. 값은 결과 파일에서 직접 계산한다(손으로 옮기지 않음).

실행: backend/venv/Scripts/python.exe experiments/make_charts.py
출력: docs/images/experiments-light.svg, docs/images/experiments-dark.svg
- 형태: 실험마다 단위가 달라 패널을 나눈 small multiples(이중 축 금지). 패널마다 기준선 vs 개선 후 막대 + 95% 신뢰구간.
- 색: dataviz 기본 팔레트의 범주 1·2번(파랑=기준선, 주황=개선 후). validate_palette.js로 라이트/다크 모두 통과 확인.
- 표준 라이브러리만 사용(새 의존성 없음).
"""
import json
import statistics
import sys
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE / "exp1_selfquery"))
sys.path.insert(0, str(HERE / "exp2_graders"))
from exp1 import bootstrap_ci, percentile, wilson  # noqa: E402
from exp2 import mean_ci  # noqa: E402

THEMES = {
    "light": {"surface": "#fcfcfb", "text1": "#0b0b0b", "text2": "#52514e", "grid": "#e4e3df", "axis": "#c3c2b7",
              "s1": "#2a78d6", "s2": "#eb6834"},
    "dark": {"surface": "#1a1a19", "text1": "#f0efec", "text2": "#c3c2b7", "grid": "#2e2e2b", "axis": "#4a4a46",
             "s1": "#3987e5", "s2": "#d95926"},
}


def rows(path):
    return [json.loads(l) for l in open(HERE / path, encoding="utf-8")]


def p50(values, scale=1.0):
    lo, hi = bootstrap_ci(values, .5)
    return percentile(values, .5) / scale, lo / scale, hi / scale


def rate(k, n):
    lo, hi = wilson(k, n)
    return 100 * k / n, 100 * lo, 100 * hi


def mean_claims(rs):
    counts = [len(r["judge_unsupported"]) for r in rs if r["context"]]
    lo, hi = mean_ci(counts)
    return statistics.mean(counts), lo, hi


def build_panels():
    e1 = rows("exp1_selfquery/results.jsonl")
    e2 = rows("exp2_graders/judged.jsonl")
    e2b = rows("exp2b_fix/judged.jsonl")
    e3 = [r for r in rows("exp3_cache/results.jsonl") + rows("exp3_cache/results_retry.jsonl") if r["registered_after_miss"]]
    e3b = [r for r in rows("exp3_cache/negative.jsonl") if r["request_index"] > 0]
    e4 = [r for r in rows("exp4_routing/results.jsonl") if r["version"] == "old"] + rows("exp4_routing/results_new_fixed.jsonl")
    e5 = rows("exp5_single_agent/results_combined_fixed.jsonl")

    def acc(rs):
        return rate(sum(r["correct"] for r in rs), len(rs))

    def zero(rs):
        return rate(sum(r["n_docs"] == 0 for r in rs), len(rs))

    return [
        ("① 검색 지연 p50", "ms · 30문항 × 3회", "ms", 0,
         ("SelfQuery(LLM 필터)", p50([r["total_ms"] for r in e1 if r["method"] == "before"])),
         ("메타데이터 직접 필터", p50([r["total_ms"] for r in e1 if r["method"] == "after"]))),
        ("① 결과 0개인 검색", "% · 30문항 × 3회", "%", 1,
         ("SelfQuery", zero([r for r in e1 if r["method"] == "before"])),
         ("직접 필터", zero([r for r in e1 if r["method"] == "after"]))),
        ("② LLM 채점(CRAG·Self-RAG) 효과", "답변당 근거 없는 주장 · gpt-4o 판정 · p=1.0", "개", 2,
         ("채점 끔", mean_claims([r for r in e2 if r["arm"] == "off"])),
         ("채점 켬", mean_claims([r for r in e2 if r["arm"] == "on"]))),
        ("② 원인(프롬프트) 수정 + 결정적 검사", "답변당 근거 없는 주장 · p<0.0001", "개", 2,
         ("당시 서비스", mean_claims([r for r in e2b if r["arm"] == "A"])),
         ("수정 후", mean_claims([r for r in e2b if r["arm"] == "C"]))),
        ("③ 크롤 캐시: 사용자 응답 p50", "초 · 판매처 4 × 시리즈 3 × 2 = 24쌍", "초", 1,
         ("캐시 없음(실제 크롤)", p50([r["miss"]["total_ms"] for r in e3], 1000)),
         ("캐시 적중", p50([r["hit"]["total_ms"] for r in e3], 1000))),
        ("③ 판매처 장애 중 응답 p50", "초 · 실측 타임아웃 주입 · 연속 요청 n=10", "초", 1,
         ("실패 캐시 없음", p50([r["total_ms"] for r in e3b if r["arm"] == "before"], 1000)),
         ("실패 캐시", p50([r["total_ms"] for r in e3b if r["arm"] == "after"], 1000))),
        ("④ 라우팅 정답률", "% · 60문항 × 3회 · p=0.0001", "%", 1,
         ("단일 의도(옛 버전)", acc([r for r in e4 if r["version"] == "old"])),
         ("다중 기능 + 조건 게이트", acc([r for r in e4 if r["version"] == "new"]))),
        ("⑤ 단일 에이전트 vs 현재 구조", "정답률 % · 60문항 × 3회 · p=0.0117", "%", 1,
         ("단일 ReAct 에이전트", acc([r for r in e5 if r["arm"] == "s1"])),
         ("라우터 + Supervisor", acc([r for r in e5 if r["arm"] == "s2"]))),
    ]


def nice_max(v, unit):
    """눈금 4칸으로 v를 덮는 가장 작은 '깔끔한' 최댓값. 퍼센트는 100을 넘기지 않는다."""
    if unit == "%" and v > 50:
        return 100, 25
    ticks = sorted(s * m for s in (1, 2, 2.5, 5) for m in (0.1, 1, 10, 100, 1000, 10000))
    tick = next(t for t in ticks if t * 4 >= v * 1.08)
    return tick * 4, tick


def fmt(v, digits):
    return f"{v:,.{digits}f}"


def render(theme, panels):
    t = THEMES[theme]
    font = "Pretendard, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif"
    W, PW, PH, COLS, TOP = 960, 450, 230, 2, 70
    H = TOP + PH * ((len(panels) + 1) // COLS) + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{font}" role="img" '
           f'aria-label="Buyer Agent 실험 결과: 실험별 기준선과 개선 후 비교, 95% 신뢰구간 포함">',
           f'<rect width="{W}" height="{H}" fill="{t["surface"]}"/>',
           f'<text x="24" y="32" font-size="18" font-weight="700" fill="{t["text1"]}">같은 조건으로 다시 측정한 개선 전후</text>',
           f'<text x="24" y="54" font-size="12" fill="{t["text2"]}">막대 = 측정값, 선 = 95% 신뢰구간 · 측정일 2026-10-29 · 근거: experiments/결과_정리.md</text>']
    # 범례(계열 2개: 색만으로 구분하지 않도록 막대 아래 이름도 표기)
    lx = W - 260
    for i, (name, key) in enumerate((("기준선", "s1"), ("개선 후 / 현재", "s2"))):
        x = lx + i * 110
        out.append(f'<rect x="{x}" y="22" width="12" height="12" rx="2" fill="{t[key]}"/>'
                   f'<text x="{x + 18}" y="32" font-size="12" fill="{t["text2"]}">{name}</text>')
    for idx, (title, sub, unit, digits, a, b) in enumerate(panels):
        px, py = 24 + (idx % COLS) * (PW + 12), TOP + (idx // COLS) * PH
        chart_top, chart_bottom, left = py + 52, py + PH - 46, px + 48
        vmax, tick = nice_max(max(a[1][2], b[1][2]), unit)
        y = lambda v: chart_bottom - (chart_bottom - chart_top) * v / vmax  # noqa: E731
        out.append(f'<text x="{px}" y="{py + 18}" font-size="14" font-weight="700" fill="{t["text1"]}">{escape(title)}</text>'
                   f'<text x="{px}" y="{py + 36}" font-size="11" fill="{t["text2"]}">{escape(sub)}</text>')
        for k in range(5):
            gv = tick * k
            gy = y(gv)
            out.append(f'<line x1="{left}" x2="{px + PW - 16}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{t["grid" if k else "axis"]}" stroke-width="1"/>'
                       f'<text x="{left - 6}" y="{gy + 4:.1f}" font-size="10" text-anchor="end" fill="{t["text2"]}">{fmt(gv, 0 if gv >= 10 or gv == 0 else 1)}</text>')
        span = px + PW - 16 - left
        for j, ((label, (v, lo, hi)), key) in enumerate(((a, "s1"), (b, "s2"))):
            cx = left + span * (0.3 + 0.4 * j)
            bw, top = 72, y(v)
            h = max(chart_bottom - top, 0.0)
            r = min(4, h)
            # 위쪽 모서리만 4px 둥글게, 아래는 기준선에 붙임
            out.append(f'<path d="M{cx - bw / 2:.1f},{chart_bottom:.1f} V{top + r:.1f} Q{cx - bw / 2:.1f},{top:.1f} {cx - bw / 2 + r:.1f},{top:.1f} '
                       f'H{cx + bw / 2 - r:.1f} Q{cx + bw / 2:.1f},{top:.1f} {cx + bw / 2:.1f},{top + r:.1f} V{chart_bottom:.1f} Z" fill="{t[key]}">'
                       f'<title>{escape(label)}: {fmt(v, digits)}{unit} (95% CI {fmt(lo, digits)}~{fmt(hi, digits)})</title></path>')
            ylo, yhi = y(lo), y(hi)
            out.append(f'<g stroke="{t["text2"]}" stroke-width="2"><line x1="{cx:.1f}" x2="{cx:.1f}" y1="{ylo:.1f}" y2="{yhi:.1f}"/>'
                       f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{yhi:.1f}" y2="{yhi:.1f}"/>'
                       f'<line x1="{cx - 6:.1f}" x2="{cx + 6:.1f}" y1="{ylo:.1f}" y2="{ylo:.1f}"/></g>')
            out.append(f'<text x="{cx:.1f}" y="{min(top, yhi) - 8:.1f}" font-size="13" font-weight="700" text-anchor="middle" fill="{t["text1"]}">{fmt(v, digits)}{unit}</text>'
                       f'<text x="{cx:.1f}" y="{chart_bottom + 18:.1f}" font-size="11" text-anchor="middle" fill="{t["text2"]}">{escape(label)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    panels = build_panels()
    dest = ROOT / "docs/images"
    dest.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        (dest / f"experiments-{theme}.svg").write_text(render(theme, panels), encoding="utf-8")
    for title, _, unit, digits, a, b in panels:
        print(f"{title}: {a[0]} {a[1][0]:.{digits}f}{unit} -> {b[0]} {b[1][0]:.{digits}f}{unit}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
