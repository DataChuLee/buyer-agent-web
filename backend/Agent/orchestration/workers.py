from __future__ import annotations

import re
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.func import task
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from Agent.orchestration.supervisor import wants_all_comparison
from Agent.product_analysis_agent import ProductAnalysisResult, product_analysis_agent
from Agent.product_search_agent import (
    _extract_requested_price_range,
    _query_requests_surface,
    parse_product_markdown_table,
    product_search_agent,
)
from Agent.seller_search_agent import parse_seller_markdown_table, seller_search_agent
from Tools.rag_search import build_analysis_cards_from_docs


async def _run_search(task_fn, *args):
    # ponytail: langgraph @task를 interrupt() 재개 + astream_events(/chat/stream)와 함께 쓸 때,
    # 이전에 스케줄된 동일 task 기록에 RETURN/ERROR 쓰기가 없으면 langgraph가 None으로 조용히
    # resolve하는 내부 엣지케이스가 있다(langgraph/pregel/_runner.py _acall_impl). 재현: ainvoke는
    # 정상, astream_events만 크래시 + 한번 발생하면 같은 스레드의 다음 턴도 내용 무관하게 재발.
    # task 캐시가 깨졌을 때만 원본 함수로 직접 재실행해 우회한다(langgraph 업그레이드로 해결되면 제거).
    # 첫 시도(@task)는 이 엣지케이스에서도 실제로는 끝까지 실행되어(LLM 호출/스트리밍 포함) 이미
    # 사용자에게 답변이 스트리밍된 뒤 반환값만 None으로 유실된 것이므로, 재실행은 mute=True로 넘겨
    # 두 번째 실행이 같은 텍스트를 또 스트리밍하지 않게 막는다. 주의: config=None으로는 안 막힌다 —
    # LangChain이 콜백을 contextvar로 자동 전파해 None을 넘겨도 조상 실행의 콜백을 그대로 물려받는다
    # (직접 검증함). 각 _search는 mute일 때 config={"callbacks": []}로 콜백을 명시적으로 비워야
    # astream_events에 두 번째 실행의 이벤트가 안 잡힌다.
    result = await task_fn(*args)
    if result is None:
        result = await task_fn.func(*args, True)
    return result


_MAX_RETRIES_PER_PENDING_STEP = 2

_SELLER_ALIASES = {
    "crazy11": ("크레이지11", "crazy11", "crazy 11"),
    "soccerboom": ("사커붐", "soccerboom", "soccer boom"),
    "redsoccer": ("레드사커", "redsoccer", "red soccer"),
    "cafostore": ("카포스토어", "cafostore", "cafo store"),
}
_SELLER_DISPLAY = {
    "crazy11": "크레이지11",
    "soccerboom": "사커붐",
    "redsoccer": "레드사커",
    "cafostore": "카포스토어",
}

_ORDINAL_WORDS = {
    "첫": 1, "첫번째": 1, "첫 번째": 1,
    "두": 2, "두번째": 2, "두 번째": 2,
    "세": 3, "세번째": 3, "세 번째": 3,
    "네": 4, "네번째": 4, "네 번째": 4,
    "다섯": 5, "다섯번째": 5, "다섯 번째": 5,
}
_PRODUCT_PRONOUN_PATTERNS = [
    "저 제품", "이 제품", "그 제품", "해당 제품", "저 상품", "이 상품", "그 상품",
    "앞서 말한", "앞서서 말한", "이전에 말한", "아까 말한", "말씀하신", "언급한",
]
_MULTI_CANDIDATE_REFERENCE_PATTERNS = [
    "저 중에서", "그 중에서", "저것들 중", "그것들 중", "위에서 말한", "앞서 말한", "앞서서 말한",
]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _last_user_message(state: dict[str, Any]) -> str:
    for message in reversed(state.get("messages", []) or []):
        if isinstance(message, HumanMessage):
            return str(message.content).strip()
    return ""


def _candidate_name(card: dict | None) -> str:
    if not card:
        return ""
    return str(card.get("name") or card.get("product_name") or card.get("title") or "").strip()


def _extract_ordinal_index(text: str) -> int | None:
    compact = re.sub(r"\s+", "", str(text or ""))
    if match := re.search(r"(\d+)\s*(?:번째|번)", str(text or "")):
        value = int(match.group(1))
        return value - 1 if value > 0 else None
    for word, value in _ORDINAL_WORDS.items():
        if word.replace(" ", "") in compact:
            return value - 1
    return None


def _last_product_cards(state: dict[str, Any]) -> list[dict]:
    cards = state.get("last_products") or state.get("products") or []
    return [dict(card) for card in cards if isinstance(card, dict)]


def _resolve_product_reference(state: dict[str, Any]) -> dict | None:
    cards = _last_product_cards(state)
    if not cards:
        return None
    message = _last_user_message(state)
    ordinal = _extract_ordinal_index(message)
    if ordinal is not None and 0 <= ordinal < len(cards):
        return cards[ordinal]
    if any(pattern in message for pattern in _PRODUCT_PRONOUN_PATTERNS):
        selected = state.get("selected_series_card")
        if isinstance(selected, dict) and _candidate_name(selected):
            return dict(selected)
        return cards[0]
    return None


def _product_search_url(name: str) -> str:
    query = re.sub(r"\s+", "+", f"{name} 축구화".strip())
    return f"https://search.naver.com/search.naver?query={query}"


def _ensure_product_links(products: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for product in products:
        item = dict(product)
        name = _candidate_name(item)
        if name and not item.get("url"):
            item["url"] = _product_search_url(name)
        enriched.append(item)
    return enriched


def _normalize_product_cards(products: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for product in products:
        item = dict(product)
        for field in ("features", "recommendation", "price", "url"):
            if item.get(field) is None:
                item[field] = ""
        normalized.append(item)
    return _ensure_product_links(normalized)


def _normalize_cards(value: Any) -> list[dict]:
    if not value:
        return []
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _enrich_seller_cards(sellers: list[dict], response_text: str) -> list[dict]:
    detailed = parse_seller_markdown_table(response_text)
    if not detailed:
        return sellers
    if not sellers:
        return detailed

    details_by_name = {
        _normalize_text(card.get("name")): card
        for card in detailed
        if isinstance(card, dict) and card.get("name")
    }
    enriched: list[dict] = []
    for seller in sellers:
        item = dict(seller)
        detail = details_by_name.get(_normalize_text(item.get("name")))
        if detail:
            for field in ("description", "why_recommended", "url"):
                if not item.get(field) and detail.get(field):
                    item[field] = detail[field]
        enriched.append(item)
    return enriched


def _seller_payload(card: dict) -> dict:
    seller_name = _candidate_name(card)
    for code, aliases in _SELLER_ALIASES.items():
        if any(_normalize_text(alias) == _normalize_text(seller_name) for alias in aliases):
            return {"display_name": _SELLER_DISPLAY[code], "crawler_code": code}
    return {"display_name": seller_name, "crawler_code": seller_name}


def _latest_message_seller_crawlers(state: dict[str, Any]) -> list[str]:
    from Tools.seller_normalization import find_seller_displays_in_query, normalize_seller_crawler

    crawlers: list[str] = []
    for display in find_seller_displays_in_query(_last_user_message(state)):
        crawler = normalize_seller_crawler(display)
        if crawler and crawler not in crawlers:
            crawlers.append(crawler)
    return crawlers


def _fallback_numbered_cards(text: str) -> list[dict]:
    cards: list[dict] = []
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if match := re.match(r"^(?:\*\*)?\s*(?:\[?(\d+)\]?\.?)\s+(.+?)(?:\*\*)?$", stripped):
            cards.append({"name": match.group(2).strip(" -*")})
    return cards


def _analysis_conditions(state: dict[str, Any]) -> dict[str, Any]:
    conditions = dict(state.get("user_conditions") or {})
    selected_series = state.get("selected_series")
    selected_seller = state.get("selected_seller") or {}
    if selected_series:
        conditions["product_name"] = selected_series
    message = _last_user_message(state)
    excluded_sellers = _extract_excluded_sellers(message)
    if excluded_sellers:
        remaining = [code for code in _SELLER_ALIASES if code not in excluded_sellers]
        conditions["seller"] = ", ".join(remaining)
        return conditions
    message_sellers = _latest_message_seller_crawlers(state)
    if message_sellers:
        conditions["seller"] = ", ".join(message_sellers)
    elif wants_all_comparison(message):
        # 이전 턴에서 새어든 단일 seller 조건을 지워 product_analysis_agent의
        # "seller 없음 → 전체 판매처 비교" 폴백이 동작하게 한다.
        conditions.pop("seller", None)
    elif selected_seller.get("crawler_code"):
        conditions["seller"] = selected_seller["crawler_code"]
    return conditions


def _product_key(card: dict) -> str:
    seller = str(card.get("seller") or "").strip()
    name = _candidate_name(card)
    if seller and name:
        return f"{seller}|{name}"
    return str(card.get("product_key") or card.get("product_url") or card.get("url") or name).strip()


async def _parse_products(text: str) -> list[dict] | None:
    from Agent.product_search_agent import is_no_result_answer

    if is_no_result_answer(text):
        return []
    table_products = parse_product_markdown_table(text)
    if table_products:
        return table_products
    try:
        result: ParsedProducts = await _products_parser().ainvoke(
            [
                SystemMessage(content=(
                    "Extract recommended football shoe SERIES/MODEL cards from the text. "
                    "Each card must represent a series or model line (e.g. '나이키 머큐리얼 베이퍼 시리즈'), "
                    "NOT individual SKUs, specific colorways, or size variants. "
                    "The 'name' field must be a series/model name only — strip out any size numbers, "
                    "edition suffixes, or colorway names."
                )),
                HumanMessage(content=text),
            ]
        )
        return [item.model_dump() for item in result.products]
    except Exception:
        return None


async def _parse_sellers(text: str) -> list[dict] | None:
    table_sellers = parse_seller_markdown_table(text)
    if table_sellers:
        return table_sellers
    try:
        list_section = text
        marker_idx = text.find("추천 목록")
        if marker_idx != -1:
            list_section = text[marker_idx:]
        result: ParsedSellers = await _sellers_parser().ainvoke(
            [
                SystemMessage(content=(
                    "Extract seller cards from the '추천 목록' section only. "
                    "Each numbered entry is one seller. "
                    "Fields: name (판매처 이름), description (설명 field content), "
                    "why_recommended (추천 이유 field content), url (링크 field URL). "
                    "Each seller name must appear EXACTLY ONCE — "
                    "if the same name appears multiple times, keep only the first occurrence."
                )),
                HumanMessage(content=list_section),
            ]
        )
        seen: set[str] = set()
        unique: list[dict] = []
        for item in result.sellers:
            key = item.name.strip().lower()
            if key not in seen:
                seen.add(key)
                unique.append(item.model_dump())
        return unique or None
    except Exception:
        return None


class ProductItem(BaseModel):
    name: str
    features: str | None = None
    recommendation: str | None = None
    price: str | None = None
    url: str | None = None


class ParsedProducts(BaseModel):
    products: list[ProductItem]


class SellerItem(BaseModel):
    name: str
    description: str | None = None
    why_recommended: str | None = None
    url: str | None = None


class ParsedSellers(BaseModel):
    sellers: list[SellerItem]


_products_parser_llm = None
_sellers_parser_llm = None


def _products_parser():
    global _products_parser_llm
    if _products_parser_llm is None:
        _products_parser_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(ParsedProducts)
    return _products_parser_llm


def _sellers_parser():
    global _sellers_parser_llm
    if _sellers_parser_llm is None:
        _sellers_parser_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(ParsedSellers)
    return _sellers_parser_llm


# ── Resume 응답 해석 (LangGraph interrupt() 로 재개된 사용자 메시지 처리) ──────
class PendingResolution(BaseModel):
    action: Literal["select", "retry", "reset", "condition_update", "question"]
    selected_indices: list[int] = Field(default_factory=list)
    message: str | None = None
    grounded: bool = Field(
        True,
        description="question 답변이 지금 보여준 카드 데이터만으로 답변 가능하면 True, 카드에 없는 정보를 "
        "지어내야 한다면 False(이 경우 message는 비워도 됨 — 안내 문구는 코드가 채운다).",
    )
    followup_capabilities: list[Literal["product_search", "seller_search", "product_analysis"]] = Field(
        default_factory=list,
        description="select와 함께 메시지에 섞여 있는, 선택 이후 이어서 처리해야 할 새로운 요청 capability. "
        "예: '이거 어디서 파는지도 알려줘' → seller_search. select가 아니거나 추가 요청이 없으면 빈 리스트.",
    )


_resolution_classifier_llm = None


def _get_resolution_classifier():
    global _resolution_classifier_llm
    if _resolution_classifier_llm is None:
        _resolution_classifier_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(
            PendingResolution
        )
    return _resolution_classifier_llm


_RESOLUTION_SYSTEM = """사용자에게 후보 카드 목록이 표시되어 있고, 사용자는 자유롭게 응답할 수 있습니다.
사용자 메시지를 보고 다음 중 하나로 분류하세요.

- select: 카드 중 하나(또는 여러 개)를 선택하는 것 같은 경우. selected_indices에 0-based 인덱스를 채우세요(여러 개 가능).
  선택과 함께 "이거 어디서 파는지도 알려줘", "이것도 분석해줘", "다른 시리즈도 추천해줘"처럼 **선택 이후 이어서
  처리해야 할 새로운 요청**이 메시지에 같이 있으면 `followup_capabilities`에 해당 capability
  (product_search/seller_search/product_analysis)를 채우세요. 단순 선택만 있으면 빈 리스트로 두세요.
- retry: 지금 보여준 카드들이 마음에 안 들어서 다른 후보를 다시 보고 싶어함.
- condition_update: 브랜드/예산/지면/판매처/사이즈 등 검색 조건을 새로 말하거나 바꿈 (예: "10만원대로", "풋살화 말고 축구화",
  "크레이지11 말고 나머지 판매처에서", "판매처 4곳 모두 비교해줘", "사이즈 265 있어?", "265 사이즈로 볼 수 있어?").
  **지금 보고 있는 것과 같은 주제(같은 시리즈/상품)를 유지한 채 조건만 조정하는 경우는 이쪽입니다** — 판매처를
  바꾸거나 제외해달라는 요청, 특정 사이즈로 다시 찾아달라는 요청도 여기 포함됩니다(사이즈 재고 여부는 지금 보여준
  카드 텍스트만으로 정확히 답할 수 없으므로 question이 아니라 실제 재검색인 condition_update로 처리하세요).
- reset: 조건을 바꾸는 게 아니라 지금 하던 것 자체를 완전히 그만두고 싶어함 (예: "아 됐고 그냥 판매처만 검색해줘",
  "처음부터 다시 할래"). 같은 주제를 이어가며 조건만 조정하는 요청은 reset이 아니라 condition_update입니다.
- question: 카드 목록 자체에 대한 질문 (예: "거기서는 안 팔아?"). message에 답변을 채우세요. **답변은 반드시 지금
  보여준 후보 카드에 실제로 있는 정보만 사용하세요** — 카드에 없는 정보(예: 판매처 정보가 없는 카드 목록에서
  "어디서 파는지" 같은 질문)는 지어내지 말고 `grounded`를 false로 설정하세요.

카드 목록에 없는 내용은 지어내지 마세요. 확실하지 않으면 retry를 선택하세요."""

_UNGROUNDED_QUESTION_FALLBACK = "그 정보는 지금 보여드린 후보만으로는 확인하기 어려워요. 선택하시면 다음 단계에서 확인해드릴게요."

_SELLER_EXCLUSION_PATTERN = re.compile(r"말고|빼고|제외")


def _extract_excluded_sellers(message: str) -> list[str]:
    """"크레이지11 말고 나머지 판매처에서" 같은 제외 표현에서 제외 대상 판매처의 crawler_code를 추출한다.

    `ExtractedConditions.seller`/`_extract_explicit_product_conditions`는 단일 포함 값만 표현할 수 있어
    "이거 빼고 나머지" 같은 제외 의미를 담지 못한다 — 이 헬퍼로 여집합(나머지 판매처)을 계산해 보완한다.
    """
    if not _SELLER_EXCLUSION_PATTERN.search(str(message or "")):
        return []
    normalized = _normalize_text(message)
    return [
        code
        for code, aliases in _SELLER_ALIASES.items()
        if any(_normalize_text(alias) in normalized for alias in aliases)
    ]


def _cards_summary(cards: list[dict]) -> str:
    lines = []
    for index, card in enumerate(cards):
        name = _candidate_name(card)
        seller = card.get("seller") or name
        price = card.get("price") or ""
        size = card.get("size") or ""
        lines.append(f"{index}: {name} / 판매처={seller} / 가격={price} / 사이즈={size}")
    return "\n".join(lines)


async def _resolve_resume(message: str, cards: list[dict]) -> PendingResolution:
    # 순수 서수("1", "1번")만 LLM 호출 없이 즉시 처리 — 자유 응답을 막지 않는 좁은 예외.
    if match := re.fullmatch(r"\s*(\d+)\s*번?\s*", str(message or "")):
        index = int(match.group(1)) - 1
        if 0 <= index < len(cards):
            return PendingResolution(action="select", selected_indices=[index])

    try:
        return await _get_resolution_classifier().ainvoke(
            [
                SystemMessage(content=_RESOLUTION_SYSTEM),
                HumanMessage(content=f"후보 카드:\n{_cards_summary(cards)}\n\n사용자 메시지: {message}"),
            ]
        )
    except Exception:
        return PendingResolution(action="retry")


def _reset_fields() -> dict[str, Any]:
    return {
        "past_steps": [],
        # requested_capabilities도 함께 비운다 — 원래 요청이 이제 의미가 없어졌으므로,
        # supervisor_node가 "이미 요청된 걸 다 끝냈으니 FINISH" 규칙에 걸리지 않고 새 메시지를
        # 자유롭게 재해석하게 한다.
        "requested_capabilities": [],
        "selected_series": None,
        "selected_series_card": None,
        "selected_seller": None,
        "rejected_series": [],
        "rejected_sellers": [],
        "rejected_product_keys": [],
        "orchestration_retry_count": 0,
        "status": "checking",
        "active_agent": None,
    }


async def _apply_condition_update(state: dict[str, Any], message: str) -> dict[str, Any]:
    # 순환 import(메인 그래프 모듈이 이 워커 모듈을 import)를 피하기 위한 지연 import.
    from Agent.LangGraph_buyeragent_with_personalization import (
        ExtractionResult,
        _extract_explicit_product_conditions,
        _merge_product_conditions,
        llm,
    )

    explicit_conditions = _extract_explicit_product_conditions(message)
    extracted_conditions = explicit_conditions
    if not explicit_conditions:
        extractor = llm.with_structured_output(ExtractionResult)
        cond_result: ExtractionResult = await extractor.ainvoke(
            [
                SystemMessage(content="Extract only the product condition values from the user's reply. Do not infer intent."),
                HumanMessage(content=message),
            ]
        )
        extracted_conditions = cond_result.conditions.model_dump()
    updated = _merge_product_conditions(state.get("user_conditions", {}), extracted_conditions, explicit_conditions, message)

    excluded = _extract_excluded_sellers(message)
    if excluded:
        remaining = [code for code in _SELLER_ALIASES if code not in excluded]
        updated["seller"] = ", ".join(remaining)
    return updated


def _merge_requested_capabilities(state: dict[str, Any], extra: list[str]) -> list[str]:
    """requested_capabilities(override 방식 state 필드)에 새 capability를 기존 값 유지한 채 dedup 추가."""
    return list(dict.fromkeys([*(state.get("requested_capabilities") or []), *extra]))


def _ensure_product_analysis_requested(state: dict[str, Any]) -> list[str]:
    """seller_search 완료 후 항상 product_analysis로 이어지도록 requested_capabilities에 추가한다.

    리뷰 카드가 "상세 분석에 사용할 판매처를 선택해주세요"라고 고지하므로, 판매처 선택이
    끝나면 원래 요청 여부와 무관하게 product_analysis로 이어지는 게 맞다.
    """
    return _merge_requested_capabilities(state, ["product_analysis"])


def _ensure_seller_search_requested(state: dict[str, Any], extra: list[str] | None = None) -> list[str]:
    """product_search 완료 후 항상 seller_search로 이어지도록 requested_capabilities에 추가한다.

    리뷰 카드가 "다음 단계에서 사용할 시리즈를 선택해주세요"라고 고지하므로, 시리즈 선택이
    끝나면 원래 요청 여부와 무관하게 seller_search로 이어지는 게 맞다(위 seller_search →
    product_analysis 체이닝과 동일한 패턴).
    """
    return _merge_requested_capabilities(state, [*(extra or []), "seller_search"])


# ── Worker 노드 ──────────────────────────────────────────────────────────
async def product_search_worker_node(state: dict[str, Any], config: RunnableConfig) -> Command:
    conditions = dict(state.get("user_conditions", {}) or {})
    message = _last_user_message(state)
    if any(pattern in message for pattern in _MULTI_CANDIDATE_REFERENCE_PATTERNS):
        # "저 중에서"류 표현이라도 이번 메시지가 budget/surface처럼 조건을 실제로 좁히면(예: "저
        # 중에서 10만원대이고 공격수에게 적합한 시리즈는 뭐야") 후보 범위를 넓히려는 게 아니라
        # 좁히려는 요청이므로 brand를 지우지 않는다. 무조건 지우면 시리즈명도 없는 쿼리가 되어
        # 캐시를 못 타고 매번 라이브 Tavily 검색으로 빠져 결과가 턴마다 들쭉날쭉해졌다.
        narrows_conditions = bool(_extract_requested_price_range(message)) or _query_requests_surface(message)
        if not narrows_conditions:
            conditions.pop("brand", None)

    @task(name="product_search_search")
    async def _search(rejected_series: list[str], mute: bool = False) -> tuple[list[dict], str]:
        # interrupt() 재개 시 노드 함수 전체가 처음부터 다시 실행되므로, @task 없이는 이 검색이
        # resume마다(단순 select 응답에서도) 다시 실행되어 사용자가 실제로 본 cards와 다른 결과가
        # 나올 수 있다. @task는 같은 인자의 호출을 체크포인트에서 재현(memoize)해 이를 막는다.
        query_parts = [
            str(conditions[key])
            for key in ["brand", "budget", "surface", "position", "age_group", "product_name"]
            if conditions.get(key)
        ]
        rejected_all = [*(state.get("rejected_series") or []), *rejected_series]
        if rejected_all:
            query_parts.append(f"exclude: {', '.join(rejected_all)}")
        query = (" ".join(query_parts).strip() or message or "축구화") + " 축구화 추천"
        del mute
        # product_search_agent()가 이제 모델의 생성 텍스트가 아니라 도구(ToolMessage) 원문을
        # 반환하므로(모델에게 "베껴 쓰라"고 시키면 gpt-4o-mini가 짧은 텍스트조차 반복 생성하는
        # 문제가 실사용에서 확인됨), 모델의 스트리밍 자체가 더 이상 필요 없다. config={"callbacks":
        # []}로 항상 스트리밍을 꺼서 화면에 모델이 생성한(신뢰할 수 없는) 텍스트가 잠깐이라도
        # 노출되지 않게 한다 — product_analysis_worker_node와 동일하게 progress→done만 사용.
        response = await product_search_agent(
            query, user_profile=state.get("user_profile") or {}, config={"callbacks": []}
        )
        parsed = await _parse_products(str(response))
        cards = _normalize_product_cards(_normalize_cards(parsed) or _fallback_numbered_cards(str(response)))
        return cards, str(response)

    cards, response = await _run_search(_search, [])
    past = [*state.get("past_steps", []), "product_search"]
    if not cards:
        return Command(
            update={
                "messages": [AIMessage(content=response)],
                "products": None,
                "last_products": None,
                "past_steps": past,
                "active_agent": "product_search",
                "status": "done",
                "error": None,
            },
            goto="supervisor_node",
        )

    retry_count = 0
    rejected_series: list[str] = []
    while True:
        resume = interrupt({
            "type": "ps_review",
            "message": "추천 후보 중 다음 단계에서 사용할 시리즈를 선택해주세요.",
            "answer": response,
            "options": [_candidate_name(c) for c in cards if _candidate_name(c)] or None,
            "cards": cards or None,
            "resume_mode": "natural_language",
        })
        resolution = await _resolve_resume(resume, cards)

        if resolution.action == "reset":
            return Command(
                update={**_reset_fields(), "messages": [HumanMessage(content=resume)]},
                goto="supervisor_node",
            )
        if resolution.action == "question":
            response = resolution.message if (resolution.grounded and resolution.message) else _UNGROUNDED_QUESTION_FALLBACK
            continue
        if resolution.action == "condition_update":
            conditions = await _apply_condition_update(state, resume)
            # 회귀: LLM 분류기가 "저 시리즈 말고 다른 건 없어?"처럼 사실상 retry인 메시지를
            # condition_update로 분류하는 경우가 있는데(실사용 확인), 이 분기는 retry와 달리
            # 지금 보여준 카드를 제외 목록에 넣지 않아 조건이 실제로 안 바뀌면 같은 카드가 그대로
            # 다시 나왔다. retry와 동일하게 항상 제외 목록에 반영해 이 경로로 와도 안전하게 한다.
            rejected_series.extend(_candidate_name(c) for c in cards if _candidate_name(c))
            cards, response = await _run_search(_search, rejected_series)
            if not cards:
                return Command(
                    update={
                        "messages": [AIMessage(content=response)],
                        "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                        "past_steps": past,
                        "active_agent": "product_search",
                        "status": "done",
                    },
                    goto="supervisor_node",
                )
            continue
        if resolution.action == "retry":
            retry_count += 1
            if retry_count > _MAX_RETRIES_PER_PENDING_STEP:
                return Command(
                    update={
                        "messages": [AIMessage(content="같은 조건에서는 더 보여줄 후보가 부족해요. 예산, 브랜드, 지면 조건을 조금 넓혀서 다시 요청해주세요.")],
                        "active_agent": "product_search",
                        "status": "done",
                    },
                    goto="supervisor_node",
                )
            rejected_series.extend(_candidate_name(c) for c in cards if _candidate_name(c))
            cards, response = await _run_search(_search, rejected_series)
            continue

        indices = [i for i in resolution.selected_indices if 0 <= i < len(cards)]
        if not indices:
            continue
        selected = cards[indices[0]]
        selected_name = _candidate_name(selected)
        return Command(
            update={
                # 다음 단계(다른 요청 capability나 supervisor의 FINISH)가 새 메시지를 남기지
                # 않을 수 있으므로, select 시점에 반드시 확인 메시지를 남겨 응답이 비지 않게 한다.
                "messages": [AIMessage(content=f"'{selected_name}' 시리즈로 확인했습니다.")],
                "selected_series_card": selected,
                "selected_series": selected_name,
                "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                "past_steps": past,
                "active_agent": "product_search",
                "status": "done",
                "requested_capabilities": _ensure_seller_search_requested(state, resolution.followup_capabilities),
            },
            goto="supervisor_node",
        )


async def seller_search_worker_node(state: dict[str, Any], config: RunnableConfig) -> Command:
    message = _last_user_message(state)
    selected_series = state.get("selected_series")
    conditions = dict(state.get("user_conditions", {}) or {})
    referenced_product = _resolve_product_reference(state)
    if referenced_product:
        selected_series = _candidate_name(referenced_product)
        if selected_series:
            conditions["product_name"] = selected_series
    base = selected_series or conditions.get("product_name") or conditions.get("brand") or message or "축구화"

    @task(name="seller_search_search")
    async def _search(rejected_sellers: list[str], mute: bool = False) -> tuple[list[dict], str]:
        rejected_all = [*(state.get("rejected_sellers") or []), *rejected_sellers]
        condition_parts = [str(conditions[key]) for key in ["budget", "surface"] if conditions.get(key)]
        query = f"{base} {' '.join(condition_parts)} 판매처 추천" if condition_parts else f"{base} 판매처 추천"
        if rejected_all:
            query += f" exclude: {', '.join(rejected_all)}"
        del mute
        # product_search_search와 동일한 이유로 항상 스트리밍을 끈다(위 주석 참조).
        response = await seller_search_agent(
            query, user_profile=state.get("user_profile") or {}, config={"callbacks": []}
        )
        parsed = await _parse_sellers(str(response))
        cards = _enrich_seller_cards(_normalize_cards(parsed), str(response))
        return cards, str(response)

    cards, response = await _run_search(_search, [])
    past = [*state.get("past_steps", []), "seller_search"]
    common_update = {
        "sellers": cards or None,
        "last_sellers": cards or None,
        "selected_series": selected_series or state.get("selected_series"),
        "selected_series_card": referenced_product or state.get("selected_series_card"),
        "past_steps": past,
        "active_agent": "seller_search",
        "error": None,
    }

    if not cards or wants_all_comparison(message):
        return Command(
            update={
                **common_update,
                "messages": [AIMessage(content=response)],
                "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                "status": "done",
                "requested_capabilities": _ensure_product_analysis_requested(state),
            },
            goto="supervisor_node",
        )

    retry_count = 0
    rejected_sellers: list[str] = []
    while True:
        resume = interrupt({
            "type": "ss_review",
            "message": "상세 분석에 사용할 판매처를 선택해주세요.",
            "answer": response,
            "options": [_candidate_name(c) for c in cards if _candidate_name(c)] or None,
            "cards": cards or None,
            "resume_mode": "natural_language",
        })
        resolution = await _resolve_resume(resume, cards)

        if resolution.action == "reset":
            return Command(
                update={**_reset_fields(), "messages": [HumanMessage(content=resume)]},
                goto="supervisor_node",
            )
        if resolution.action == "question":
            response = resolution.message if (resolution.grounded and resolution.message) else _UNGROUNDED_QUESTION_FALLBACK
            continue
        if resolution.action == "condition_update":
            conditions = await _apply_condition_update(state, resume)
            # product_search_worker_node와 동일한 이유(회귀: "다른 판매처 없어?"류 메시지가
            # condition_update로 오분류될 수 있음)로, 이 분기에서도 지금 보여준 판매처를 제외
            # 목록에 반영한다. 단, "4곳 모두 비교해줘"는 지금 보여준 걸 포함해서 전부 보고 싶다는
            # 뜻이므로 제외하면 안 된다(wants_all_comparison이면 스킵).
            if not wants_all_comparison(resume):
                rejected_sellers.extend(str(c.get("name") or c.get("seller") or "") for c in cards)
            cards, response = await _run_search(_search, rejected_sellers)
            common_update = {
                "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                "past_steps": past,
                "active_agent": "seller_search",
            }
            if not cards or wants_all_comparison(resume):
                return Command(
                    update={
                        **common_update,
                        "messages": [AIMessage(content=response)],
                        "status": "done",
                        "requested_capabilities": _ensure_product_analysis_requested(state),
                    },
                    goto="supervisor_node",
                )
            continue
        if resolution.action == "retry":
            retry_count += 1
            if retry_count > _MAX_RETRIES_PER_PENDING_STEP:
                return Command(
                    update={
                        "messages": [AIMessage(content="같은 조건에서는 더 보여줄 판매처가 부족해요. 조건을 넓혀서 다시 요청해주세요.")],
                        "active_agent": "seller_search",
                        "status": "done",
                    },
                    goto="supervisor_node",
                )
            rejected_sellers.extend(str(c.get("name") or c.get("seller") or "") for c in cards)
            cards, response = await _run_search(_search, rejected_sellers)
            continue

        indices = [i for i in resolution.selected_indices if 0 <= i < len(cards)]
        if not indices:
            continue
        selected_payloads = [_seller_payload(cards[i]) for i in indices]
        if len(selected_payloads) >= 2:
            crawler_codes = [payload["crawler_code"] for payload in selected_payloads if payload.get("crawler_code")]
            display_names = ", ".join(payload["display_name"] for payload in selected_payloads)
            return Command(
                update={
                    # 다음 단계가 새 메시지를 남기지 않을 수 있으므로 select 시점에 확인 메시지를 남긴다.
                    "messages": [AIMessage(content=f"{display_names}로 확인했습니다.")],
                    "selected_seller": None,
                    "user_conditions": {
                        **(state.get("user_conditions") or {}),
                        **conditions,
                        "seller": ", ".join(dict.fromkeys(crawler_codes)),
                    },
                    "past_steps": past,
                    "active_agent": "seller_search",
                    "status": "done",
                    "requested_capabilities": _merge_requested_capabilities(
                        state, [*resolution.followup_capabilities, "product_analysis"]
                    ),
                },
                goto="supervisor_node",
            )
        return Command(
            update={
                "messages": [AIMessage(content=f"'{selected_payloads[0]['display_name']}'로 확인했습니다.")],
                "selected_seller": selected_payloads[0],
                "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                "past_steps": past,
                "active_agent": "seller_search",
                "status": "done",
                "requested_capabilities": _merge_requested_capabilities(
                    state, [*resolution.followup_capabilities, "product_analysis"]
                ),
            },
            goto="supervisor_node",
        )


async def product_analysis_worker_node(state: dict[str, Any]) -> Command:
    message = _last_user_message(state)
    conditions = _analysis_conditions(state)
    referenced_product = _resolve_product_reference(state)
    if referenced_product:
        referenced_name = _candidate_name(referenced_product)
        if referenced_name:
            conditions["product_name"] = referenced_name
            state = {**state, "selected_series": referenced_name, "selected_series_card": referenced_product}
    selected_seller = state.get("selected_seller") or {}
    selected_series = state.get("selected_series") or conditions.get("product_name") or message or "축구화"

    def _build_query(current_conditions: dict[str, Any], latest_message: str) -> str:
        # "모두/전부 비교" 요청이면 이전에 선택했던 단일 판매처(selected_seller)를 쿼리 텍스트에
        # 다시 박아 넣지 않는다 — product_analysis_agent._extract_sellers()가 conditions["seller"]
        # 뿐 아니라 쿼리 텍스트에서도 판매처명을 스캔하므로, 여기서 새어들면 conditions에서 seller를
        # 지워도 여전히 그 판매처로만 좁혀진다.
        seller_display = None
        if not wants_all_comparison(latest_message):
            raw_seller = current_conditions.get("seller") or selected_seller.get("display_name")
            if raw_seller:
                # conditions["seller"]는 crawler_code(들)일 수 있으므로(예: 판매처 제외 시 여집합을
                # 콤마로 합침) 자연어 문장에 어울리게 한글 표시명으로 변환한다.
                tokens = [token.strip() for token in re.split(r"[,/]", raw_seller) if token.strip()]
                seller_display = ", ".join(_SELLER_DISPLAY.get(token, token) for token in tokens)
        return f"{seller_display + '에서 ' if seller_display else ''}{selected_series} 상세 분석"

    exclude_keys = set(state.get("rejected_product_keys") or state.get("shown_product_keys") or [])

    @task(name="product_analysis_search")
    async def _search(
        current_conditions: dict[str, Any], exclude: set[str], search_query: str, mute: bool = False
    ) -> tuple[list[dict], str]:
        del mute  # product_analysis_agent는 config/스트리밍 콜백을 안 받으므로 관련 없음
        analysis_result = await product_analysis_agent(
            search_query,
            user_profile=state.get("user_profile") or {},
            conditions=current_conditions,
            return_result=True,
            original_query=search_query,
            exclude_keys=exclude,
        )
        if isinstance(analysis_result, ProductAnalysisResult):
            response_text = analysis_result.answer
            docs = analysis_result.docs
        else:
            response_text = str(analysis_result)
            docs = []
        result_cards = _normalize_cards(build_analysis_cards_from_docs(docs, limit=3)) if docs else []
        return result_cards, str(response_text)

    query = _build_query(conditions, message)
    cards, response = await _run_search(_search, conditions, exclude_keys, query)
    past = [*state.get("past_steps", []), "product_analysis"]
    base_update = {
        "messages": [AIMessage(content=response)],
        "analysis": cards or None,
        "last_analysis": cards or None,
        "shown_product_keys": [_product_key(c) for c in cards] or list(exclude_keys),
        "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
        "past_steps": past,
        "active_agent": "product_analysis",
        "error": None,
    }

    if not cards or wants_all_comparison(message):
        return Command(update={**base_update, "status": "done"}, goto="supervisor_node")

    retry_count = 0
    rejected_keys: list[str] = []
    while True:
        resume = interrupt({
            "type": "pa_review",
            "message": "분석 결과 중 원하는 상품을 선택해주세요.",
            "answer": response,
            "options": [_candidate_name(c) for c in cards if _candidate_name(c)] or None,
            "cards": cards or None,
            "resume_mode": "natural_language",
        })
        resolution = await _resolve_resume(resume, cards)

        if resolution.action == "reset":
            return Command(
                update={**_reset_fields(), "messages": [HumanMessage(content=resume)]},
                goto="supervisor_node",
            )
        if resolution.action == "question":
            response = resolution.message if (resolution.grounded and resolution.message) else _UNGROUNDED_QUESTION_FALLBACK
            continue
        if resolution.action == "condition_update":
            updated_conditions = await _apply_condition_update(state, resume)
            # 회귀: 메인 그래프의 의도 추출 LLM이 판매처명을 엉뚱한 필드(surface 등)로 오분류하면
            # user_conditions에 seller가 아예 안 남아, "사이즈 265 있어?"처럼 판매처와 무관한
            # 조건 변경 메시지에도 이미 좁혀둔 판매처 범위가 조용히 전체 판매처로 넓어졌다.
            # _apply_condition_update가 seller를 못 채웠고 "모두 비교" 요청도 아니면, 이번 진입
            # 시점에 _analysis_conditions()가 이미 계산해둔 seller를 그대로 유지한다.
            if (
                not wants_all_comparison(resume)
                and not updated_conditions.get("seller")
                and conditions.get("seller")
            ):
                updated_conditions["seller"] = conditions["seller"]
            conditions = updated_conditions
            query = _build_query(conditions, resume)
            cards, response = await _run_search(_search, conditions, exclude_keys | set(rejected_keys), query)
            common_update = {
                "user_conditions": {**(state.get("user_conditions") or {}), **conditions},
                "past_steps": past,
                "active_agent": "product_analysis",
            }
            if not cards or wants_all_comparison(resume):
                return Command(
                    update={**common_update, "messages": [AIMessage(content=response)], "status": "done"},
                    goto="supervisor_node",
                )
            continue
        if resolution.action == "retry":
            retry_count += 1
            if retry_count > _MAX_RETRIES_PER_PENDING_STEP:
                return Command(
                    update={
                        "messages": [AIMessage(content="같은 조건에서는 더 보여줄 후보가 부족해요. 가격대나 판매처 조건을 넓혀서 다시 요청해주세요.")],
                        "active_agent": "product_analysis",
                        "status": "done",
                    },
                    goto="supervisor_node",
                )
            rejected_keys.extend(_product_key(c) for c in cards if _product_key(c))
            cards, response = await _run_search(_search, conditions, exclude_keys | set(rejected_keys), query)
            continue

        indices = [i for i in resolution.selected_indices if 0 <= i < len(cards)]
        if not indices:
            continue
        selected = cards[indices[0]]
        return Command(
            update={
                "selected_product": selected,
                "status": "waiting_input",
                "active_agent": "purchase_prepare",
                "purchase_status": "awaiting_purchase_info",
                "purchase_missing_fields": ["size", "recipient_name", "phone", "address", "detail_address"],
                "messages": [AIMessage(content="선택한 상품을 저장했어요. 구매를 진행하려면 사이즈와 배송 정보를 알려주세요.")],
            },
            goto="purchase_prepare_node",
        )
