"""
crawl_and_index.py
==================
seller_total_test.py의 crawl_multiple_sellers를 호출해
크롤링 결과를 rag_search.py의 shared vectorstore에 upsert하는 Tool.
"""

import asyncio
import hashlib
import os
import re
import sys
from typing import Any
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))  # backend/Tools/
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))  # backend/
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)   # rag_search.py 탐색용
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)      # Crawling/ 탐색용
from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.tools import tool

load_dotenv()

# # ── 경로 등록 ───────────────────────────────────────────────
# sys.path.append(os.path.join(os.path.dirname(__file__), "../Crawling"))

# ── shared vectorstore (rag_search.py에서 생성된 인스턴스 공유) ──
from rag_search import vectorstore

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


# ── 크롤링 item → LangChain Document 변환 ───────────────────
def _normalize_sizes(sizes: Any) -> list[int]:
    if not sizes:
        return []
    if isinstance(sizes, (list, tuple, set)):
        return sorted({int(x) for x in sizes if str(x).isdigit() and 0 < int(x) < 400})
    nums = re.findall(r"\d{2,3}", str(sizes))
    return sorted({int(n) for n in nums if 0 < int(n) < 400})


def _clean_name(name: str) -> str:
    t = re.sub(r"\[[^\]]+\]", " ", str(name or "")).strip()
    return re.sub(r"\s+", " ", t).strip()


def item_to_document(item: dict[str, Any]) -> Document:
    seller_raw = item.get("seller", "미상")
    seller_kr = SELLER_INPUT_MAP.get(seller_raw, seller_raw)
    product_name = _clean_name(item.get("product_name", "정보없음"))
    price = int(item.get("product_price") or 0)
    sizes = _normalize_sizes(item.get("sizes", []))

    name_upper = product_name.upper()
    age_group = "유소년용" if re.search(r"주니어|JR|키즈|유소년", product_name, re.I) else "성인용"

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

    product_category = "풋살화" if re.search(r"풋살|TF", product_name, re.I) else "축구화"
    size_text = ", ".join(map(str, sizes)) if sizes else "정보없음"

    page_content = "\n".join([
        f"상품명: {product_name}",
        f"판매자: {seller_kr}",
        f"카테고리: {product_category}",
        f"연령대: {age_group}",
        f"지면: {ground_type}",
        f"가격: {price}원",
        f"사이즈: {size_text}",
    ])

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


# ── Tool 정의 ───────────────────────────────────────────────
@tool
async def crawl_and_index(
    sellers: str,
    product_keyword: str,
    min_price: int,
    max_price: int
) -> str:
    """
    지정한 판매처에서 축구화를 크롤링하고 벡터스토어에 인덱싱합니다.
    rag_search 호출 전에 반드시 먼저 실행하세요.

    Args:
        sellers: 판매처 목록 (쉼표 구분). 지원: crazy11, soccerboom, redsoccer, cafostore
        product_keyword: 검색 키워드. 예: "머큐리얼 베이퍼 성인용 TF" -> "머큐리얼 베이퍼 TF" / "나이키 머큐리얼 베이퍼 10만원대" -> "나이키 머큐리얼 베이퍼"
        min_price: 최소 가격
        max_price: 최대 가격
    """
    from Crawling.seller_total_test import crawl_multiple_sellers

    seller_list = [s.strip() for s in sellers.split(",")]

    result = await crawl_multiple_sellers(
        sellers=seller_list,
        product_keyword=product_keyword,
        min_price=min_price,
        max_price=max_price,
    )

    items = result["items"]
    errors = result["errors"]

    if not items:
        return f"크롤링 결과 없음. 오류: {errors}"

    docs = [item_to_document(item) for item in items]

    ids = [
        hashlib.sha1(d.metadata["product_url"].encode("utf-8")).hexdigest()
        for d in docs
    ]

    vectorstore.add_documents(docs, ids=ids)

    seller_counts: dict[str, int] = {}
    for item in items:
        s = SELLER_INPUT_MAP.get(item.get("seller", ""), item.get("seller", "미상"))
        seller_counts[s] = seller_counts.get(s, 0) + 1

    summary = ", ".join(f"{s}: {c}개" for s, c in seller_counts.items())
    return f"✅ 인덱싱 완료 — 총 {len(docs)}개 ({summary}). 오류: {errors if errors else '없음'}"


if __name__ == "__main__":
    async def test():
        result = await crawl_and_index.ainvoke({
            "sellers": "crazy11",
            "product_keyword": "나이키 머큐리얼 베이퍼",
            "min_price": 100000,
            "max_price": 200000,
        })
        print(result)

    asyncio.run(test())
