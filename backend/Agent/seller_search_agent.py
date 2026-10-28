from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from Agent.product_search_agent import (
    BRAND_RULES,
    _extract_requested_price_range,
    _requested_brand_name,
    _requested_series_name,
    _strip_exclude_clause,
    extract_series_name,
    is_no_result_answer,
)
from Tools.crawl_and_index import load_raw_items_cache
from Tools.seller_normalization import normalize_seller_display
from Tools.seller_selection import (
    DOMAIN_TO_SELLER,
    SELLER_ORDER,
    parse_seller_price,
    supported_seller_from_url,
    validate_seller_candidate,
)


SELLER_DOMAINS = list(DOMAIN_TO_SELLER)


def _split_markdown_row(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _extract_markdown_link(value: str) -> str | None:
    if match := re.search(r"\[[^\]]+\]\(([^)]+)\)", str(value or "")):
        return match.group(1).strip()
    if match := re.search(r"https?://[^\s|)]+", str(value or "")):
        return match.group(0).strip()
    return None


def _normalize_header_cell(value: str) -> str:
    return re.sub(r"[\s_*`]+", "", str(value or "")).lower()


def _find_column(header: list[str], candidates: list[str]) -> int | None:
    normalized_candidates = [_normalize_header_cell(candidate) for candidate in candidates]
    for idx, cell in enumerate(header):
        normalized = _normalize_header_cell(cell)
        if normalized in normalized_candidates:
            return idx
        if any(candidate and candidate in normalized for candidate in normalized_candidates):
            return idx
    return None


def _is_separator_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in row if cell.strip())


def _derive_seller_description(status: str, price: str) -> str:
    parts = []
    if status and status not in {"-", "—"}:
        parts.append(status)
    if price and price not in {"-", "—"}:
        parts.append(f"최저가 {price}")
    return " · ".join(parts) or "판매 정보 확인 필요"


def _derive_seller_reason(name: str, status: str, price: str, explicit_reason: str) -> str:
    if explicit_reason and explicit_reason not in {"-", "—"}:
        return explicit_reason
    if price and price not in {"-", "—"}:
        return (
            f"{name}에서 현재 응답 기준 최저가 {price}가 확인되어 같은 제품의 "
            "판매처별 가격 비교 후보로 적합합니다. 실제 구매 전 옵션/사이즈별 "
            "재고와 최종 결제 금액을 확인하세요."
        )
    if status and status not in {"-", "—"}:
        return (
            f"{name}에서 관련 판매 페이지가 확인되어 구매 가능 여부를 확인할 후보입니다. "
            "실제 구매 전 옵션/사이즈별 재고와 최종 결제 금액을 확인하세요."
        )
    return (
        f"{name}은 지원 판매처에 포함되어 있어 후보로 표시했습니다. "
        "상세 상품명, 사이즈, 재고와 최종 가격은 판매처에서 다시 확인하세요."
    )


# format_product_search_results()와 같은 패턴: _build_cache_table()/_build_tavily_table()이
# 만드는 "N. 판매처명" 헤더 + "추천 이유:"/"URL:" 프로즈 블록을 결정적으로(LLM 호출 없이) 되짚는
# 파서. 판매 안 되는 판매처는 애초에 텍스트에 나오지 않으므로(호출측에서 필터링됨) 상태/가격을
# 헤더에서 분리하던 옛 로직은 필요 없다.
_SELLER_HEADER_RE = re.compile(r"^\s*\d+\.\s*(?P<name>.+?)\s*$")
_SELLER_FIELD_RE = re.compile(
    r"^\s*(추천 이유|상품명|판매가|정상가|판매 상태|사이즈|출처|URL)\s*:\s*(.*)$"
)


def _parse_seller_prose_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    current: dict | None = None
    for line in str(text or "").splitlines():
        if field_match := _SELLER_FIELD_RE.match(line):
            if current is None:
                continue
            label, value = field_match.group(1), field_match.group(2).strip()
            if label == "추천 이유":
                current["reason"] = value
            elif label == "상품명":
                current["product_name"] = value
            elif label == "판매가":
                current["sale_price"] = value
            elif label == "정상가":
                current["original_price"] = value
            elif label == "판매 상태":
                current["availability"] = value
            elif label == "사이즈":
                current["size"] = value
            elif label == "출처":
                current["source"] = value
            elif label == "URL":
                current["url"] = value
            continue
        if header_match := _SELLER_HEADER_RE.match(line):
            name = header_match.group("name").strip()
            if not name:
                continue
            if current:
                blocks.append(current)
            current = {
                "name": name,
                "reason": "",
                "product_name": "",
                "sale_price": "",
                "original_price": "",
                "availability": "",
                "size": "",
                "source": "",
                "url": "",
            }
    if current:
        blocks.append(current)

    parsed: list[dict] = []
    for block in blocks:
        name = block["name"]
        url = _extract_markdown_link(block["url"])
        if not url or supported_seller_from_url(url) != name:
            continue
        reason = block["reason"] or _derive_seller_reason(name, "", "", "")
        parsed.append(
            {
                "name": name,
                "description": reason,
                "why_recommended": reason,
                "url": url,
                "product_name": block["product_name"],
                "sale_price": parse_seller_price(block["sale_price"]),
                "original_price": parse_seller_price(block["original_price"]),
                "availability": block["availability"],
                "size": block["size"],
                "source": block["source"],
            }
        )
    return parsed


def parse_seller_markdown_table(text: str) -> list[dict]:
    if blocks := _parse_seller_prose_blocks(text):
        return blocks
    return _parse_seller_legacy_table(text)


_NO_SELLER_RESULT_PHRASES = (
    "판매처 검색에 사용할 검증된 상품명 또는 시리즈가 없습니다",
    "사용자가 지원 판매처를 모두 제외하여 검색할 판매처가 없습니다",
    "검증 가능한 판매 상품을 찾지 못했습니다",
    "판매처 검색 중 지원 판매처의 외부 검색을 모두 사용할 수 없었습니다",
)


def is_no_seller_result_answer(text: str) -> bool:
    """명시적인 판매처 0건/오류 응답을 카드 추출 입력과 구분한다."""
    return any(phrase in str(text or "") for phrase in _NO_SELLER_RESULT_PHRASES)


def _parse_seller_legacy_table(text: str) -> list[dict]:
    """과거 판매처 markdown 표(파이프 컬럼) 포맷 호환용 파서.

    현재 에이전트 응답은 더 이상 표를 만들지 않지만, 다른 경로로 여전히 이
    포맷의 텍스트가 들어올 수 있어 폴백으로 남겨둔다.
    """
    rows = [_split_markdown_row(line) for line in str(text or "").splitlines()]
    rows = [row for row in rows if row]
    header_index = None
    name_idx = status_idx = price_idx = reason_idx = link_idx = None
    for idx, row in enumerate(rows):
        maybe_name_idx = _find_column(row, ["판매처", "판매처명", "seller", "name"])
        maybe_link_idx = _find_column(row, ["바로가기", "url", "링크"])
        maybe_price_idx = _find_column(row, ["최저가", "가격", "판매가"])
        if maybe_name_idx is None or (maybe_link_idx is None and maybe_price_idx is None):
            continue
        header_index = idx
        name_idx = maybe_name_idx
        status_idx = _find_column(row, ["판매 여부", "검색 결과", "판매상태", "상태"])
        price_idx = maybe_price_idx
        reason_idx = _find_column(row, ["추천 이유", "이유"])
        link_idx = maybe_link_idx
        break
    if header_index is None:
        return []

    header = rows[header_index]
    parsed: list[dict] = []
    for row in rows[header_index + 1 :]:
        if _is_separator_row(row):
            continue
        if len(row) < len(header):
            continue

        name = row[name_idx].strip() if name_idx is not None else ""
        if not name:
            continue

        status = row[status_idx].strip() if status_idx is not None else "판매 중"
        if status in {"없음", "검색 결과 없음"} or any(
            word in status.lower() for word in ("품절", "판매 종료", "구매 불가", "sold out")
        ):
            continue

        price = row[price_idx].strip() if price_idx is not None else ""
        reason = row[reason_idx].strip() if reason_idx is not None else ""
        link_cell = row[link_idx].strip() if link_idx is not None else ""
        url = _extract_markdown_link(link_cell)
        if not url or supported_seller_from_url(url) != name:
            continue
        parsed_price = parse_seller_price(price)
        if parsed_price is None:
            continue
        description = _derive_seller_description(status, price)
        parsed.append(
            {
                "name": name,
                "description": description,
                "why_recommended": _derive_seller_reason(name, status, price, reason),
                "url": url,
                "sale_price": parsed_price,
                "original_price": None,
                "availability": "판매 중",
                "source": "legacy_markdown",
            }
        )
    return parsed


SELLER_SYSTEM = SystemMessage(content="""당신은 축구화 판매처 탐색 전문 에이전트입니다.
search_sellers 도구를 정확히 한 번 호출하세요. 도구가 반환한 텍스트가 최종 답변으로 그대로 쓰이므로,
도구 호출 뒤에는 그 텍스트를 다시 베껴 쓰거나 요약/수정하지 말고 짧게 '완료' 한 마디만 답하세요.""")

_CACHE_PREFIX = "[캐시 데이터 기준]"
_TAVILY_PREFIX = "[Tavily 검색 기준]"
_CACHE_FOOTER = "\n\n> 상품 상세 비교·분석이 필요하다면 Product Analysis 에이전트에게 문의하세요."
_TAVILY_FOOTER = "\n\n> 웹 검색 기반으로 가격·재고가 실제와 다를 수 있습니다."


def _finalize_seller_search_answer(tool_output: str) -> str:
    """search_sellers 도구 출력의 [캐시/Tavily 기준] 마커를 사람이 읽는 안내 문구로 바꾼다.

    과거엔 이 안내 문구를 LLM이 프롬프트 지침("결과가 [...]이면 마지막에: ...")대로 직접
    작성했는데, LLM에게 도구 결과를 "그대로 베껴 쓰라"고 시키는 것 자체가 gpt-4o-mini 같은
    소형 모델에서 반복 생성(같은 텍스트가 두 번 나옴) 문제를 일으켜(실사용 재현으로 확인)
    결정론적 후처리로 옮겼다.
    """
    if tool_output.startswith(_CACHE_PREFIX):
        return tool_output[len(_CACHE_PREFIX):].lstrip("\n") + _CACHE_FOOTER
    if tool_output.startswith(_TAVILY_PREFIX):
        return tool_output[len(_TAVILY_PREFIX):].lstrip("\n") + _TAVILY_FOOTER
    return tool_output


_TAVILY_SELLERS: dict[str, Any] = {}


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _result_text(result: dict[str, Any]) -> str:
    return "\n".join(str(result.get(key) or "") for key in ("title", "content", "raw_content", "snippet"))


def _product_matches(product_name: str, keyword: str) -> bool:
    requested_series = _requested_series_name(keyword)
    candidate_series = extract_series_name(product_name)
    if requested_series:
        return candidate_series == requested_series
    requested_brand = _requested_brand_name(keyword)
    if requested_brand:
        aliases = BRAND_RULES[requested_brand]
        return any(alias.lower() in product_name.lower() for alias in aliases)
    return bool(_compact_spaces(product_name))


def _extract_web_prices(text: str) -> tuple[int | None, int | None]:
    sale = original = None
    for label, value in re.findall(
        r"(판매가|할인가|세일가|정상가|소비자가)\s*[:：]?\s*([₩￦]?\s*[0-9][0-9, ]*\s*원?)",
        str(text or ""), re.IGNORECASE,
    ):
        price = parse_seller_price(value)
        if label in {"판매가", "할인가", "세일가"} and sale is None:
            sale = price
        elif label in {"정상가", "소비자가"} and original is None:
            original = price
    if sale is None and original is None:
        values = re.findall(r"([₩￦]?\s*[0-9]{1,3}(?:[, ][0-9]{3})+\s*원|[₩￦]?\s*[0-9]{5,7}\s*원)", str(text or ""))
        if values:
            sale = parse_seller_price(values[0])
    return sale, original


def normalize_seller_candidate(
    raw: Any,
    product_keyword: str,
    *,
    source: str,
    excluded_sellers: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "invalid_candidate"
    text = _result_text(raw)
    product_name = _compact_spaces(raw.get("product_name") or raw.get("raw_name") or raw.get("title") or "")
    url = _compact_spaces(raw.get("product_url") or raw.get("detail_url") or raw.get("source_url") or raw.get("url") or "")
    sale_price = raw.get("sale_price") if raw.get("sale_price") is not None else raw.get("product_price")
    original_price = raw.get("original_price") if raw.get("original_price") is not None else raw.get("consumer_price")
    if source == "web_search":
        parsed_sale, parsed_original = _extract_web_prices(text)
        sale_price = parsed_sale if sale_price is None else sale_price
        original_price = parsed_original if original_price is None else original_price
    availability = raw.get("availability") or raw.get("status")
    if availability is None and source == "raw_cache":
        availability = "판매 중"
    candidate = {
        "seller": normalize_seller_display(raw.get("seller", "")),
        "product_name": product_name,
        "product_url": url,
        "sale_price": sale_price,
        "original_price": original_price,
        "availability": availability or text,
        "size": raw.get("size") or raw.get("sizes") or raw.get("option") or raw.get("options"),
        "source": source,
        "product_match": _product_matches(product_name, product_keyword),
    }
    return validate_seller_candidate(candidate, excluded_sellers=excluded_sellers)


def _normalize_candidates(rows: Any, keyword: str, *, source: str, excluded_sellers: frozenset[str] = frozenset()) -> tuple[list[dict[str, Any]], dict[str, int]]:
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    if not isinstance(rows, list):
        rows = []
        rejected["corrupt_rows"] = 1
    for row in rows:
        candidate, reason = normalize_seller_candidate(row, keyword, source=source, excluded_sellers=excluded_sellers)
        if candidate is not None:
            accepted.append(candidate)
        else:
            key = reason or "invalid_candidate"
            rejected[key] = rejected.get(key, 0) + 1
    by_url: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in accepted:
        url_key = candidate["product_url"].rstrip("/")
        key = (candidate["seller"], url_key)
        previous = by_url.get(key)
        if previous is None or candidate["effective_price"] < previous["effective_price"]:
            by_url[key] = candidate
    by_product: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in by_url.values():
        name_key = re.sub(r"\W+", "", candidate["product_name"].lower())
        key = (candidate["seller"], name_key)
        previous = by_product.get(key)
        if previous is None or candidate["effective_price"] < previous["effective_price"]:
            by_product[key] = candidate
    candidates = sorted(by_product.values(), key=lambda row: (row["effective_price"], row["seller"], row["product_url"]))
    if len(accepted) != len(candidates):
        rejected["duplicate"] = len(accepted) - len(candidates)
    return candidates, rejected


def _format_seller_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "판매처 추천 목록\n\n검증 가능한 판매 상품을 찾지 못했습니다."
    lines = ["판매처 추천 목록", ""]
    for idx, row in enumerate(candidates, start=1):
        lines.extend([
            f"{idx}. {row['seller']}  ",
            f"상품명: {row['product_name']}  ",
        ])
        if row.get("sale_price") is not None:
            lines.append(f"판매가: {row['sale_price']:,}원  ")
        if row.get("original_price") is not None:
            lines.append(f"정상가: {row['original_price']:,}원  ")
        lines.extend([
            "판매 상태: 판매 중  ",
            f"사이즈: {row.get('size') or '상세 페이지 확인'}  ",
            f"출처: {row['source']}  ",
            "추천 이유: 검증된 상품 URL과 판매 가격이 확인되었습니다.  ",
            f"URL: {row['product_url']}",
            "",
        ])
    return "\n".join(lines).rstrip()


def _build_cache_table(items: list[dict], excluded_sellers: frozenset[str] = frozenset(), product_keyword: str = "") -> str:
    candidates, _ = _normalize_candidates(items, product_keyword, source="raw_cache", excluded_sellers=excluded_sellers)
    return _format_seller_candidates(candidates)


def _build_tavily_table(tavily_results: list[dict], excluded_sellers: frozenset[str] = frozenset(), product_keyword: str = "") -> str:
    candidates, _ = _normalize_candidates(tavily_results, product_keyword, source="web_search", excluded_sellers=excluded_sellers)
    return _format_seller_candidates(candidates)


def build_seller_search_query(
    product_keyword: str,
    min_price: int = 0,
    max_price: int = 9_999_999,
    rejected_sellers: list[str] | None = None,
) -> str:
    price_hint = f" {min_price // 10000}만원대" if 0 < min_price < 9_999_999 else ""
    rejected = [seller for seller in (rejected_sellers or []) if seller]
    exclusion = f" {' '.join(rejected)} 제외" if rejected else ""
    return _compact_spaces(f"{product_keyword}{price_hint} 구매 판매처{exclusion}")


def _get_tavily_seller(domain: str):
    if domain not in _TAVILY_SELLERS:
        from langchain_community.tools.tavily_search import TavilySearchResults

        _TAVILY_SELLERS[domain] = TavilySearchResults(
            max_results=3,
            search_depth="basic",
            include_domains=[domain],
        )
    return _TAVILY_SELLERS[domain]


async def _run_tavily_branch(domain: str, keyword: str, min_price: int, max_price: int) -> dict[str, Any]:
    seller = DOMAIN_TO_SELLER[domain]
    query = _compact_spaces(f"site:{domain} {build_seller_search_query(keyword, min_price, max_price)}")
    started = time.monotonic()
    try:
        results = await _get_tavily_seller(domain).ainvoke(query)
        return {
            "seller": seller,
            "status": "ok",
            "results": results if isinstance(results, list) else [],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:
        return {
            "seller": seller,
            "status": "error",
            "results": [],
            "error_type": type(exc).__name__,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


async def _run_tavily(
    keyword: str,
    min_price: int,
    max_price: int,
    excluded_sellers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    domains = [domain for domain, seller in DOMAIN_TO_SELLER.items() if seller not in excluded_sellers]
    branches = await asyncio.gather(
        *(_run_tavily_branch(domain, keyword, min_price, max_price) for domain in domains)
    )
    failed_sellers = [row["seller"] for row in branches if row["status"] == "error"]
    rows = [item for branch in branches for item in branch["results"]]
    candidates, rejected = _normalize_candidates(rows, keyword, source="web_search", excluded_sellers=excluded_sellers)
    if failed_sellers and len(failed_sellers) == len(branches):
        status = "error"
    elif failed_sellers:
        status = "partial_failure"
    elif candidates:
        status = "ok"
    else:
        status = "no_results"
    return {
        "search_status": status,
        "source": "web_search",
        "candidates": candidates,
        "failed_sellers": failed_sellers,
        "rejection_summary": rejected,
    }


_PRICE_PHRASE_RE = re.compile(r"\d+\s*만\s*원?\s*(?:대|이하|이상)|\d{5,7}\s*원?\s*대")


def _seller_search_keyword(query: str) -> str:
    # 가격 문구("10만원대")와 workers.py가 재시도 시 붙이는 exclude 절은 raw_items_cache의
    # 토큰 매칭에서 리터럴로 요구되면 안 되므로(product_name에 절대 나타나지 않는 문자열이라
    # 매칭이 항상 실패함) 여기서 제거하고, 가격은 별도로 _extract_requested_price_range가 처리한다.
    text = _strip_exclude_clause(query)
    text = _PRICE_PHRASE_RE.sub(" ", text)
    text = re.sub(r"(?:판매처|추천|구매|검색)", " ", text, flags=re.IGNORECASE)
    return _compact_spaces(text)


def _excluded_seller_names(query: str) -> frozenset[str]:
    """"exclude: A, B" 절에서 제외 대상 판매처명 집합을 뽑는다.

    그동안 이 절은 raw_items_cache 키워드 추출 시 벗겨내기만 하고 실제로 판매처를 걸러내는
    데는 쓰이지 않아서, "다른 판매처 없어?"(retry)를 물어도 항상 같은 4곳이 그대로 다시
    나오는 문제가 있었다(product_search의 exclude 절 미처리 버그와 같은 계열).
    """
    match = re.search(r"exclude\s*:\s*(.*)$", str(query or ""), re.IGNORECASE)
    if not match:
        return frozenset()
    names = {normalize_seller_display(part.strip()) for part in match.group(1).split(",") if part.strip()}
    return frozenset(names)


def _valid_product_keyword(query: str, keyword: str) -> bool:
    lowered = str(query or "").lower()
    if not keyword or is_no_result_answer(query):
        return False
    if re.search(r"search_status\s*[=:]\s*['\"]?(?:error|no_results)", lowered):
        return False
    if any(text in lowered for text in ("검색 실패", "검색 결과 없음", "상품을 찾지 못")):
        return False
    return _requested_series_name(keyword) is not None


def _status_answer(status: str, candidates: list[dict[str, Any]], failed_sellers: list[str]) -> str:
    if status == "error":
        return (
            "판매처 검색 중 지원 판매처의 외부 검색을 모두 사용할 수 없었습니다.\n\n"
            "검증되지 않은 판매처나 가격은 대신 생성하지 않았습니다."
        )
    body = _format_seller_candidates(candidates)
    if status == "partial_failure":
        body += "\n\n일부 판매처 검색 실패: " + ", ".join(failed_sellers)
    return body


async def run_seller_search_pipeline(query: str) -> dict[str, Any]:
    min_price, max_price = _extract_requested_price_range(query) or (0, 9_999_999)
    keyword = _seller_search_keyword(query)
    excluded_sellers = _excluded_seller_names(query)
    if not _valid_product_keyword(query, keyword):
        return {
            "search_status": "no_results",
            "source": "none",
            "candidates": [],
            "failed_sellers": [],
            "rejection_summary": {"invalid_product_input": 1},
            "answer": "판매처 검색에 사용할 검증된 상품명 또는 시리즈가 없습니다.",
        }
    if excluded_sellers.issuperset(SELLER_ORDER):
        return {
            "search_status": "no_results",
            "source": "none",
            "candidates": [],
            "failed_sellers": [],
            "rejection_summary": {"all_sellers_excluded": 1},
            "answer": "사용자가 지원 판매처를 모두 제외하여 검색할 판매처가 없습니다.",
        }
    cache_error = False
    try:
        cached = load_raw_items_cache(keyword, min_price, max_price)
    except Exception:
        cached = None
        cache_error = True
    if cached is not None:
        candidates, rejected = _normalize_candidates(cached, keyword, source="raw_cache", excluded_sellers=excluded_sellers)
        if candidates:
            return {
                "search_status": "ok",
                "source": "raw_cache",
                "candidates": candidates,
                "failed_sellers": [],
                "rejection_summary": rejected,
                "answer": _format_seller_candidates(candidates),
            }
    result = await _run_tavily(keyword, min_price, max_price, excluded_sellers)
    if cache_error:
        result["rejection_summary"]["cache_error"] = 1
    result["answer"] = _status_answer(result["search_status"], result["candidates"], result["failed_sellers"])
    return result


@tool
async def search_sellers(query: str) -> str:
    """검증된 상품 시리즈를 캐시 우선으로 지원 판매처에서 검색합니다."""
    result = await run_seller_search_pipeline(query)
    prefix = _CACHE_PREFIX if result["source"] == "raw_cache" else _TAVILY_PREFIX
    return f"{prefix}\n{result['answer']}"


_SELLER_SEARCH_REACT_AGENT = None


def _get_seller_search_react_agent():
    global _SELLER_SEARCH_REACT_AGENT
    if _SELLER_SEARCH_REACT_AGENT is None:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent

        _SELLER_SEARCH_REACT_AGENT = create_react_agent(
            ChatOpenAI(model="gpt-4o-mini", temperature=0),
            tools=[search_sellers],
            prompt=SELLER_SYSTEM,
        )
    return _SELLER_SEARCH_REACT_AGENT


async def seller_search_agent(query: str, user_profile: dict | None = None, config=None) -> str:
    del user_profile
    # config(콜백 포함)를 넘겨야 상위 그래프의 astream_events가 이 react agent 내부 LLM의
    # 토큰 스트림까지 이벤트로 잡아낼 수 있다.
    result = await _get_seller_search_react_agent().ainvoke(
        {"messages": [HumanMessage(content=query)]}, config=config
    )
    # product_search_agent()와 동일한 이유로 모델의 최종 메시지 대신 search_sellers 도구가
    # 반환한 원문(ToolMessage)을 직접 사용한다.
    for message in reversed(result["messages"]):
        if isinstance(message, ToolMessage):
            return _finalize_seller_search_answer(str(message.content))
    return result["messages"][-1].content
