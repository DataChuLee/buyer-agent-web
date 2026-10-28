from __future__ import annotations

import re
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END
from langgraph.types import Command
from pydantic import BaseModel, Field


_ALL_COMPARISON_PATTERNS = ["모두", "모든", "전부", "전체", "다같이", "각각"]


def wants_all_comparison(message: str) -> bool:
    """Return whether the message asks to compare across every known candidate at once.

    e.g. "판매자 4곳 모두에서 비교해줘" — the user already knows the sellers/products
    and wants them all compared together, not narrowed down to a single one.
    """
    text = re.sub(r"\s+", " ", str(message or "").strip().lower())
    return any(pattern in text for pattern in _ALL_COMPARISON_PATTERNS)


class SupervisorDecision(BaseModel):
    next: Literal["product_search", "seller_search", "product_analysis", "ask_user", "FINISH"]
    remaining_order: list[Literal["product_search", "seller_search", "product_analysis"]] = Field(
        default_factory=list,
        description="이번 턴에 요청된 capability 중 아직 끝나지 않은 것들을, 지금 상황 기준으로 "
        "실행되어야 할 순서대로 다시 나열하세요(매 턴 새로 판단). 예: 아직 구체적인 상품/모델이 "
        "정해지지 않았다면 product_search를 가장 앞에 둡니다.",
    )
    question: str | None = Field(None, description="next가 ask_user일 때 사용자에게 물어볼 질문")


_SUPERVISOR_SYSTEM = """당신은 축구화/풋살화 쇼핑 에이전트의 supervisor입니다.

"이번 턴에 요청된 capability" 목록은 사용자가 이번 요청에서 실제로 명시한 의도이므로 절대적으로
존중해야 합니다. 아래 순서로 판단하세요.

1. "이번 턴에 요청된 capability" 중 past_steps에 아직 없는 것이 있으면 그중 하나를 선택하세요.
   요청되지 않은 capability는 고르지 마세요 — 예를 들어 사용자가 product_search만 요청했다면
   seller_search나 product_analysis를 임의로 끼워 넣지 마세요.
2. 요청된 capability를 모두 실행했다면 FINISH하세요.
2-1. `remaining_order`에는 아직 끝나지 않은 요청 capability 전부를 지금 실행돼야 할 순서대로
   나열하세요. 일반적인 쇼핑 흐름은 product_search(상품 확정) → seller_search(판매처 확인) →
   product_analysis(비교/분석) 순이지만, 대화 맥락상 이미 필요 없는 단계라면 건너뛰어도 됩니다.
   이 판단은 이전 턴 결과에 얽매이지 말고 지금 상황 기준으로 매번 다시 하세요.
3. 예외: "사용자 메시지"가 요청 목록에 없는 완전히 새로운 요청(예: 리뷰 취소 후 "그럼 판매처 검색해줘")을
   명시적으로 담고 있다면, 그 요청에 맞는 capability를 골라도 됩니다.
4. 다음 단계를 진행하기엔 정보가 부족하면 ask_user를 선택하세요(question에 질문 작성).

capability 설명:
- product_search: 시리즈/모델 추천
- seller_search: 어디서 파는지(판매처) 안내
- product_analysis: 특정 상품/판매처 상세 비교·분석

이미 past_steps에 있는 단계는 반복하지 마세요."""

_supervisor_llm = None


def _get_supervisor_classifier():
    global _supervisor_llm
    if _supervisor_llm is None:
        _supervisor_llm = ChatOpenAI(model="gpt-5.4-nano", temperature=0).with_structured_output(
            SupervisorDecision
        )
    return _supervisor_llm


def _last_user_message(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages", []) or []):
        if isinstance(message, HumanMessage):
            return str(message.content).strip()
    return ""


# 한 턴 안에서 Supervisor 루프가 무한히 돌지 않도록 하는 상한(무료/제품/분석 3단계 이상 반복될 일은 없음).
_MAX_STEPS_PER_TURN = 3


async def supervisor_node(state: dict[str, Any]) -> Command:
    past_steps = list(state.get("past_steps") or [])
    if len(past_steps) >= _MAX_STEPS_PER_TURN:
        return Command(update={"status": "done", "active_agent": None}, goto="queue_user_memory_save")

    message = _last_user_message(state)
    conditions = state.get("user_conditions") or {}
    context = (
        f"사용자 메시지: {message}\n"
        f"이번 턴에 요청된 capability: {state.get('requested_capabilities') or []}\n"
        f"이미 실행한 단계: {past_steps}\n"
        f"알고 있는 조건: {conditions}\n"
        f"이미 알고 있는 판매처가 있음: {bool(state.get('last_sellers') or state.get('sellers'))}\n"
        f"'모두/전부' 비교 요청 여부: {wants_all_comparison(message)}"
    )
    decision = await _get_supervisor_classifier().ainvoke(
        [SystemMessage(content=_SUPERVISOR_SYSTEM), HumanMessage(content=context)]
    )

    requested_capabilities = list(state.get("requested_capabilities") or [])
    remaining_requested = [step for step in requested_capabilities if step not in past_steps]

    # replan: 남은 요청 capability가 있으면, 이번 턴에 LLM이 다시 정렬한 순서(remaining_order)를
    # 우선 채택하고, 빠뜨린 항목은 기존 순서로 보충해 항상 그 첫 번째만 실행한다. LLM이 특정
    # capability 하나만 콕 집어 고르더라도(decision.next) 순서를 건너뛰어 채택하지 않는다 —
    # 순서 판단은 remaining_order를 통해서만 반영된다.
    if remaining_requested:
        if decision.next == "ask_user":
            next_step = "ask_user"
        else:
            ordered = [step for step in decision.remaining_order if step in remaining_requested]
            ordered += [step for step in remaining_requested if step not in ordered]
            next_step = ordered[0]
    elif requested_capabilities:
        # 원래 요청된 capability를 이미 다 실행했다면, 사용자가 새로 요청(reset 등으로
        # requested_capabilities가 비워진 경우)하지 않는 한 여기서 종료한다. reset은
        # requested_capabilities도 함께 비우므로 이 분기를 타지 않고 LLM 판단으로 넘어간다.
        next_step = "FINISH"
    elif decision.next in past_steps:
        # requested_capabilities가 비어있는 자유 판단 상황(reset 이후 등)에서는, 이미 실행한
        # 단계를 사용자가 다시 요청한 게 아니라면 반복 대신 종료한다.
        next_step = "FINISH"
    else:
        next_step = decision.next

    if next_step == "FINISH":
        return Command(update={"status": "done", "active_agent": None}, goto="queue_user_memory_save")
    if next_step == "ask_user":
        return Command(
            update={
                "messages": [AIMessage(content=decision.question or "조금 더 자세히 알려주세요.")],
                "status": "waiting_input",
                "active_agent": None,
                "question_options": None,
                "question_sequence": None,
            },
            goto=END,
        )

    node_by_step = {
        "product_search": "product_search_worker_node",
        "seller_search": "seller_search_worker_node",
        "product_analysis": "product_analysis_worker_node",
    }
    return Command(goto=node_by_step[next_step])
