from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from Tools.seller_normalization import normalize_seller_display


DOMAIN_TO_SELLER = {
    "crazy11.co.kr": "크레이지11",
    "soccerboom.co.kr": "사커붐",
    "redsoccer.co.kr": "레드사커",
    "capostore.co.kr": "카포스토어",
}
SELLER_ORDER = ["크레이지11", "사커붐", "레드사커", "카포스토어"]
SELLER_URL = {
    seller: f"https://{domain}" for domain, seller in DOMAIN_TO_SELLER.items()
}
MIN_VALID_SELLER_PRICE = 20_000
MAX_VALID_SELLER_PRICE = 9_999_999

_UNAVAILABLE_TERMS = (
    "품절",
    "판매 종료",
    "판매종료",
    "판매 중지",
    "판매중지",
    "구매 불가",
    "구매불가",
    "접근 불가",
    "접근불가",
    "접근 실패",
    "접근실패",
    "not found",
    "404",
    "sold out",
    "unavailable",
    "discontinued",
)


def parse_seller_price(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = int(value)
    else:
        text = str(value).strip()
        match = re.search(r"(\d{1,3}(?:[ ,]\d{3})+|\d{4,7})", text)
        if not match:
            return None
        price = int(re.sub(r"[^0-9]", "", match.group(1)))
    if not MIN_VALID_SELLER_PRICE <= price <= MAX_VALID_SELLER_PRICE:
        return None
    return price


def supported_seller_from_url(url: Any) -> str | None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    for domain, seller in DOMAIN_TO_SELLER.items():
        if host == domain or host.endswith(f".{domain}"):
            return seller
    return None


def is_available_status(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return False
    return not any(term in text for term in _UNAVAILABLE_TERMS)


def validate_seller_candidate(
    candidate: Any,
    *,
    excluded_sellers: frozenset[str] = frozenset(),
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(candidate, dict):
        return None, "invalid_candidate"

    url = str(
        candidate.get("product_url")
        or candidate.get("detail_url")
        or candidate.get("url")
        or ""
    ).strip()
    if not url:
        return None, "missing_url"
    seller = supported_seller_from_url(url)
    if seller is None:
        return None, "unsupported_seller"
    if seller in excluded_sellers:
        return None, "excluded_seller"
    if candidate.get("product_match") is False:
        return None, "product_mismatch"

    availability = candidate.get("availability")
    if not is_available_status(availability):
        return None, "unavailable"

    sale_price = parse_seller_price(candidate.get("sale_price"))
    original_price = parse_seller_price(candidate.get("original_price"))
    effective_price = sale_price if sale_price is not None else original_price
    if effective_price is None:
        return None, "unverified_price"

    normalized = dict(candidate)
    normalized.update(
        {
            "seller": seller,
            "product_url": url,
            "sale_price": sale_price,
            "original_price": original_price,
            "effective_price": effective_price,
            "availability": "판매 중",
            "source": str(candidate.get("source") or "unknown"),
        }
    )
    return normalized, None


def select_cheapest_seller(
    candidates: list[Any],
    *,
    excluded_sellers: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    rejection_summary: dict[str, int] = {}
    for candidate in candidates or []:
        normalized, reason = validate_seller_candidate(
            candidate, excluded_sellers=excluded_sellers
        )
        if normalized is not None:
            valid.append(normalized)
            continue
        rejection = reason or "invalid_candidate"
        rejection_summary[rejection] = rejection_summary.get(rejection, 0) + 1

    valid.sort(
        key=lambda row: (
            row["effective_price"],
            row["seller"],
            row["product_url"],
        )
    )
    return {
        "status": "ok" if valid else "no_results",
        "selected": valid[0] if valid else None,
        "candidates": valid,
        "rejection_summary": rejection_summary,
    }


def _markdown_candidates(answer: str) -> list[dict[str, Any]]:
    rows = []
    for line in str(answer or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "---" in stripped:
            continue
        columns = [column.strip() for column in stripped.strip("|").split("|")]
        if not columns or columns[0] in {"판매처", "판매처명"}:
            continue
        if len(columns) < 4:
            continue
        url_match = re.search(r"\[[^\]]+\]\(([^)]+)\)", columns[-1])
        url = url_match.group(1).strip() if url_match else columns[-1]
        rows.append(
            {
                "seller": normalize_seller_display(columns[0]),
                "availability": columns[1],
                "sale_price": columns[2],
                "product_url": url,
                "product_match": True,
                "source": "markdown",
            }
        )
    return rows


def select_cheapest_seller_from_markdown(
    answer: str,
    default: str | None = None,
) -> str | None:
    """Legacy Markdown 입력에서 검증 가능한 최저가 판매처를 고른다.

    `default`는 호출 호환성을 위해 남겨두지만 안전상 임의 fallback으로 사용하지 않는다.
    """
    del default
    result = select_cheapest_seller(_markdown_candidates(answer))
    selected = result["selected"]
    return selected["seller"] if selected else None
