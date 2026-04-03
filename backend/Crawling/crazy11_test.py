from __future__ import annotations

import re
import asyncio
from typing import Any
from urllib.parse import urlencode, urljoin
from collections import Counter
from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

BASE_URL = "https://www.crazy11.co.kr"
SEARCH_PATH = "/shop/shopbrand.html"


def remove_common_sizes(products: list[dict]) -> list[dict]:
    """
    모든 상품의 sizes에 공통적으로 존재하는 값을 제거
    """

    counter = Counter()
    total_products = len(products)

    # 각 상품에서 중복 없이 카운트
    for product in products:
        counter.update(set(product.get("sizes", [])))

    # 모든 상품에 등장한 값 찾기
    common_sizes = {size for size, cnt in counter.items() if cnt == total_products}

    # 제거
    for product in products:
        product["sizes"] = [
            s for s in product.get("sizes", []) if s not in common_sizes
        ]

    return products


def _parse_price(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _extract_mm_sizes(text: str) -> list[str]:
    return re.findall(r"\b([1-3]\d{2})\b", text or "")


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    return url


def _build_search_url(
    product_keyword: str,
    min_price: int,
    max_price: int,
    page_no: int,
) -> str:
    params = {
        "search": "",
        "code": "",
        "page": str(page_no),
        "sort": "order",
        "money1": str(min_price),
        "money2": str(max_price),
        "prize1": product_keyword,
        "company1": "",
        "content1": "",
        "brcode": "",
    }
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(params)}"


async def _safe_text(page_or_locator, selector: str) -> str:
    try:
        return _clean_text(await page_or_locator.locator(selector).first.inner_text())
    except Exception:
        return ""


async def _safe_attr(page_or_locator, selector: str, attr: str) -> str:
    try:
        value = await page_or_locator.locator(selector).first.get_attribute(attr)
        return value or ""
    except Exception:
        return ""


async def _extract_sizes_from_detail_page(page: Page) -> list[str]:
    sizes: list[str] = []

    select_candidates = [
        "select[name*='option']",
        "select[id*='option']",
        "select.MS_input_select",
        "select",
    ]

    for selector in select_candidates:
        try:
            selects = page.locator(selector)
            count = await selects.count()

            for i in range(min(count, 10)):
                sel = selects.nth(i)
                options = sel.locator("option")
                option_count = await options.count()

                for j in range(option_count):
                    text = _clean_text(await options.nth(j).inner_text())
                    if not text:
                        continue

                    lower = text.lower()
                    if any(
                        k in lower for k in ["option", "옵션", "선택", "choose", "필수"]
                    ):
                        continue

                    for item in _extract_mm_sizes(text):
                        if item not in sizes:
                            sizes.append(item)
        except Exception:
            pass

        if sizes:
            return sizes

    text_candidates = [
        ".size",
        "[class*='size']",
        "[id*='size']",
        ".option",
        "[class*='option']",
    ]

    for selector in text_candidates:
        try:
            locator = page.locator(selector)
            count = await locator.count()

            for i in range(min(count, 30)):
                raw = _clean_text(await locator.nth(i).inner_text())
                if not raw:
                    continue

                found = _extract_mm_sizes(raw)
                for item in found:
                    if item and item not in sizes:
                        sizes.append(item)
        except Exception:
            pass

        if sizes:
            return sizes

    return sizes


async def _collect_sizes(
    context: BrowserContext,
    detail_url: str,
    semaphore: asyncio.Semaphore,
) -> list[str]:
    if not detail_url:
        return []

    async with semaphore:
        page = await context.new_page()
        try:
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(700)
            return await _extract_sizes_from_detail_page(page)
        except Exception:
            return []
        finally:
            await page.close()


async def _collect_products_from_current_page(
    page: Page,
    min_price: int,
    max_price: int,
) -> list[dict[str, Any]]:
    item_selector = ".itemsList__item"

    try:
        await page.wait_for_selector(item_selector, timeout=7000)
    except PlaywrightTimeoutError:
        return []

    items = page.locator(item_selector)
    item_count = await items.count()

    products: list[dict[str, Any]] = []

    for i in range(item_count):
        item = items.nth(i)

        name = await _safe_text(item, ".itemInfo-tit")
        price_text = await _safe_text(item, ".txtc-e4")
        price = _parse_price(price_text)

        if price is None:
            continue
        if not (min_price <= price <= max_price):
            continue

        detail_href = await _safe_attr(item, "a.itemInfo", "href")
        detail_url = urljoin(BASE_URL, detail_href) if detail_href else ""

        image_url = ""
        for attr in ["data-src", "data-original", "src"]:
            value = await _safe_attr(item, "img", attr)
            if value:
                image_url = _normalize_url(value)
                break

        products.append(
            {
                "product_name": name,
                "product_price": price,
                "sizes": [],
                "image_url": image_url,
                "detail_url": detail_url,
            }
        )

    return products


async def crazy11_crawl(
    product_keyword: str,
    min_price: int,
    max_price: int,
    max_concurrency: int = 5,
    max_pages: int = 30,
) -> list[dict[str, Any]]:
    if min_price > max_price:
        raise ValueError("min_price는 max_price보다 클 수 없습니다.")
    if max_concurrency < 1:
        raise ValueError("max_concurrency는 1 이상이어야 합니다.")
    if max_pages < 1:
        raise ValueError("max_pages는 1 이상이어야 합니다.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            all_products: list[dict[str, Any]] = []
            seen_detail_urls: set[str] = set()

            for page_no in range(1, max_pages + 1):
                search_url = _build_search_url(
                    product_keyword=product_keyword,
                    min_price=min_price,
                    max_price=max_price,
                    page_no=page_no,
                )

                await page.goto(
                    search_url, wait_until="domcontentloaded", timeout=30000
                )
                await page.wait_for_timeout(1200)

                page_products = await _collect_products_from_current_page(
                    page=page,
                    min_price=min_price,
                    max_price=max_price,
                )

                # 상품이 없으면 마지막 페이지로 판단
                if not page_products:
                    break

                new_products: list[dict[str, Any]] = []
                for product in page_products:
                    detail_url = product["detail_url"]
                    # 중복 페이지/중복 상품 방지
                    if detail_url and detail_url in seen_detail_urls:
                        continue
                    if detail_url:
                        seen_detail_urls.add(detail_url)
                    new_products.append(product)

                # 새 상품이 하나도 없으면 페이지 반복으로 보고 종료
                if not new_products:
                    break

                all_products.extend(new_products)

            # 상세 페이지 병렬 수집
            semaphore = asyncio.Semaphore(max_concurrency)
            tasks = [
                _collect_sizes(context, product["detail_url"], semaphore)
                for product in all_products
            ]
            sizes_list = await asyncio.gather(*tasks, return_exceptions=True)

            for product, sizes in zip(all_products, sizes_list):
                product["sizes"] = [] if isinstance(sizes, Exception) else sizes
            return all_products

        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    data = asyncio.run(
        crazy11_crawl(
            product_keyword="나이키 머큐리얼 베이퍼",
            min_price=100000,
            max_price=200000,
            max_concurrency=5,
            max_pages=3,
        )
    )

    from pprint import pprint

    pprint(data)

# 해결 사항
## 속도 개선
