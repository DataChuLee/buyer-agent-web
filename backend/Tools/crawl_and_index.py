"""
crawl_and_index.py
==================
Crawler tool that collects product data and upserts it into the shared Chroma
vectorstore used by rag_search.py.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.tools import tool

load_dotenv()

# =============================================================================
# 전역 인덱싱 레지스트리
# 서버 프로세스 생존 동안 유효. 재시작 시 vectorstore(in-memory)와 함께 초기화됨.
# 세션이 달라도 동일 (판매자+키워드+가격) 조합 재크롤 방지.
# =============================================================================
_CRAWL_INDEX_REGISTRY: set[str] = set()


def _registry_key(sellers: list[str], keyword: str, min_price: int, max_price: int) -> str:
    sellers_sorted = ",".join(sorted(s.strip() for s in sellers if s.strip()))
    return f"{sellers_sorted}|{keyword}|{min_price}|{max_price}"


def is_already_indexed(sellers: list[str], keyword: str, min_price: int, max_price: int) -> bool:
    """동일 조건으로 이미 크롤·인덱싱된 적 있는지 확인 (전역, 세션 무관)."""
    return _registry_key(sellers, keyword, min_price, max_price) in _CRAWL_INDEX_REGISTRY

try:
    from Tools.seller_normalization import (
        normalize_seller_crawler,
        normalize_seller_display,
    )
except ImportError:
    from seller_normalization import normalize_seller_crawler, normalize_seller_display

try:
    from Tools.vectorstore_singleton import vectorstore
except ImportError:
    from vectorstore_singleton import vectorstore

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
        "product_url": item.get("product_url", ""),
        "image_url": item.get("image_url", ""),
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

    # 전역 레지스트리 확인 — 이미 인덱싱된 조합이면 재크롤 생략
    if is_already_indexed(sellers, product_keyword, min_price, max_price):
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
    vectorstore.add_documents(docs, ids=ids)

    # 성공 시 전역 레지스트리에 등록
    _CRAWL_INDEX_REGISTRY.add(_registry_key(sellers, product_keyword, min_price, max_price))

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
