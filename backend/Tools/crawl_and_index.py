"""
crawl_and_index.py
==================
Crawler tool that collects product data and upserts it into the shared Chroma
vectorstore used by rag_search.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote


def _safe_unquote_url(url: str) -> str:
    """percent-encoded URL을 UTF-8 기준으로만 decode.

    레드사커처럼 EUC-KR 로 인코딩된 검색 쿼리스트링이 들어오면 UTF-8 decode 실패 →
    원본 percent-encoded 형태 그대로 유지해 브라우저가 정상 처리하도록 함.
    """
    if not url:
        return ""
    try:
        return unquote(url, encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return url

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.tools import tool

load_dotenv()

# =============================================================================
# 크로스세션 인덱싱 레지스트리
# 디스크 JSON 파일에 (판매자+키워드+가격) 조합 + TTL(24h) 저장.
# 서버 재시작·멀티워커 환경에서도 재크롤 방지.
# 구현은 crawl_registry 모듈에 위임.
# =============================================================================
try:
    from Tools.crawl_registry import is_already_indexed, register_crawl
except ImportError:
    from crawl_registry import is_already_indexed, register_crawl

try:
    from Tools.seller_normalization import (
        normalize_seller_crawler,
        normalize_seller_display,
    )
except ImportError:
    from seller_normalization import normalize_seller_crawler, normalize_seller_display

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHROMA_PERSIST_DIR = os.path.abspath(
    os.getenv("CHROMA_PERSIST_DIR", os.path.join(_BACKEND_DIR, ".chroma_store"))
)


def _get_vectorstore():
    """RAG 인덱싱을 실제 실행할 때만 embedding/vectorstore를 초기화한다."""
    try:
        from Tools.vectorstore_singleton import vectorstore
    except ImportError:
        from vectorstore_singleton import vectorstore
    return vectorstore

# =============================================================================
# Raw items 캐시 — Seller Search가 재크롤 없이 크롤 결과를 재사용
# 저장 경로: CHROMA_PERSIST_DIR/raw_items_cache.json
# TTL: 24h (crawl_registry와 동일)
# =============================================================================
_RAW_CACHE_PATH = os.path.join(CHROMA_PERSIST_DIR, "raw_items_cache.json")
_RAW_CACHE_TTL = timedelta(hours=24)
_RAW_CACHE_LOCK = threading.Lock()


def _raw_cache_key(sellers: list[str], keyword: str, min_price: int, max_price: int) -> str:
    sellers_sorted = ",".join(sorted(s.strip() for s in sellers if s.strip()))
    return f"{sellers_sorted}|{keyword}|{min_price}|{max_price}"


def _load_raw_cache() -> dict[str, Any]:
    if not os.path.exists(_RAW_CACHE_PATH):
        return {}
    try:
        with open(_RAW_CACHE_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_raw_cache(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_RAW_CACHE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".raw_items_cache_", suffix=".json", dir=os.path.dirname(_RAW_CACHE_PATH))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, _RAW_CACHE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _store_raw_items(sellers: list[str], keyword: str, min_price: int, max_price: int, items: list[dict]) -> None:
    key = _raw_cache_key(sellers, keyword, min_price, max_price)
    entry = {
        "sellers": sorted(s.strip() for s in sellers if s.strip()),
        "keyword": keyword,
        "min_price": min_price,
        "max_price": max_price,
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }
    with _RAW_CACHE_LOCK:
        data = _load_raw_cache()
        data[key] = entry
        _save_raw_cache(data)


_RAW_CACHE_STOPWORDS = {
    "나이키",
    "nike",
    "축구화",
    "풋살화",
    "구매",
    "재고",
    "가격",
    "판매처",
    "비교",
    "어디서",
    "제일",
    "가장",
    "싸게",
    "팔아",
    "팔아줘",
    "알려줘",
    "추천",
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_cache_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _keyword_tokens(keyword: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", str(keyword or ""))
    return [
        token
        for token in tokens
        if token.lower() not in _RAW_CACHE_STOPWORDS
        and (len(token) >= 2 or token.isdigit())
    ]


def _raw_item_matches_keyword(item: dict, keyword: str) -> bool:
    tokens = _keyword_tokens(keyword)
    if not tokens:
        return True

    product_name = str(item.get("product_name") or "").lower()
    return all(token.lower() in product_name for token in tokens)


def _price_ranges_overlap(
    request_min: int,
    request_max: int,
    entry_min: int,
    entry_max: int,
) -> bool:
    return max(request_min, entry_min) <= min(request_max, entry_max)


def _raw_item_dedupe_key(item: dict) -> str:
    seller = str(item.get("seller") or "").strip().lower()
    product_name = re.sub(
        r"\s+",
        " ",
        str(item.get("product_name") or "").strip().lower(),
    )
    if seller and product_name:
        return f"{seller}|{product_name}"

    product_url = str(item.get("product_url") or "").strip()
    if product_url:
        return product_url
    return "|".join(
        [
            str(item.get("seller") or "").strip(),
            str(item.get("product_name") or "").strip(),
            str(item.get("product_price") or "").strip(),
        ]
    )


def load_raw_items_cache(keyword: str, min_price: int = 0, max_price: int = 9_999_999) -> list[dict] | None:
    """Seller Search용 — 캐시된 raw items 반환. 없거나 만료 시 None.

    fuzzy 매칭: 등록된 키워드가 요청 키워드의 부분집합이고 가격대가 포함되면 hit.
    반환 items는 요청 가격대(min_price ~ max_price)로 추가 필터링됨.
    """
    now = datetime.now(timezone.utc)
    with _RAW_CACHE_LOCK:
        data = _load_raw_cache()

    keyword_lower = (keyword or "").lower()
    matched_items: list[dict] = []
    seen: set[str] = set()

    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        cached_at = entry.get("cached_at")
        if not cached_at:
            continue
        cached_at_dt = _parse_cache_datetime(cached_at)
        if cached_at_dt is None:
            continue
        age = now - cached_at_dt
        if age > _RAW_CACHE_TTL:
            continue

        entry_keyword = str(entry.get("keyword") or "").lower()
        entry_min = _safe_int(entry.get("min_price"), 0)
        entry_max = _safe_int(entry.get("max_price"), 9_999_999)

        # 키워드 포함 + 요청 가격대가 캐시 범위와 겹치면 hit
        keyword_match = entry_keyword and (entry_keyword in keyword_lower or keyword_lower in entry_keyword)
        price_match = _price_ranges_overlap(min_price, max_price, entry_min, entry_max)
        if keyword_match and price_match:
            # 요청 가격대와 상품명 토큰으로 재필터
            for item in entry.get("items") or []:
                if not isinstance(item, dict):
                    continue
                price = _safe_int(item.get("product_price"), 0)
                if not min_price <= price <= max_price:
                    continue
                if not _raw_item_matches_keyword(item, keyword):
                    continue
                key = _raw_item_dedupe_key(item)
                if key in seen:
                    continue
                seen.add(key)
                matched_items.append(item)

    return matched_items or None


SELLER_INPUT_MAP = {
    "crazy11": "크레이지11",
    "크레이지11": "크레이지11",
    "soccerboom": "사커붐",
    "사커붐": "사커붐",
    "redsoccer": "레드사커",
    "레드사커": "레드사커",
    "cafostore": "카포스토어",
    "카포스토어": "카포스토어",
}


def _normalize_sizes(sizes: Any) -> list[int]:
    if not sizes:
        return []
    if isinstance(sizes, (list, tuple, set)):
        return sorted(
            {
                int(value)
                for value in sizes
                if str(value).isdigit() and 100 <= int(value) < 400
            }
        )

    numbers = re.findall(r"\d{3}", str(sizes))
    return sorted({int(number) for number in numbers if 100 <= int(number) < 400})


def _clean_name(name: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", " ", str(name or "")).strip()
    return re.sub(r"\s+", " ", cleaned).strip()


def item_to_document(item: dict[str, Any]) -> Document:
    seller_raw = item.get("seller", "미상")
    seller_kr = normalize_seller_display(seller_raw)
    product_name = _clean_name(item.get("product_name", "정보없음"))
    price = int(item.get("product_price") or 0)
    sizes = _normalize_sizes(item.get("sizes", []))

    name_upper = product_name.upper()
    age_group = (
        "유소년용"
        if re.search(r"주니어|JR|키즈|유소년", product_name, re.IGNORECASE)
        else "성인용"
    )

    if "FG" in name_upper:
        ground_type = "FG"
    elif "AG" in name_upper:
        ground_type = "AG"
    elif "MG" in name_upper:
        ground_type = "MG"
    elif "HG" in name_upper:
        ground_type = "HG"
    elif "TF" in name_upper or "TURF" in name_upper:
        ground_type = "TF"
    else:
        ground_type = "UNKNOWN"

    product_category = (
        "풋살화" if re.search(r"풋살|TF", product_name, re.IGNORECASE) else "축구화"
    )
    size_text = ", ".join(map(str, sizes)) if sizes else "정보없음"

    page_content = "\n".join(
        [
            f"상품명: {product_name}",
            f"판매처: {seller_kr}",
            f"카테고리: {product_category}",
            f"연령대: {age_group}",
            f"지면: {ground_type}",
            f"가격: {price}원",
            f"사이즈: {size_text}",
        ]
    )

    metadata = {
        "seller": seller_kr,
        "product_name": product_name,
        "product_price": price,
        "size_min": min(sizes) if sizes else 0,
        "size_max": max(sizes) if sizes else 0,
        "size_text": ",".join(map(str, sizes)) if sizes else "",
        "product_category": product_category,
        "age_group": age_group,
        "ground_type": ground_type,
        "product_url": _safe_unquote_url(item.get("product_url", "")),
        "image_url": _safe_unquote_url(item.get("image_url", "")),
    }

    return Document(page_content=page_content, metadata=metadata)


@tool
async def crawl_and_index(
    sellers: list[str], product_keyword: str, min_price: int, max_price: int
) -> str:
    """
    Crawl products from the requested sellers and upsert them into the shared
    vectorstore before rag_search runs.
    """

    # 전역 레지스트리 확인 — 이미 인덱싱된 조합이면 재크롤 생략.
    # is_already_indexed는 동기 파일 I/O라 to_thread로 넘겨야, product_analysis_agent가
    # 판매처별로 asyncio.gather 하는 동안 이벤트 루프가 이 파일 읽기로 막히지 않는다.
    if await asyncio.to_thread(is_already_indexed, sellers, product_keyword, min_price, max_price):
        print(f"[전역 레지스트리 HIT] 재크롤 생략 | sellers={sellers}, keyword={product_keyword}, price={min_price}~{max_price}")
        return f"이미 인덱싱된 데이터가 있습니다. 재크롤 생략 (sellers={sellers}, keyword={product_keyword})."

    from Crawling.seller_total_test import crawl_multiple_sellers

    seller_list = [
        normalize_seller_crawler(seller) for seller in sellers if seller.strip()
    ]
    result = await crawl_multiple_sellers(
        sellers=seller_list,
        product_keyword=product_keyword,
        min_price=min_price,
        max_price=max_price,
        seller_parallelism=len(seller_list),  # 판매자 수만큼 동시 크롤
    )

    items = result["items"]
    errors = result["errors"]

    if not items:
        return f"크롤링 결과 없음. 오류: {errors}"

    docs = [item_to_document(item) for item in items]
    ids = [
        hashlib.sha1(document.metadata["product_url"].encode("utf-8")).hexdigest()
        for document in docs
    ]
    _get_vectorstore().add_documents(docs, ids=ids)

    await asyncio.to_thread(
        register_crawl, sellers, product_keyword, min_price, max_price, len(docs)
    )
    # Seller Search 재사용을 위해 raw items도 캐시에 저장
    _store_raw_items(sellers, product_keyword, min_price, max_price, items)

    seller_counts: dict[str, int] = {}
    for item in items:
        seller_name = normalize_seller_display(item.get("seller", ""))
        seller_counts[seller_name] = seller_counts.get(seller_name, 0) + 1

    summary = ", ".join(
        f"{seller_name}: {count}개" for seller_name, count in seller_counts.items()
    )
    return (
        f"인덱싱 완료. 총 {len(docs)}개 ({summary}). "
        f"오류: {errors if errors else '없음'}"
    )


if __name__ == "__main__":

    async def test():
        result = await crawl_and_index.ainvoke(
            {
                "sellers": ["crazy11"],
                "product_keyword": "나이키 머큐리얼 베이퍼",
                "min_price": 100000,
                "max_price": 200000,
            }
        )
        print(result)

    import asyncio

    asyncio.run(test())
