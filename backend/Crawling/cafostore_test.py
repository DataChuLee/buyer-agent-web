from __future__ import annotations

import re
from typing import List, Dict, Any
from urllib.parse import urlencode, urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://capostore.co.kr"
SEARCH_PATH = "/goods/goods_search.php"


def _parse_price_to_int(price_text: str) -> int | None:
    """
    '189,000원' -> 189000
    """
    if not price_text:
        return None

    digits = re.sub(r"[^\d]", "", price_text)
    return int(digits) if digits else None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _build_search_url(product_keyword: str, page: int = 1) -> str:
    """
    PDF 내 검색 페이지 구조를 기준으로 URL 구성.
    기본적으로 keyword 파라미터로 검색 가능.
    page 파라미터를 추가해 페이지네이션 순회.
    """
    query = {
        "keyword": product_keyword,
        "key": "goodsNm",
        "pageNum": "18",
        "sort": "",
        "page": page,
    }
    return f"{BASE_URL}{SEARCH_PATH}?{urlencode(query, doseq=True)}"


def cafostore_crawl(
    product_keyword: str, min_price: int, max_price: int
) -> List[Dict[str, Any]]:
    """
    카포스토어 검색 결과 페이지 구조를 기준으로 상품 데이터 수집.

    Args:
        product_keyword: 축구화 모델명
        min_price: 최소 가격
        max_price: 최대 가격

    Returns:
        [
            {
                "product_name": str,
                "price": int,
                "sizes": List[str],
                "image_url": str,
                "product_url": str,
            },
            ...
        ]
    """
    if not product_keyword.strip():
        raise ValueError("product_keyword는 비어 있을 수 없습니다.")
    if min_price > max_price:
        raise ValueError("min_price는 max_price보다 클 수 없습니다.")

    results: List[Dict[str, Any]] = []
    seen_product_urls: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 2200},
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        current_page_num = 1

        while True:
            search_url = _build_search_url(
                product_keyword=product_keyword, page=current_page_num
            )
            page.goto(search_url, wait_until="domcontentloaded")

            # 상품 리스트 렌더링 대기
            try:
                page.wait_for_selector(
                    ".goods_list_cont .item_cont, .goods_list .item_cont", timeout=10000
                )
            except PlaywrightTimeoutError:
                # 검색 결과가 없거나 구조가 바뀐 경우
                break

            item_locator = page.locator(".goods_list_cont .item_cont")
            if item_locator.count() == 0:
                item_locator = page.locator(".goods_list .item_cont")

            item_count = item_locator.count()
            if item_count == 0:
                break

            page_has_new_item = False

            for i in range(item_count):
                item = item_locator.nth(i)

                # 상품명
                product_name = ""
                name_locator = item.locator(".item_name")
                if name_locator.count() > 0:
                    product_name = _normalize_text(name_locator.first.inner_text())

                # 가격
                price_text = ""
                price_locator = item.locator(".item_price")
                if price_locator.count() > 0:
                    price_text = _normalize_text(price_locator.first.inner_text())

                price = _parse_price_to_int(price_text)
                if price is None:
                    continue

                # 가격 필터
                if price < min_price or price > max_price:
                    continue

                # 사이즈
                sizes = []
                size_locator = item.locator(".list_options span")
                size_count = size_locator.count()
                for j in range(size_count):
                    size_text = _normalize_text(size_locator.nth(j).inner_text())
                    if size_text:
                        sizes.append(size_text)

                # 상품 링크
                product_url = ""
                link_locator = item.locator(".item_tit_box a")
                if link_locator.count() > 0:
                    href = link_locator.first.get_attribute("href")
                    if href:
                        product_url = urljoin(BASE_URL, href)

                # 이미지 URL
                image_url = ""
                photo_box = item.locator(".item_photo_box")
                if photo_box.count() > 0:
                    image_url = (
                        photo_box.first.get_attribute("data-image-main")
                        or photo_box.first.get_attribute("data-image-list")
                        or ""
                    )

                if not image_url:
                    img_locator = item.locator(".item_photo_box img")
                    if img_locator.count() > 0:
                        src = img_locator.first.get_attribute("src")
                        if src:
                            image_url = urljoin(BASE_URL, src)

                if product_url and product_url in seen_product_urls:
                    continue

                if product_url:
                    seen_product_urls.add(product_url)

                results.append(
                    {
                        "product_name": product_name,
                        "price": price,
                        "sizes": sizes,
                        "image_url": image_url,
                        "product_url": product_url,
                    }
                )
                page_has_new_item = True

            # 다음 페이지가 있는지 확인
            next_page_num = current_page_num + 1

            # pagination a 태그 중 다음 페이지 번호 링크 탐색
            next_link = page.locator(f".pagination a[href*='page={next_page_num}']")
            if next_link.count() == 0:
                break

            # 현재 페이지에서 수집된 새 아이템이 없으면 중단
            if not page_has_new_item:
                break

            current_page_num += 1

        browser.close()

    return results


if __name__ == "__main__":
    data = cafostore_crawl(
        product_keyword="머큐리얼 베이퍼",
        min_price=100000,
        max_price=200000,
    )

    for row in data:
        print(row)

# 카포스토어 -> 사이즈 데이터 및 넘어갈 페이지 있는 경우 -> 상품 데이터 수집 잘함
