from __future__ import annotations

from typing import Literal, TypedDict


AgentStep = Literal["product_search", "seller_search", "product_analysis"]
PendingActionType = Literal["ps_review", "ss_review", "pa_review"]


class PendingAction(TypedDict, total=False):
    type: PendingActionType
    message: str
    answer: str | None
    options: list[str] | None
    cards: list[dict] | None
    resume_mode: str
