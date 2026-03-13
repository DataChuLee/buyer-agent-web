import asyncio
import inspect
from typing import Any

import pandas as pd
import time
import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)
from Crawling.crazy11_test import crazy11_crawl
from Crawling.redsoccer_test import redsoccer_crawl
from Crawling.soccerboom_test import soccerboom_crawl
from Crawling.cafostore_test import cafostore_crawl


SELLER_CRAWLERS = {
    "crazy11": crazy11_crawl,
    "redsoccer": redsoccer_crawl,
    "soccerboom": soccerboom_crawl,
    "cafostore": cafostore_crawl,
}

SELLER_DEFAULT_KWARGS = {
    "crazy11": {"max_concurrency": 5, "max_pages": 3},
    "redsoccer": {"max_concurrency": 6},
    "soccerboom": {},
    "cafostore": {},
}


def normalize_item(seller: str, item: dict[str, Any]) -> dict[str, Any]:
    product_price = item.get("product_price", item.get("price"))
    product_url = item.get("product_url", item.get("detail_url", ""))

    return {
        "seller": seller,
        "product_name": item.get("product_name", ""),
        "product_price": product_price,
        "sizes": item.get("sizes", []),
        "image_url": item.get("image_url", ""),
        "product_url": product_url,
        "raw": item,
    }


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []

    for item in items:
        key = (
            item["seller"],
            item.get("product_url") or "",
            item.get("product_name") or "",
            item.get("product_price") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)

    return out


def items_to_dataframe(items: list[dict[str, Any]]) -> pd.DataFrame:
    """
    정규화된 item 리스트를 DataFrame으로 변환
    """
    rows = []
    for item in items:
        rows.append(
            {
                "seller": item.get("seller", ""),
                "product_name": item.get("product_name", ""),
                "product_price": item.get("product_price", None),
                "sizes": item.get("sizes", []),
                "sizes_text": (
                    ", ".join(map(str, item.get("sizes", [])))
                    if item.get("sizes")
                    else ""
                ),
                "image_url": item.get("image_url", ""),
                "product_url": item.get("product_url", ""),
            }
        )

    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "seller",
                "product_name",
                "product_price",
                "sizes",
                "sizes_text",
                "image_url",
                "product_url",
            ]
        )

    df = df.sort_values(
        by=["seller", "product_price", "product_name"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    return df


def split_items_by_seller(
    items: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        seller = item.get("seller", "unknown")
        grouped.setdefault(seller, []).append(item)

    return grouped


def build_seller_dataframes(
    items: list[dict[str, Any]],
    requested_sellers: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    grouped = split_items_by_seller(items)
    seller_dfs: dict[str, pd.DataFrame] = {}

    if requested_sellers is None:
        requested_sellers = list(grouped.keys())

    for seller in requested_sellers:
        seller_items = grouped.get(seller, [])
        seller_dfs[seller] = items_to_dataframe(seller_items)

    return seller_dfs


async def run_one_seller(
    seller: str,
    product_keyword: str,
    min_price: int,
    max_price: int,
    seller_semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    crawler = SELLER_CRAWLERS[seller]
    kwargs = {
        "product_keyword": product_keyword,
        "min_price": min_price,
        "max_price": max_price,
        **SELLER_DEFAULT_KWARGS.get(seller, {}),
    }

    async with seller_semaphore:
        if inspect.iscoroutinefunction(crawler):
            result = await crawler(**kwargs)
        else:
            result = await asyncio.to_thread(crawler, **kwargs)

    return [normalize_item(seller, item) for item in result]


async def crawl_multiple_sellers(
    sellers: list[str],
    product_keyword: str,
    min_price: int,
    max_price: int,
    seller_parallelism: int = 2,
) -> dict[str, Any]:
    invalid = [seller for seller in sellers if seller not in SELLER_CRAWLERS]
    if invalid:
        raise ValueError(f"지원하지 않는 판매자: {invalid}")

    seller_semaphore = asyncio.Semaphore(seller_parallelism)

    tasks = [
        asyncio.create_task(
            run_one_seller(
                seller=seller,
                product_keyword=product_keyword,
                min_price=min_price,
                max_price=max_price,
                seller_semaphore=seller_semaphore,
            )
        )
        for seller in sellers
    ]

    gathered = await asyncio.gather(*tasks, return_exceptions=True)

    merged_items: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    for seller, result in zip(sellers, gathered):
        if isinstance(result, Exception):
            errors[seller] = repr(result)
            continue
        merged_items.extend(result)

    merged_items = dedupe_items(merged_items)
    merged_items.sort(key=lambda x: (x["product_price"] is None, x["product_price"]))

    all_df = items_to_dataframe(merged_items)
    seller_dfs = build_seller_dataframes(merged_items, requested_sellers=sellers)

    return {
        "items": merged_items,
        "errors": errors,
        "dataframe": all_df,  # 전체 통합 DataFrame
        "dataframes_by_seller": seller_dfs,  # 판매자별 DataFrame
    }


if __name__ == "__main__":
    start = time.time()
    result = asyncio.run(
        crawl_multiple_sellers(
            sellers=["crazy11", "soccerboom"],
            product_keyword="머큐리얼 베이퍼",
            min_price=100000,
            max_price=200000,
            seller_parallelism=2,
        )
    )
    end = time.time()
    print(f"총 실행시간: {round(end-start,2)}초")

    print("items:", len(result["items"]))
    print("errors:", result["errors"])

    df = result["dataframe"]
    df.to_csv("crawler_result.csv", index=False, encoding="utf-8-sig")
