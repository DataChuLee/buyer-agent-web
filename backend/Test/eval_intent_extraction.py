"""extract_conditions_and_intent 실제 LLM 정확도 측정 스크립트.

pytest 자동 수집 대상이 아니다 (파일명이 test_*.py가 아님) — 실제 OPENAI_API_KEY로
LLM을 호출하므로 비용이 들어 수동 실행 전용이다.

사용법: python Test/eval_intent_extraction.py
"""
from __future__ import annotations

import asyncio
import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

_api_key = os.environ.get("OPENAI_API_KEY")
if not _api_key or _api_key == "test-key":
    sys.exit(
        "OPENAI_API_KEY가 설정되어 있지 않습니다 (또는 유닛테스트용 더미 값입니다). "
        "실제 키로 환경변수를 설정한 뒤 다시 실행하세요."
    )

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

import Agent.LangGraph_buyeragent_with_personalization as buyer_graph  # noqa: E402
from Test.fixtures.intent_extraction_cases import INTENT_EXTRACTION_CASES  # noqa: E402


def _build_messages(history: list[tuple[str, str]], message: str) -> list:
    messages = []
    for role, content in history:
        messages.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))
    messages.append(HumanMessage(content=message))
    return messages


async def _run_case(case: dict) -> tuple[bool, str]:
    state = {
        "messages": _build_messages(case["history"], case["message"]),
        "intent": "",
        "user_conditions": {},
        "user_profile": {},
    }
    result = await buyer_graph.extract_conditions_and_intent(state)

    intent_ok = result.get("intent") == case["expected_intent"]
    capabilities_ok = set(result.get("requested_capabilities") or []) == set(case["expected_capabilities"])
    passed = intent_ok and capabilities_ok

    detail = (
        f"intent={result.get('intent')!r} (expected {case['expected_intent']!r}), "
        f"capabilities={result.get('requested_capabilities')!r} (expected {case['expected_capabilities']!r})"
    )
    return passed, detail


async def main() -> None:
    total = len(INTENT_EXTRACTION_CASES)
    passed_count = 0
    for case in INTENT_EXTRACTION_CASES:
        passed, detail = await _run_case(case)
        passed_count += int(passed)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {case['message']!r} — {detail}")

    accuracy = passed_count / total if total else 0.0
    print(f"\n{passed_count}/{total} passed ({accuracy:.0%})")


if __name__ == "__main__":
    asyncio.run(main())
