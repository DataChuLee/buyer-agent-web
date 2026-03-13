from __future__ import annotations

import re
from typing import List, Dict, Any
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://soccerboom.co.kr"


def _parse_price_to_int(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urljoin(BASE_URL, url)


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_price_from_card(card) -> int | None:
    sale_price = card.locator(".description").get_attribute("data-sale_price")
    price = _parse_price_to_int(sale_price)
    if price is not None:
        return price

    data_price = card.locator(".thumbnail .sale_rate").get_attribute("data-price")
    price = _parse_price_to_int(data_price)
    if price is not None:
        return price

    spec_items = card.locator("ul.spec li")
    for i in range(spec_items.count()):
        txt = _clean_text(spec_items.nth(i).inner_text())
        if "판매가" in txt:
            price = _parse_price_to_int(txt)
            if price is not None:
                return price

    return None


def _extract_sizes_from_detail_page(page) -> List[str]:
    sizes: List[str] = []
    seen = set()

    def add_size(value: str):
        value = _clean_text(value)
        if not value:
            return
        if value in seen:
            return
        ignore_keywords = [
            "필수",
            "선택",
            "옵션",
            "품절",
            "추가구매",
            "수량",
            "총",
            "상품명",
            "판매가",
        ]
        if any(k in value for k in ignore_keywords):
            return
        seen.add(value)
        sizes.append(value)

    select_candidates = [
        'select[id^="product_option_id"]',
        ".ProductOption select",
        ".xans-product-option select",
        "#product_option_id1",
        "#product_option_id2",
    ]

    for selector in select_candidates:
        selects = page.locator(selector)
        for i in range(selects.count()):
            options = selects.nth(i).locator("option")
            for j in range(options.count()):
                text = _clean_text(options.nth(j).inner_text())

                mm_match = re.search(r"\b(\d{2,3})\s*mm\b", text, re.I)
                num_match = re.search(
                    r"\b(220|225|230|235|240|245|250|255|260|265|270|275|280|285|290|295|300)\b",
                    text,
                )

                if mm_match:
                    add_size(f"{mm_match.group(1)}mm")
                elif num_match:
                    add_size(num_match.group(1))

    return sizes


def soccerboom_crawl(
    product_keyword: str, min_price: int, max_price: int
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(15000)

        try:
            page.goto(f"{BASE_URL}/product/search.html", wait_until="domcontentloaded")

            # 가격 필드가 있는 실제 상품검색 폼만 선택
            search_form = (
                page.locator('form[action="/product/search.html"]')
                .filter(has=page.locator("#product_price1"))
                .first
            )
            search_form.wait_for()

            # strict mode 에러 방지: form 내부에서만 탐색
            search_form.locator('input[name="keyword"]').fill(product_keyword)
            search_form.locator("#product_price1").fill(str(min_price))
            search_form.locator("#product_price2").fill(str(max_price))

            if search_form.locator("#order_by").count() > 0:
                search_form.locator("#order_by").select_option("priceasc")

            # 상품검색 영역의 검색 버튼 클릭
            search_form.locator('input[type="image"][alt="검색"]').click()
            page.wait_for_load_state("domcontentloaded")

            cards = page.locator(
                ".xans-search-result.ec-base-product ul.prdList.grid4 > li"
            )
            cards.first.wait_for()

            while True:
                card_count = cards.count()

                for i in range(card_count):
                    card = cards.nth(i)

                    product_name = _clean_text(
                        card.locator(".description .name a").inner_text()
                    )

                    image_url = ""
                    if card.locator(".thumbnail img").count() > 0:
                        image_url = _normalize_url(
                            card.locator(".thumbnail img").first.get_attribute("src")
                        )

                    product_url = ""
                    if card.locator(".thumbnail a").count() > 0:
                        href = card.locator(".thumbnail a").first.get_attribute("href")
                        product_url = _normalize_url(href)

                    product_price = _extract_price_from_card(card)
                    if product_price is None:
                        continue

                    if not (min_price <= product_price <= max_price):
                        continue

                    sizes: List[str] = []
                    if product_url:
                        detail_page = context.new_page()
                        detail_page.set_default_timeout(10000)
                        try:
                            detail_page.goto(product_url, wait_until="domcontentloaded")
                            sizes = _extract_sizes_from_detail_page(detail_page)
                        except PlaywrightTimeoutError:
                            sizes = []
                        finally:
                            detail_page.close()

                    results.append(
                        {
                            "product_name": product_name,
                            "product_price": product_price,
                            "sizes": sizes,
                            "image_url": image_url,
                            "product_url": product_url,
                        }
                    )

                # 다음 페이지
                next_link = page.locator(
                    ".xans-search-paging.ec-base-paginate a"
                ).filter(has_text="다음")

                if next_link.count() > 0 and next_link.first.is_visible():
                    next_link.first.click()
                    page.wait_for_load_state("domcontentloaded")
                    cards = page.locator(
                        ".xans-search-result.ec-base-product ul.prdList.grid4 > li"
                    )
                    cards.first.wait_for()
                else:
                    break

        finally:
            context.close()
            browser.close()

    return results


if __name__ == "__main__":
    data = soccerboom_crawl("머큐리얼 베이퍼", 100000, 200000)
    from pprint import pprint

    pprint(data)

# 해결 사항
## 사커붐은 다음 페이지 및 사이즈 데이터 수집 잘 수행
## 하지만, 속도 측면에서 좀 걸리는 것 같음 이를 개선
