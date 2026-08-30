from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from Tools.crawl_and_index import load_raw_items_cache


PRODUCT_SEARCH_DOMAINS = [
    "crazy11.co.kr",
    "soccerboom.co.kr",
    "redsoccer.co.kr",
    "capostore.co.kr",
]
PRODUCT_SEARCH_DOMAIN_LABELS = {
    "crazy11.co.kr": "크레이지11",
    "soccerboom.co.kr": "사커붐",
    "redsoccer.co.kr": "레드사커",
    "capostore.co.kr": "카포스토어",
}
SELLER_DOMAIN_BY_KEY = {
    "crazy11": "crazy11.co.kr",
    "soccerboom": "soccerboom.co.kr",
    "redsoccer": "redsoccer.co.kr",
    "capostore": "capostore.co.kr",
}

PRODUCT_SEARCH_DROP_URL_PARTS = (
    "board",
    "event",
    "calendar",
    "dbk_event",
    "notice",
    "qna",
)
MIN_SCORE_THRESHOLD = 0.35
MAX_CANDIDATES_PER_SELLER = 5
MAX_PRODUCT_ITEMS = 80

PRODUCT_FIELD_LABELS = {
    "name": "상품명",
    "maker": "제조사",
    "consumer_price": "소비자가",
    "sale_price": "판매가",
    "won": "원",
}

BOOT_SURFACE_KEYWORDS = (
    "AG-PRO",
    "FG/MG",
    "FG/AG",
    "HG/AG",
    "AG PRO",
    "MG",
    "FG",
    "AG",
    "TF",
    "IC",
)
BOOT_TEXT_KEYWORDS = (
    "축구화",
    "풋살화",
    "터프",
    "인조잔디",
    "천연잔디",
)
NON_BOOT_KEYWORDS = (
    "타월",
    "저지",
    "유니폼",
    "양말",
    "스타킹",
    "볼",
    "공",
    "가방",
    "슬리퍼",
    "장갑",
    "트레이닝",
    "반팔",
    "쇼츠",
    "팬츠",
    "자켓",
    "후디",
    "모자",
    "ACG",
)
BRAND_RULES = {
    "나이키": ("나이키", "nike"),
    "아디다스": ("아디다스", "adidas"),
    "푸마": ("푸마", "puma"),
    "미즈노": ("미즈노", "mizuno"),
    "뉴발란스": ("뉴발란스", "new balance", "newbalance"),
}
SERIES_PATTERNS = (
    ("머큐리얼 수퍼플라이", ("머큐리얼 수퍼플라이", "머큐리얼 슈퍼플라이", "mercurial superfly", "superfly")),
    ("머큐리얼 베이퍼", ("머큐리얼 베이퍼", "mercurial vapor", "vapor")),
    ("머큐리얼", ("머큐리얼", "mercurial")),
    ("팬텀", ("팬텀", "phantom")),
    ("티엠포 레전드", ("티엠포 레전드", "tiempo legend")),
    ("티엠포 마에스트로", ("티엠포 마에스트로", "tiempo maestro")),
    ("티엠포", ("티엠포", "tiempo")),
    ("프레데터", ("프레데터", "predator")),
    ("F50", ("f50",)),
    ("코파", ("코파", "copa")),
    ("퓨쳐", ("퓨쳐", "future")),
    ("울트라", ("울트라", "ultra")),
    ("모렐리아", ("모렐리아", "morelia")),
)

# SERIES_PATTERNS의 각 canonical 시리즈명에 대한 큐레이션 1줄 설명. LLM이 즉석에서 생성하지 않고
# 직접 작성해둔 고정 텍스트만 사용 — 스펙/성능을 지어내는(hallucination) 위험을 없애기 위함.
SERIES_DESCRIPTIONS: dict[str, str] = {
    "머큐리얼 수퍼플라이": "나이키 최상급 스피드 라인. 초경량 니트 갑피와 저컷 디자인으로 순간 가속과 스피드에 특화된 공격수용 모델입니다.",
    "머큐리얼 베이퍼": "나이키 스피드 라인의 서브 모델. 수퍼플라이보다 안정적인 착화감과 합리적인 가격대로 스피드형 플레이를 원하는 선수에게 적합합니다.",
    "머큐리얼": "나이키의 스피드·침투 특화 축구화 라인. 가볍고 낮은 프로파일로 순간 가속에 강점이 있습니다.",
    "팬텀": "나이키의 터치·컨트롤 특화 라인. 넓은 스트라이크존과 그립 갑피로 정교한 볼 컨트롤과 패스에 강점이 있습니다.",
    "티엠포 레전드": "나이키 최상급 천연가죽 라인. 부드러운 착화감과 터치감으로 클래식한 플레이를 선호하는 미드필더에게 적합합니다.",
    "티엠포 마에스트로": "티엠포 라인의 서브 모델. 가죽 특유의 터치감을 유지하면서 합리적인 가격대의 모델입니다.",
    "티엠포": "나이키의 클래식 가죽 라인. 부드러운 착화감과 안정적인 터치를 중시하는 선수에게 적합합니다.",
    "프레데터": "아디다스의 터치·컨트롤 특화 라인. 고무 스파이크(스터드) 패턴으로 볼 그립과 슈팅 스핀에 강점이 있습니다.",
    "F50": "아디다스의 스피드 특화 라인. 초경량 설계로 가속력과 민첩성을 중시하는 공격수에게 적합합니다.",
    "코파": "아디다스의 가죽 소재 클래식 라인. 부드러운 착화감과 안정적인 터치감을 중시하는 선수에게 적합합니다.",
    "퓨쳐": "푸마의 터치·컨트롤 특화 라인. 신축성 있는 갑피로 발에 밀착되는 착화감이 특징입니다.",
    "울트라": "푸마의 스피드 특화 라인. 경량 설계와 낮은 프로파일로 가속력을 중시하는 선수에게 적합합니다.",
    "모렐리아": "미즈노의 프리미엄 가죽 라인. 얇고 부드러운 가죽으로 섬세한 터치감을 중시하는 선수에게 적합합니다.",
}

# 이 카탈로그 도메인에서는 시리즈명이 브랜드 전용(exclusive)이므로, raw_name에 브랜드 텍스트가
# 없는 캐시 상품(브랜드 필드 자체가 없음)도 시리즈명만으로 브랜드를 안전하게 추론할 수 있다.
SERIES_BRAND: dict[str, str] = {
    "머큐리얼 수퍼플라이": "나이키",
    "머큐리얼 베이퍼": "나이키",
    "머큐리얼": "나이키",
    "팬텀": "나이키",
    "티엠포 레전드": "나이키",
    "티엠포 마에스트로": "나이키",
    "티엠포": "나이키",
    "프레데터": "아디다스",
    "F50": "아디다스",
    "코파": "아디다스",
    "퓨쳐": "푸마",
    "울트라": "푸마",
    "모렐리아": "미즈노",
}

# 브랜드가 정해졌을 때 물어볼 수 있는 큐레이션 시리즈 목록 (SERIES_BRAND의 역인덱스).
# 뉴발란스처럼 큐레이션 시리즈가 없는 브랜드는 키 자체가 없다 — 호출측이 빈 리스트로 받고
# 자유검색으로 폴백한다.
SERIES_OPTIONS_BY_BRAND: dict[str, list[str]] = {}
for _series, _brand in SERIES_BRAND.items():
    SERIES_OPTIONS_BY_BRAND.setdefault(_brand, []).append(_series)
del _series, _brand


def series_options_for_brand(brand: str | None) -> list[str]:
    return SERIES_OPTIONS_BY_BRAND.get(str(brand or ""), [])

PRODUCT_SEARCH_SYSTEM_PROMPT = SystemMessage(
    content=(
        "축구화/풋살화 시리즈 추천 에이전트입니다. search_products 도구를 정확히 한 번 호출하세요. "
        "도구가 반환한 텍스트가 최종 답변으로 그대로 쓰이므로, 도구 호출 뒤에는 그 텍스트를 다시 "
        "베껴 쓰거나 요약/수정하지 말고 짧게 '완료' 한 마디만 답하세요."
    )
)


_PARALLEL_TAVILY_SEARCH = None


def _compact_spaces(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _excerpt(value: Any, limit: int = 180) -> str:
    text = _compact_spaces(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _escape_markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", " ").strip()


def _result_text(result: dict[str, Any]) -> str:
    return "\n".join(
        str(result.get(key) or "")
        for key in ("title", "content", "raw_content", "snippet")
        if result.get(key)
    )


def _candidate_text(item: dict[str, Any]) -> str:
    return _compact_spaces(
        " ".join(
            str(item.get(key) or "")
            for key in ("title", "content", "raw_content", "snippet", "url")
        )
    )


def _seller_domain(url: str) -> str | None:
    host = urlparse(str(url or "")).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    for domain in PRODUCT_SEARCH_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain
    return None


def _seller_label(url: str) -> str:
    domain = _seller_domain(url)
    return PRODUCT_SEARCH_DOMAIN_LABELS.get(domain or "", "지원 판매처")


def _result_domain_ok(url: str, domain: str) -> bool:
    host = urlparse(str(url or "")).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host == domain or host.endswith(f".{domain}")


def _url_has_part(url: str, parts: tuple[str, ...]) -> bool:
    lowered = str(url or "").lower()
    return any(part in lowered for part in parts)


def _parse_krw_price(value: str) -> int | None:
    match = re.search(r"(\d{1,3}(?:,\d{3})+|\d{4,7})", str(value or ""))
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _coerce_verified_price(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        price = int(value)
    else:
        price = _parse_krw_price(str(value))
    return price if price is not None and price > 0 else None


def _extract_price_values(text: str) -> list[int]:
    values: set[int] = set()
    normalized = str(text or "")
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{5,7})\s*원", normalized):
        values.add(int(match.group(1).replace(",", "")))
    for match in re.finditer(r"(\d+)\s*만\s*(\d+)\s*천\s*원?", normalized):
        values.add(int(match.group(1)) * 10000 + int(match.group(2)) * 1000)
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*만\s*원?", normalized):
        values.add(int(float(match.group(1)) * 10000))
    return sorted(value for value in values if value > 0)


def _extract_requested_price_range(query: str) -> tuple[int, int] | None:
    normalized = str(query or "").replace(",", "")
    if match := re.search(r"(\d+)\s*만\s*원?\s*이하", normalized):
        return 0, int(match.group(1)) * 10000
    if match := re.search(r"(\d+)\s*만\s*원?\s*이상", normalized):
        return int(match.group(1)) * 10000, 9_999_999
    if match := re.search(r"(\d+)\s*만\s*원?\s*대", normalized):
        amount = int(match.group(1))
        upper_man = amount + 10 if amount % 10 == 0 else amount + 1
        return amount * 10000, upper_man * 10000 - 1
    if match := re.search(r"(\d{5,7})\s*원?\s*대", normalized):
        amount = int(match.group(1))
        return amount, amount + 99_999
    return None


def _requested_brand_aliases(query: str) -> tuple[str, ...]:
    lowered = str(query or "").lower()
    for aliases in BRAND_RULES.values():
        if any(alias.lower() in lowered for alias in aliases):
            return aliases
    return ()


def _requested_series_name(query: str) -> str | None:
    """쿼리에서 요청된 시리즈의 canonical 이름만 반환한다(모델 번호 없이).

    `extract_series_name()`은 상품명(raw_name) 파싱용으로 별칭 뒤에 오는 숫자를
    모델 번호로 붙이는데, 쿼리 문장에는 "10만원대"처럼 시리즈와 무관한 숫자가
    바로 뒤에 올 수 있어 그대로 재사용하면 오탐(예: "머큐리얼 10")이 발생한다.
    """
    lowered = str(query or "").lower()
    for canonical, aliases in SERIES_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            return canonical
    return None


def _clean_product_field(value: str) -> str:
    text = _compact_spaces(value)
    text = re.sub(r"^[+:\-\]\[]+", "", text).strip()
    text = re.sub(r"[+:\-\]\[]+$", "", text).strip()
    return text


def _extract_labeled_value(block: str, label: str, stop_labels: list[str]) -> str | None:
    stop_pattern = "|".join(re.escape(stop) for stop in stop_labels if stop != label)
    pattern = rf"{re.escape(label)}\s*[:]\s*(.*?)(?=(?:\s*[+|]\s*)?(?:{stop_pattern})\s*[:]|$)"
    match = re.search(pattern, block)
    if not match:
        return None
    value = _clean_product_field(match.group(1))
    return value or None


def _extract_product_blocks(text: str) -> list[str]:
    name_label = PRODUCT_FIELD_LABELS["name"]
    normalized = _compact_spaces(text)
    if name_label not in normalized:
        return []
    chunks = re.split(rf"(?={re.escape(name_label)}\s*[:])", normalized)
    return [chunk for chunk in chunks if chunk.startswith(name_label)]


def _upper_name(value: str) -> str:
    return str(value or "").upper().replace("AG PRO", "AG-PRO")


def _surface_matches_query(product_surface: str | None, query: str) -> bool:
    requested = [surface for surface in BOOT_SURFACE_KEYWORDS if surface in _upper_name(query)]
    if not requested:
        return True
    if not product_surface:
        return False
    product_surface = product_surface.upper()
    for surface in requested:
        surface = surface.replace("AG PRO", "AG-PRO")
        if surface == product_surface or surface in product_surface or product_surface.startswith(surface):
            return True
    return False


def _has_non_boot_keyword(raw_name: str) -> bool:
    lowered = str(raw_name or "").lower()
    return any(keyword.lower() in lowered for keyword in NON_BOOT_KEYWORDS)


def _matches_requested_brand(brand: str | None, raw_name: str, query: str) -> bool:
    aliases = _requested_brand_aliases(query)
    if not aliases:
        return True
    text = f"{brand or ''} {raw_name or ''}".lower()
    return any(alias.lower() in text for alias in aliases)


def _matches_requested_series(series_name: str | None, raw_name: str, query: str) -> bool:
    requested = _requested_series_name(query)
    if not requested:
        return True
    candidate = series_name or extract_series_name(raw_name)
    if not candidate:
        return False
    return candidate.startswith(requested)


def _matches_requested_price(sale_price: int | None, query: str) -> bool:
    price_range = _extract_requested_price_range(query)
    if not price_range:
        return True
    if sale_price is None:
        return False
    return price_range[0] <= sale_price <= price_range[1]


def _price_match_for_item(item: dict[str, Any], query: str) -> tuple[bool, str | None, int | None]:
    price_range = _extract_requested_price_range(query)
    sale_price = _coerce_verified_price(item.get("sale_price"))
    if sale_price is not None:
        matches = not price_range or price_range[0] <= sale_price <= price_range[1]
        return matches, "sale_price", sale_price

    consumer_price = _coerce_verified_price(item.get("consumer_price"))
    if consumer_price is not None:
        matches = not price_range or price_range[0] <= consumer_price <= price_range[1]
        return matches, "consumer_price", consumer_price

    return False, None, None


def build_product_search_query(
    conditions: dict[str, Any] | str | None,
    rejected_series: list[str] | None = None,
) -> str:
    if isinstance(conditions, str):
        base = conditions
    else:
        values = conditions or {}
        parts = [
            str(values[key])
            for key in ["brand", "budget", "surface", "position", "age_group", "product_name"]
            if values.get(key)
        ]
        base = " ".join(parts)
    base = _compact_spaces(base) or "축구화"
    rejected = [item for item in (rejected_series or []) if item]
    exclusion = f" {' '.join(rejected)} 제외" if rejected else ""
    return _compact_spaces(f"{base} 축구화 풋살화 시리즈 추천{exclusion}")


def build_tavily_product_search_query(query: str) -> str:
    return _compact_spaces(f"{query} 축구화 풋살화 시리즈 추천")


def filter_tavily_candidates(
    result_by_seller: dict[str, Any],
    *,
    min_score: float = MIN_SCORE_THRESHOLD,
    max_per_seller: int | None = MAX_CANDIDATES_PER_SELLER,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    counts_by_seller: dict[str, int] = {}
    for row in _flatten_parallel_tavily_result(result_by_seller):
        seller_key = str(row["seller_key"])
        if max_per_seller is not None and counts_by_seller.get(seller_key, 0) >= max_per_seller:
            continue
        keep_reason = _candidate_keep_reason(row, min_score=min_score)
        if not keep_reason:
            continue
        row["keep_reason"] = keep_reason
        kept.append(row)
        counts_by_seller[seller_key] = counts_by_seller.get(seller_key, 0) + 1
    return kept


def _flatten_parallel_tavily_result(result_by_seller: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seller_key, seller_result in (result_by_seller or {}).items():
        if not isinstance(seller_result, dict) or not seller_result.get("ok"):
            continue
        seller = seller_result.get("seller") or seller_key
        domain = seller_result.get("domain") or ""
        for rank, item in enumerate(seller_result.get("results") or [], start=1):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["seller_key"] = seller_key
            row["seller"] = seller
            row["domain"] = domain
            row["rank"] = rank
            row["score"] = float(row.get("score") or 0.0)
            row["domain_ok"] = bool(row.get("domain_ok", _result_domain_ok(row.get("url", ""), domain)))
            row["price_candidates"] = _extract_price_values(_candidate_text(row))
            row["dropped_url"] = _url_has_part(row.get("url", ""), PRODUCT_SEARCH_DROP_URL_PARTS)
            rows.append(row)
    return rows


def _candidate_keep_reason(row: dict[str, Any], *, min_score: float) -> str | None:
    if not row.get("domain_ok"):
        return None
    if row.get("dropped_url"):
        return None
    if row.get("score", 0.0) < min_score:
        return None
    return "score_threshold"


def _build_product_item(candidate: dict[str, Any], block: str, local_index: int) -> dict[str, Any] | None:
    labels = list(PRODUCT_FIELD_LABELS.values())
    raw_name = _extract_labeled_value(block, PRODUCT_FIELD_LABELS["name"], labels)
    if not raw_name:
        return None

    brand = _extract_labeled_value(block, PRODUCT_FIELD_LABELS["maker"], labels)
    consumer_price_text = _extract_labeled_value(block, PRODUCT_FIELD_LABELS["consumer_price"], labels)
    sale_price_text = _extract_labeled_value(block, PRODUCT_FIELD_LABELS["sale_price"], labels)
    consumer_price = _parse_krw_price(consumer_price_text or "")
    sale_price = _parse_krw_price(sale_price_text or "")

    return {
        "input_index": None,
        "seller": candidate.get("seller") or "",
        "seller_key": candidate.get("seller_key") or "",
        "source_url": candidate.get("url") or "",
        "source_title": candidate.get("title") or "",
        "source_rank": candidate.get("rank"),
        "search_score": round(float(candidate.get("score") or 0.0), 4),
        "local_index": local_index,
        "raw_name": raw_name,
        "brand": brand,
        "consumer_price": consumer_price,
        "sale_price": sale_price,
        "price_source": "sale_price_label" if sale_price is not None else None,
        "evidence_text": _excerpt(block, 320),
    }


def extract_product_items_from_candidate(candidate: dict[str, Any], max_items: int = 12) -> list[dict[str, Any]]:
    text = candidate.get("content") or candidate.get("raw_content") or ""
    items: list[dict[str, Any]] = []
    for local_index, block in enumerate(_extract_product_blocks(text), start=1):
        item = _build_product_item(candidate, block, local_index)
        if item is None:
            continue
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def extract_product_items(candidates: list[dict[str, Any]], max_items: int = MAX_PRODUCT_ITEMS) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None, str]] = set()
    for candidate in candidates:
        for item in extract_product_items_from_candidate(candidate):
            key = (item.get("raw_name") or "", item.get("sale_price"), item.get("source_url") or "")
            if key in seen:
                continue
            seen.add(key)
            item["input_index"] = len(items) + 1
            items.append(item)
            if len(items) >= max_items:
                return items
    return items


def detect_brand(item: dict[str, Any]) -> str | None:
    text = f"{item.get('brand') or ''} {item.get('raw_name') or ''}".lower()
    for brand, aliases in BRAND_RULES.items():
        if any(alias.lower() in text for alias in aliases):
            return brand
    return item.get("brand") or None


def extract_surface(raw_name: str) -> str | None:
    upper = _upper_name(raw_name)
    for surface in BOOT_SURFACE_KEYWORDS:
        normalized = surface.replace("AG PRO", "AG-PRO")
        if normalized in upper:
            return "AG-PRO" if normalized == "AG-PRO" else normalized
    return None


def extract_category(raw_name: str, surface: str | None) -> str | None:
    lowered = str(raw_name or "").lower()
    if "풋살" in lowered or surface in {"TF", "IC"}:
        return "풋살화"
    if "축구" in lowered or surface in {"FG", "AG", "AG-PRO", "MG", "FG/MG", "FG/AG", "HG/AG"}:
        return "축구화"
    return None


def is_boot_product(item: dict[str, Any]) -> bool:
    raw_name = str(item.get("raw_name") or "")
    if _has_non_boot_keyword(raw_name):
        return False
    upper = _upper_name(raw_name)
    lowered = raw_name.lower()
    return any(surface.replace("AG PRO", "AG-PRO") in upper for surface in BOOT_SURFACE_KEYWORDS) or any(
        keyword.lower() in lowered for keyword in BOOT_TEXT_KEYWORDS
    )


def extract_series_name(raw_name: str) -> str | None:
    """상품명에서 시리즈명(예: "머큐리얼 베이퍼")을 판별한다.

    세대 번호(예: "16")는 일부러 붙이지 않는다 — "시리즈" 추천은 제품(SKU) 단위가 아니라
    라인업 단위여야 하므로, 세대가 달라도 같은 시리즈로 묶여 dedupe되게 한다.
    """
    lowered = str(raw_name or "").lower()
    for canonical, aliases in SERIES_PATTERNS:
        if any(alias.lower() in lowered for alias in aliases):
            return canonical
    return None


def normalize_product_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    if not is_boot_product(item):
        return None
    raw_name = item.get("raw_name") or ""
    surface = extract_surface(raw_name)
    series_name = extract_series_name(raw_name)
    if not series_name:
        return None
    brand = detect_brand(item) or SERIES_BRAND.get(series_name)
    normalized = dict(item)
    normalized.update(
        {
            "brand": brand,
            "series_name": series_name,
            "surface": surface,
            "category": extract_category(raw_name, surface),
            "product_url": item.get("source_url") or item.get("url"),
            "sale_price": _coerce_verified_price(item.get("sale_price")),
            "consumer_price": _coerce_verified_price(item.get("consumer_price")),
        }
    )
    return normalized


def classify_product_item(item: dict[str, Any], query: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    # exclude 절을 벗겨내지 않으면 거절된 시리즈명이 뒤이은 substring 매칭(_requested_series_name)에
    # "요청된 시리즈"로 오인식돼(예: "10만원대 exclude: 머큐리얼 베이퍼"에서 "머큐리얼"이 매칭됨),
    # 그 시리즈만 통과시키고 다른 시리즈는 전부 걸러버리는 문제가 있었다(retry 시 "다른 거 없어?"가
    # 오히려 같은/제외된 시리즈만 다시 보여주던 실사용 버그의 원인).
    excluded = _excluded_series_names(query or "")
    query = _strip_exclude_clause(query or "")
    if not isinstance(item, dict):
        return None, "invalid_item"
    normalized = normalize_product_item(item)
    if normalized is None:
        return None, "not_boot_or_missing_series"
    if not normalized.get("product_url"):
        return normalized, "missing_url"
    if _seller_domain(normalized["product_url"]) is None:
        return normalized, "unsupported_seller"
    if normalized.get("series_name") in excluded:
        return normalized, "excluded_series"
    if not _matches_requested_brand(normalized.get("brand"), normalized.get("raw_name", ""), query):
        return normalized, "brand_mismatch"
    if not _matches_requested_series(normalized.get("series_name"), normalized.get("raw_name", ""), query):
        return normalized, "series_mismatch"

    price_ok, price_source, price_value = _price_match_for_item(normalized, query)
    if price_source is None:
        return normalized, "unverified_price"
    if not price_ok:
        return normalized, "price_mismatch"
    if price_source:
        normalized["price_match_source"] = price_source
        normalized["price_match_value"] = price_value

    if not _surface_matches_query(normalized.get("surface"), query):
        return normalized, "surface_mismatch"
    if price_value is not None and price_value < 20000:
        return normalized, "invalid_low_sale_price"
    return normalized, None


def collect_product_filter_diagnostics(
    items: list[dict[str, Any]],
    query: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    summary: dict[str, int] = {}
    for item in items:
        normalized, reject_reason = classify_product_item(item, query)
        if reject_reason is None and normalized is not None:
            accepted.append(normalized)
            continue

        reason = reject_reason or "unknown"
        rejected_source = normalized if isinstance(normalized, dict) else item
        rejected_item = (
            dict(rejected_source)
            if isinstance(rejected_source, dict)
            else {"input_type": type(item).__name__}
        )
        rejected_item["reject_reason"] = reason
        rejected.append(rejected_item)
        summary[reason] = summary.get(reason, 0) + 1
    return accepted, rejected, summary


def filter_normalized_products(items: list[dict[str, Any]], query: str | None = None) -> list[dict[str, Any]]:
    accepted, _, _ = collect_product_filter_diagnostics(items, query)
    return accepted


def _product_dedupe_key(row: dict[str, Any]) -> tuple[Any, ...]:
    # 가격/판매처는 dedup 키에서 뺀다 — "시리즈 추천"은 SKU/판매처 단위가 아니라 시리즈+지면
    # 단위여야 하므로, 같은 시리즈가 가격만 다른 여러 행으로 쪼개지지 않게 한다.
    return (
        row.get("brand") or "",
        row.get("series_name") or "",
        row.get("surface") or "",
    )


def _is_cheaper_candidate(row: dict[str, Any], previous: dict[str, Any]) -> bool:
    """같은 시리즈+지면 중 더 저렴한 쪽(최저가 1개만 표시)을 남긴다. 가격이 같으면 검색 점수로 판단."""
    row_price = _coerce_verified_price(row.get("sale_price")) or _coerce_verified_price(
        row.get("consumer_price")
    )
    prev_price = _coerce_verified_price(previous.get("sale_price")) or _coerce_verified_price(
        previous.get("consumer_price")
    )
    if (row_price is None) != (prev_price is None):
        return prev_price is None
    if row_price is not None and prev_price is not None and row_price != prev_price:
        return row_price < prev_price
    return float(row.get("search_score") or 0.0) > float(previous.get("search_score") or 0.0)


def dedupe_extracted_series(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = _product_dedupe_key(row)
        previous = best_by_key.get(key)
        if previous is None or _is_cheaper_candidate(row, previous):
            best_by_key[key] = row
    return sorted(
        best_by_key.values(),
        key=lambda row: (
            row.get("sale_price") is None,
            row.get("sale_price") or 9_999_999,
            -(float(row.get("search_score") or 0.0)),
        ),
    )


def _requested_price_label(query: str) -> str | None:
    normalized = str(query or "").replace(",", "")
    if match := re.search(r"(\d+)\s*만원\s*(대|이하|이상)?", normalized):
        return f"{match.group(1)}만원{match.group(2) or ''}"
    if match := re.search(r"(\d{5,7})\s*원\s*(대|이하|이상)?", normalized):
        return f"{int(match.group(1)):,}원{match.group(2) or ''}"
    return None


def build_recommendation_reason(row: dict[str, Any], query: str) -> str:
    series = row.get("series_name")
    description = SERIES_DESCRIPTIONS.get(series or "")

    parts: list[str] = []
    brand = row.get("brand")
    if brand:
        parts.append(f"{brand} 조건에 맞습니다")

    price_label = _requested_price_label(query)
    if price_label and row.get("sale_price") is not None:
        parts.append(f"{price_label} 예산대에 들어옵니다")

    requested_surfaces = [surface for surface in BOOT_SURFACE_KEYWORDS if surface in _upper_name(query)]
    surface = row.get("surface")
    if surface and requested_surfaces:
        parts.append(f"{surface} 지면 조건과 일치합니다")
    elif surface:
        parts.append(f"{surface} 지면용 후보입니다")

    if not parts and not description:
        return "상품명과 판매가가 확인된 축구화/풋살화 후보입니다."

    match_summary = (", ".join(parts) + ".") if parts else ""
    return f"{description} {match_summary}".strip()


_NO_RESULT_ANSWER_PREFIXES = (
    # 주의: 성공 응답(format_product_search_results 하단)도 "지원 판매처 4곳의 Tavily 검색
    # 결과에서"로 시작하므로, 여기서는 "찾지 못했습니다"까지 포함한 전체 문장을 접두어로 써서
    # 두 메시지가 서로 다른 접두어를 갖도록 한다(짧은 공통 substring으로 두면 성공 응답까지
    # "결과 없음"으로 오판되어 카드가 전혀 파싱되지 않는다).
    "지원 판매처 4곳의 Tavily 검색 결과에서 요청 조건에 맞는 축구화/풋살화 시리즈 후보를 찾지 못했습니다",
    "지원 판매처 검색에서는 요청 조건에 맞는 실제 판매 상품을 찾지 못했습니다",
    "상품 검색 중 외부 검색 서비스를 사용할 수 없어 실제 상품을 확인하지 못했습니다",
)


def is_no_result_answer(text: str) -> bool:
    """조건에 맞는 실제 상품을 찾지 못했을 때의 안내 텍스트인지 판별한다.

    이름은 기존 호출부 호환을 위해 유지하지만 외부 검색 오류 안내도 포함한다. 이런 텍스트는
    실제 상품 데이터(가격/URL)가 없는 일반 안내 문구일 뿐이므로,
    LLM 카드 추출기로 넘겨 '추천 상품 카드'로 오인 파싱되지 않도록 막는 데 사용한다.
    """
    stripped = str(text or "").strip()
    return any(stripped.startswith(prefix) for prefix in _NO_RESULT_ANSWER_PREFIXES)


def build_product_search_error_answer() -> str:
    return (
        "상품 검색 중 외부 검색 서비스를 사용할 수 없어 실제 상품을 확인하지 못했습니다.\n\n"
        "검증되지 않은 상품이나 가격은 대신 생성하지 않았습니다. 잠시 후 다시 검색해 주세요."
    )


def build_product_search_fallback_answer(
    query: str,
    rejection_summary: dict[str, int] | None = None,
) -> str:
    lines = [
        "지원 판매처 검색에서는 요청 조건에 맞는 실제 판매 상품을 찾지 못했습니다.",
        "",
        "대신 일반적인 시리즈 기준으로 보면 아래 방향으로 다시 찾아보는 것이 좋습니다.",
        "",
        "- 스피드/침투 성향: 나이키 머큐리얼, 아디다스 F50 계열",
        "- 터치/컨트롤 성향: 나이키 팬텀, 아디다스 프레데터 계열",
        "- 안정감/착화감 성향: 나이키 티엠포, 아디다스 코파 계열",
        "",
        "정확한 판매가, 재고, 구매 가능 여부는 판매처 검색 결과가 없어서 확인하지 못했습니다.",
        "FG, AG, TF, IC 중 실제로 신을 지면을 좁히면 다시 검색 정확도가 올라갑니다.",
    ]
    if rejection_summary:
        summary = ", ".join(f"{reason}={count}" for reason, count in sorted(rejection_summary.items()))
        lines.append("")
        lines.append(f"필터 탈락 요약: {summary}")
    return "\n".join(lines)


def format_product_search_results(
    rows: list[dict[str, Any]],
    query: str,
    rejection_summary: dict[str, int] | None = None,
) -> str:
    if not rows:
        message = (
            "지원 판매처 4곳의 Tavily 검색 결과에서 요청 조건에 맞는 축구화/풋살화 시리즈 후보를 찾지 못했습니다.\n\n"
            "현재 필터는 score 0.35 이상, 게시판/이벤트 URL 제외, 상품명/판매가 라벨 확인, "
            "브랜드/가격대/지면 조건 일치를 기준으로 적용됩니다."
        )
        if rejection_summary:
            summary = ", ".join(f"{reason}={count}" for reason, count in sorted(rejection_summary.items()))
            message += f"\n\n필터 탈락 요약: {summary}"
        return message

    lines = [
        "지원 판매처 4곳의 Tavily 검색 결과에서 조건에 맞는 축구화/풋살화 시리즈 후보입니다.",
        "",
    ]
    for idx, row in enumerate(rows, start=1):
        reason = build_recommendation_reason(row, query)
        series = row.get("series_name") or ""
        # 줄 끝 공백 2칸은 CommonMark hard line break — 채팅 UI가 markdown으로 렌더링할 때
        # 한 문단으로 뭉치지 않고 항목별로 줄바꿈되게 한다.
        lines.append(f"{idx}. {series}  ")
        lines.append(f"추천 이유: {reason}")
        lines.append("")
    return "\n".join(lines).rstrip()


_EXCLUDE_CLAUSE_RE = re.compile(r"\s*exclude\s*:.*$", re.IGNORECASE)


def _strip_exclude_clause(query: str) -> str:
    """workers.py가 재시도 시 붙이는 "exclude: A, B" 절을 제거한다.

    제거하지 않으면 거절된 시리즈명이 그 절 안에 그대로 남아있어, 뒤이은 substring
    매칭(_requested_series_name 등)이 "제외해달라"는 이름을 오히려 검색 키워드로
    골라버려 방금 거절한 시리즈가 캐시에서 다시 나오는 문제가 생긴다.
    """
    return _EXCLUDE_CLAUSE_RE.sub("", str(query or ""))


def _excluded_series_names(query: str) -> set[str]:
    """"exclude: A, B" 절에서 제외 대상 시리즈명 집합을 뽑아 classify_product_item()이
    해당 시리즈를 명시적으로 걸러내는 데 쓴다(그동안은 Tavily 쿼리 문구로만 힌트를 줬을 뿐,
    실제로 걸러내는 필터가 없었다).

    콤마로 분리하지 않고 SERIES_PATTERNS 별칭의 substring 매칭으로 찾는다 — workers.py가
    "exclude: A, B" 뒤에 항상 " 축구화 추천"을 덧붙이므로, 콤마 분리 방식은 마지막 이름에
    그 접미사가 붙어버려(예: "머큐리얼 베이퍼 축구화 추천") 정확히 일치하지 않는다.
    """
    match = re.search(r"exclude\s*:\s*(.*)$", str(query or ""), re.IGNORECASE)
    if not match:
        return set()
    segment = match.group(1).lower()
    matched = {
        canonical
        for canonical, aliases in SERIES_PATTERNS
        if any(alias.lower() in segment for alias in aliases)
    }
    # "머큐리얼 베이퍼"가 명시됐을 때 일반 "머큐리얼"까지 함께 매칭되어 수퍼플라이까지
    # 과잉 제외되지 않도록, 더 구체적인 하위 시리즈가 있으면 상위 canonical만 제거한다.
    return {
        canonical
        for canonical in matched
        if not any(other != canonical and other.startswith(canonical) for other in matched)
    }


def _raw_cache_search_keyword(query: str) -> str | None:
    """Seller Search가 이미 사용 중인 raw_items_cache는 시리즈명 단위로 색인되어 있으므로,
    쿼리에서 인식 가능한 시리즈가 없으면 캐시 조회 자체를 건너뛴다."""
    return _requested_series_name(_strip_exclude_clause(query))


def _requested_brand_name(query: str) -> str | None:
    """쿼리에 언급된 브랜드의 canonical 이름만 반환한다(별칭 튜플이 아니라)."""
    lowered = str(query or "").lower()
    for brand, aliases in BRAND_RULES.items():
        if any(alias.lower() in lowered for alias in aliases):
            return brand
    return None


def _raw_cache_search_keywords(query: str) -> list[str]:
    """캐시 조회에 쓸 키워드 목록을 반환한다.

    쿼리에 특정 시리즈명이 있으면 그 하나만 쓰고, 시리즈 없이 브랜드만 있으면(예: "나이키
    10만원대 TF 추천해줘") 그 브랜드의 큐레이션 시리즈 전체를 조회해 병합한다 — 안 그러면
    캐시에 이미 데이터가 있어도 사용자가 시리즈까지 안 골랐다는 이유만으로 매번 라이브 Tavily
    검색에 노출되어 같은 조건인데도 결과가 호출마다 들쭉날쭉해졌다(실사용 재현으로 확인).
    """
    stripped = _strip_exclude_clause(query)
    keyword = _raw_cache_search_keyword(stripped)
    if keyword:
        return [keyword]
    return series_options_for_brand(_requested_brand_name(stripped))


def _raw_cache_search_items(query: str) -> list[dict[str, Any]]:
    keywords = _raw_cache_search_keywords(query)
    if not keywords:
        return []
    min_price, max_price = _extract_requested_price_range(query) or (0, 9_999_999)

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for keyword in keywords:
        for cache_item in load_raw_items_cache(keyword, min_price, max_price) or []:
            if not isinstance(cache_item, dict):
                continue
            raw_name = cache_item.get("product_name") or ""
            if not raw_name:
                continue
            dedupe_key = (raw_name, cache_item.get("product_url") or "")
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            items.append(
                {
                    "input_index": None,
                    "seller": cache_item.get("seller") or "",
                    "seller_key": cache_item.get("seller") or "",
                    "source_url": cache_item.get("product_url") or "",
                    "source_title": raw_name,
                    "source_rank": None,
                    "search_score": 0.9,
                    "local_index": len(items) + 1,
                    "raw_name": raw_name,
                    "brand": None,
                    "consumer_price": None,
                    "sale_price": cache_item.get("product_price"),
                    "price_source": "raw_items_cache",
                    "evidence_text": raw_name,
                }
            )
    return items


def build_product_search_pipeline_result(
    query: str,
    parallel_result: dict[str, Any],
    extra_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    filtered_candidates = filter_tavily_candidates(parallel_result)
    product_items = extract_product_items(filtered_candidates)
    if extra_items:
        product_items = product_items + extra_items
    normalized_products, rejected_products, rejection_summary = collect_product_filter_diagnostics(product_items, query)
    deduped_series = dedupe_extracted_series(normalized_products)
    answer = format_product_search_results(deduped_series, query, rejection_summary)
    return {
        "query": query,
        "filtered_candidates": filtered_candidates,
        "product_items": product_items,
        "normalized_products": normalized_products,
        "rejected_products": rejected_products,
        "rejection_summary": rejection_summary,
        "deduped_series": deduped_series,
        "answer": answer,
    }


# format_product_search_results()가 만드는 "N. 시리즈명" 헤더 + 들여쓴 "라벨: 값" 줄 포맷을
# 그대로 되짚는 파서. 표가 아니라 프로즈 스트리밍 텍스트로 바뀌어도 카드 데이터(품명/가격/
# 추천 이유/링크)는 여전히 결정적으로(=LLM 호출 없이) 추출한다.
_PRODUCT_HEADER_RE = re.compile(r"^\s*\d+\.\s*(?P<name>.+?)\s*$")
_PRODUCT_REASON_RE = re.compile(r"^\s*추천 이유\s*:\s*(.*)$")


def parse_product_markdown_table(text: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in str(text or "").splitlines():
        if reason_match := _PRODUCT_REASON_RE.match(line):
            if current is not None:
                current["recommendation"] = reason_match.group(1).strip()
            continue
        if header_match := _PRODUCT_HEADER_RE.match(line):
            name = header_match.group("name").strip()
            if not name:
                continue
            if current:
                parsed.append(current)
            current = {"name": name, "features": "", "recommendation": "", "price": "", "url": None}
    if current:
        parsed.append(current)
    return parsed


def _flat_results_from_parallel(parallel_result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for seller_result in (parallel_result or {}).values():
        if not isinstance(seller_result, dict):
            continue
        rows.extend([item for item in seller_result.get("results") or [] if isinstance(item, dict)])
    return rows


def format_unfiltered_tavily_results(results: list[dict[str, Any]], limit: int = 10) -> str:
    rows = [
        "가격 필터를 적용하지 않은 Tavily 원본 결과입니다.",
        "",
        "| 순위 | 제목 | URL | 요약 | 추출 가격 후보 |",
        "|---|---|---|---|---|",
    ]
    for idx, result in enumerate((results or [])[:limit], start=1):
        if not isinstance(result, dict):
            continue
        text = _result_text(result)
        prices = _extract_price_values(text)
        price_text = ", ".join(f"{price:,}원" for price in prices[:5]) if prices else "없음"
        rows.append(
            "| {idx} | {title} | {url} | {summary} | {prices} |".format(
                idx=idx,
                title=_escape_markdown_cell(result.get("title") or "제목 없음"),
                url=_escape_markdown_cell(result.get("url") or ""),
                summary=_escape_markdown_cell(_excerpt(text)),
                prices=_escape_markdown_cell(price_text),
            )
        )
    if len(rows) == 4:
        rows.append("| - | 결과 없음 |  |  |  |")
    return "\n".join(rows)


def _format_diagnostic_rows(
    results: list[dict[str, Any]],
    *,
    include_prices_only: bool = False,
    price_range: tuple[int, int] | None = None,
    limit: int = 10,
) -> list[str]:
    rows = ["| 순위 | 제목 | URL | 추출 가격 후보 | 요약 |", "|---|---|---|---|---|"]
    for result in (results or [])[:limit]:
        if not isinstance(result, dict):
            continue
        text = _result_text(result)
        prices = _extract_price_values(text)
        if include_prices_only and not prices:
            continue
        if price_range and not any(price_range[0] <= price <= price_range[1] for price in prices):
            continue

        price_text = ", ".join(f"{price:,}원" for price in prices[:5]) if prices else "없음"
        rows.append(
            "| {idx} | {title} | {url} | {prices} | {summary} |".format(
                idx=len(rows) - 1,
                title=_escape_markdown_cell(result.get("title") or "제목 없음"),
                url=_escape_markdown_cell(result.get("url") or ""),
                prices=_escape_markdown_cell(price_text),
                summary=_escape_markdown_cell(_excerpt(text)),
            )
        )
    if len(rows) == 2:
        rows.append("| - | 결과 없음 |  |  |  |")
    return rows


def format_tavily_price_diagnostics(
    query: str,
    results: list[dict[str, Any]],
    limit: int = 10,
) -> str:
    price_range = _extract_requested_price_range(query)
    sections = [
        "RAW: 아무 필터도 적용하지 않은 Tavily 원본",
        *_format_diagnostic_rows(results, limit=limit),
        "",
        "PRICE_DETECTED: 가격 후보가 추출된 결과",
        *_format_diagnostic_rows(results, include_prices_only=True, limit=limit),
        "",
        "PRICE_FILTERED: 요청 가격대 통과 결과" if price_range else "PRICE_FILTERED: 가격 조건 없음 - 필터 미적용",
    ]
    sections.extend(_format_diagnostic_rows(results, price_range=price_range, limit=limit))
    return "\n".join(sections)


def filter_tavily_product_results(
    query: str,
    results: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, str]]:
    parallel_result = {
        "legacy": {
            "seller": "지원 판매처",
            "domain": "",
            "ok": True,
            "results": [
                dict(result, domain_ok=bool(_seller_domain(result.get("url", ""))))
                for result in (results or [])
                if isinstance(result, dict)
            ],
        }
    }
    pipeline = build_product_search_pipeline_result(query, parallel_result)
    cards: list[dict[str, str]] = []
    for row in pipeline["deduped_series"][:limit]:
        price = row.get("sale_price")
        cards.append(
            {
                "name": row.get("series_name") or row.get("raw_name") or "",
                "features": row.get("surface") or "",
                "recommendation": build_recommendation_reason(row, query),
                "price": f"{price:,}원" if price is not None else "",
                "url": row.get("product_url") or row.get("source_url") or "",
            }
        )
    return cards


def build_strict_product_search_answer(query: str, results: list[dict[str, Any]]) -> str:
    parallel_result = {
        "legacy": {
            "seller": "지원 판매처",
            "domain": "",
            "ok": True,
            "results": [
                dict(result, domain_ok=bool(_seller_domain(result.get("url", ""))))
                for result in (results or [])
                if isinstance(result, dict)
            ],
        }
    }
    return build_product_search_pipeline_result(query, parallel_result)["answer"]


def _build_profile_context(user_profile: dict[str, Any] | None) -> str:
    profile = user_profile or {}
    fields: list[str] = []
    labels = {
        "brand": "선호 브랜드",
        "budget": "예산",
        "surface": "지면",
        "position": "포지션",
        "age_group": "연령대",
        "play_style": "플레이 스타일",
        "physical_traits": "신체 특징",
    }
    for key, label in labels.items():
        value = profile.get(key)
        if value:
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            fields.append(f"- {label}: {value}")
    return "\n".join(fields)


def _create_tavily_tool(domain: str):
    from langchain_community.tools.tavily_search import TavilySearchResults

    return TavilySearchResults(
        max_results=5,
        include_answer=False,
        include_raw_content=False,
        include_images=False,
        format_output=True,
        search_depth="advanced",
        include_domains=[domain],
        exclude_domains=["ads.com", "spam.com"],
    )


def _seller_branch(tool, seller: str, domain: str):
    from langchain_core.runnables import RunnableLambda

    async def _run(payload: dict[str, Any]):
        query = payload.get("query", "") if isinstance(payload, dict) else str(payload)
        started = time.perf_counter()
        try:
            raw_results = await tool.ainvoke({"query": query})
            results = raw_results if isinstance(raw_results, list) else []
            for item in results:
                if isinstance(item, dict):
                    item["domain_ok"] = _result_domain_ok(item.get("url", ""), domain)
            return {
                "seller": seller,
                "domain": domain,
                "ok": True,
                "elapsed_sec": round(time.perf_counter() - started, 3),
                "results": results,
                "error": None,
            }
        except Exception as exc:
            return {
                "seller": seller,
                "domain": domain,
                "ok": False,
                "elapsed_sec": round(time.perf_counter() - started, 3),
                "results": [],
                "error": repr(exc),
            }

    return RunnableLambda(_run)


def get_parallel_tavily_search():
    global _PARALLEL_TAVILY_SEARCH
    if _PARALLEL_TAVILY_SEARCH is None:
        from langchain_core.runnables import RunnableParallel

        branches = {}
        for seller_key, domain in SELLER_DOMAIN_BY_KEY.items():
            branches[seller_key] = _seller_branch(
                _create_tavily_tool(domain),
                PRODUCT_SEARCH_DOMAIN_LABELS[domain],
                domain,
            )
        _PARALLEL_TAVILY_SEARCH = RunnableParallel(branches)
    return _PARALLEL_TAVILY_SEARCH


async def run_parallel_tavily_product_search(query: str) -> dict[str, Any]:
    tavily_query = build_tavily_product_search_query(query)
    return await get_parallel_tavily_search().ainvoke(
        {"query": tavily_query},
        config={"max_concurrency": len(SELLER_DOMAIN_BY_KEY)},
    )


def _query_requests_surface(query: str) -> bool:
    upper = _upper_name(query)
    return any(surface.replace("AG PRO", "AG-PRO") in upper for surface in BOOT_SURFACE_KEYWORDS)


def _merge_parallel_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for result in results:
        for key, seller_result in (result or {}).items():
            if not isinstance(seller_result, dict):
                continue
            target = merged.setdefault(
                key,
                {
                    "seller": seller_result.get("seller"),
                    "domain": seller_result.get("domain"),
                    "ok": bool(seller_result.get("ok")),
                    "elapsed_sec": seller_result.get("elapsed_sec"),
                    "results": [],
                    "error": seller_result.get("error"),
                },
            )
            target["ok"] = bool(target.get("ok") or seller_result.get("ok"))
            target["results"].extend(seller_result.get("results") or [])
    return merged


def _parallel_search_state(parallel_result: dict[str, Any]) -> tuple[str, list[str]]:
    branches = [value for value in (parallel_result or {}).values() if isinstance(value, dict)]
    failed_sellers = [
        str(branch.get("seller") or branch.get("domain") or "지원 판매처")
        for branch in branches
        if not branch.get("ok")
    ]
    if branches and not any(branch.get("ok") for branch in branches):
        return "error", failed_sellers
    return "available", failed_sellers


def _set_pipeline_status(
    result: dict[str, Any],
    *,
    source: str,
    status: str,
    failed_sellers: list[str] | None = None,
) -> dict[str, Any]:
    result["source"] = source
    result["search_status"] = status
    result["failed_sellers"] = list(dict.fromkeys(failed_sellers or []))
    return result


async def _run_surface_expanded_search(query: str) -> dict[str, Any]:
    expansion_queries = [f"{query} {surface}" for surface in ("FG", "AG", "TF", "IC")]
    expanded_results = await asyncio.gather(
        *(run_parallel_tavily_product_search(expanded_query) for expanded_query in expansion_queries)
    )
    return _merge_parallel_results(expanded_results)


async def run_product_search_pipeline(query: str) -> dict[str, Any]:
    # seller_search_agent.search_sellers와 동일한 순서: raw_items_cache에 매칭되는 항목이 있으면
    # 그걸로 결정적으로 답을 만들고, 없을 때만 실시간 Tavily 검색으로 폴백한다. 예전엔 캐시 유무와
    # 무관하게 매번 Tavily를 먼저 돌리고 캐시는 그저 덧붙이기만 해서, 매 턴 라이브 검색 결과 편차에
    # 그대로 노출돼 같은 조건인데도 "됐다가 안됐다가"하는 문제가 있었다.
    cache_items = _raw_cache_search_items(query)
    if cache_items:
        result = build_product_search_pipeline_result(query, {}, extra_items=cache_items)
        result["parallel_result"] = {}
        result["expanded_search"] = False
        if not result["deduped_series"]:
            result["answer"] = build_product_search_fallback_answer(query, result.get("rejection_summary"))
        result["initial_parallel_result"] = {}
        return _set_pipeline_status(
            result,
            source="raw_cache",
            status="ok" if result["deduped_series"] else "no_results",
        )

    try:
        parallel_result = await run_parallel_tavily_product_search(query)
    except Exception:
        result = build_product_search_pipeline_result(query, {})
        result["parallel_result"] = {}
        result["initial_parallel_result"] = {}
        result["expanded_search"] = False
        result["answer"] = build_product_search_error_answer()
        return _set_pipeline_status(result, source="web_search", status="error")

    initial_state, initial_failed_sellers = _parallel_search_state(parallel_result)
    result = build_product_search_pipeline_result(query, parallel_result)
    result["parallel_result"] = parallel_result
    result["expanded_search"] = False

    failed_sellers = initial_failed_sellers
    if (
        initial_state != "error"
        and not result["deduped_series"]
        and not _query_requests_surface(query)
    ):
        try:
            expanded_parallel_result = await _run_surface_expanded_search(query)
        except Exception:
            expanded_parallel_result = {}
        expanded_state, expanded_failed_sellers = _parallel_search_state(expanded_parallel_result)
        failed_sellers.extend(expanded_failed_sellers)
        if expanded_state != "error":
            expanded_result = build_product_search_pipeline_result(query, expanded_parallel_result)
            expanded_result["parallel_result"] = expanded_parallel_result
            expanded_result["expanded_search"] = True
            result = expanded_result

    if not result["deduped_series"]:
        if initial_state == "error":
            result["answer"] = build_product_search_error_answer()
        else:
            result["answer"] = build_product_search_fallback_answer(query, result.get("rejection_summary"))

    result["initial_parallel_result"] = parallel_result
    return _set_pipeline_status(
        result,
        source="web_search",
        status=(
            "ok"
            if result["deduped_series"]
            else "error"
            if initial_state == "error"
            else "no_results"
        ),
        failed_sellers=failed_sellers,
    )


async def run_unfiltered_tavily_product_search(query: str) -> str:
    parallel_result = await run_parallel_tavily_product_search(query)
    return format_unfiltered_tavily_results(_flat_results_from_parallel(parallel_result))


async def run_tavily_price_diagnostics(query: str) -> str:
    parallel_result = await run_parallel_tavily_product_search(query)
    return format_tavily_price_diagnostics(query, _flat_results_from_parallel(parallel_result))


async def run_product_search(query: str) -> str:
    return (await run_product_search_pipeline(query))["answer"]


@tool
async def search_products(query: str) -> str:
    """조건에 맞는 축구화/풋살화 시리즈 후보를 검색해 번호 목록 텍스트(표 아님)로 반환합니다."""
    return await run_product_search(query)


_PRODUCT_SEARCH_REACT_AGENT = None


def _get_product_search_react_agent():
    global _PRODUCT_SEARCH_REACT_AGENT
    if _PRODUCT_SEARCH_REACT_AGENT is None:
        from langchain_openai import ChatOpenAI
        from langgraph.prebuilt import create_react_agent

        _PRODUCT_SEARCH_REACT_AGENT = create_react_agent(
            ChatOpenAI(model="gpt-4o-mini", temperature=0),
            tools=[search_products],
            prompt=PRODUCT_SEARCH_SYSTEM_PROMPT,
        )
    return _PRODUCT_SEARCH_REACT_AGENT


async def product_search_agent(query: str, user_profile: dict | None = None, config=None) -> str:
    profile_context = _build_profile_context(user_profile)
    final_query = query
    if profile_context:
        final_query = f"{query}\n\n[사용자 프로필]\n{profile_context}"
    # config(콜백 포함)를 넘겨야 상위 그래프의 astream_events가 이 react agent 내부 LLM의
    # 토큰 스트림까지 이벤트로 잡아낼 수 있다 — 안 넘기면 답변이 스트리밍 없이 한 번에 나온다.
    result = await _get_product_search_react_agent().ainvoke(
        {"messages": [HumanMessage(content=final_query)]}, config=config
    )
    # LLM에게 도구 결과를 "그대로 베껴 출력"하라고 시키면 gpt-4o-mini 같은 소형 모델이 실사용에서
    # 반복적으로 같은 텍스트를 한 번 더 생성해버리는 문제가 확인됐다(원시 SSE 캡처로 검증 —
    # AIMessage.content 자체에 텍스트가 두 번 들어있었음, _run_search 재실행과는 무관). 모델이
    # 생성한 최종 메시지를 신뢰하지 않고 search_products 도구가 반환한 원문(ToolMessage)을 직접
    # 사용해 이 반복 생성 문제를 근본적으로 없앤다.
    for message in reversed(result["messages"]):
        if isinstance(message, ToolMessage):
            return str(message.content)
    return result["messages"][-1].content
