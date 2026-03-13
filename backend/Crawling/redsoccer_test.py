from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    Response,
    async_playwright,
)

BASE_URL = "https://www.redsoccer.co.kr"
SEARCH_PATH = "/shop/shopbrand.html"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_price(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _normalize_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return urljoin(BASE_URL, url)
    return url


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        item = _clean_text(item)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _extract_branduid(text: str) -> str:
    m = re.search(r"branduid=(\d+)", text or "")
    if m:
        return m.group(1)

    m = re.search(r"mk_prd_option_preview\((\d+)", text or "")
    if m:
        return m.group(1)

    return ""


def _extract_page_no_from_href(href: str) -> int | None:
    m = re.search(r"pagemove\((\d+)\)", href or "")
    return int(m.group(1)) if m else None


def _looks_like_size(token: str) -> bool:
    token = _clean_text(token)
    if not token:
        return False

    lower = token.lower()

    bad_words = [
        "옵션",
        "선택",
        "choose",
        "필수",
        "추가",
        "추가구성",
        "재고수량",
        "무제한",
        "품절",
        "sold out",
        "장바구니",
        "바로구매",
        "총 상품금액",
        "미리보기",
        "닫기",
        "색상",
    ]
    if any(word in lower for word in bad_words):
        return False

    patterns = [
        r"^\d{3}$",  # 220, 225, 230...
        r"^\d{2,3}mm$",  # 270mm
        r"^(?:US|UK|EU)\s?\d+(?:\.\d+)?$",
        r"^\d{2,3}/\d{2,3}$",
    ]
    return any(re.match(p, token, flags=re.I) for p in patterns)


def _extract_sizes_from_text_blob(text: str) -> list[str]:
    text = _clean_text(text)
    if not text:
        return []

    candidates = re.findall(
        r"""
        (?:US|UK|EU)\s?\d+(?:\.\d+)? |
        \d{2,3}mm |
        \b\d{3}\b |
        \b\d{2,3}/\d{2,3}\b
        """,
        text,
        flags=re.I | re.X,
    )

    return _dedupe_keep_order([x for x in candidates if _looks_like_size(x)])


async def _safe_inner_text(locator: Locator) -> str:
    try:
        return _clean_text(await locator.inner_text())
    except Exception:
        return ""


async def _safe_attr(locator: Locator, attr: str) -> str:
    try:
        value = await locator.get_attribute(attr)
        return value or ""
    except Exception:
        return ""


async def _block_unnecessary_resources(page: Page) -> None:
    async def handler(route):
        req = route.request
        rt = req.resource_type
        url = req.url.lower()

        if rt in {"image", "font", "media", "stylesheet"}:
            await route.abort()
            return

        if any(
            x in url
            for x in [
                "google-analytics",
                "googletagmanager",
                "doubleclick",
                "facebook",
                "wcslog",
                "analytics",
            ]
        ):
            await route.abort()
            return

        await route.continue_()

    await page.route("**/*", handler)


async def _collect_preview_sizes(page: Page, branduid: str) -> list[str]:
    """
    옵션 미리보기:
    1) JS 직접 호출
    2) DOM에 렌더링된 #MK_opt_preview / .mk_prd_option_list 수집
    3) 호출 중 발생한 XHR 응답 텍스트도 함께 수집
    """
    if not branduid:
        return []

    captured_responses: list[str] = []

    async def on_response(resp: Response):
        try:
            url = resp.url.lower()
            if branduid not in url:
                return
            if resp.request.resource_type not in {"xhr", "fetch", "document"}:
                return
            text = await resp.text()
            if text:
                captured_responses.append(text)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        await page.evaluate(
            """
            (branduid) => {
                const fakeEvent = {
                    pageX: 0, pageY: 0, clientX: 0, clientY: 0,
                    preventDefault: () => {}, stopPropagation: () => {}
                };
                if (typeof mk_prd_option_preview === "function") {
                    mk_prd_option_preview(Number(branduid), fakeEvent);
                }
            }
            """,
            branduid,
        )
    except Exception:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        return []

    await page.wait_for_timeout(500)

    dom_texts: list[str] = []
    candidate_selectors = [
        "#MK_opt_preview",
        f"#MK_opt_preview_{branduid}",
        ".mk_prd_option_list",
    ]

    for selector in candidate_selectors:
        try:
            nodes = page.locator(selector)
            count = await nodes.count()
            for i in range(min(count, 10)):
                node = nodes.nth(i)

                txt = await _safe_inner_text(node)
                if txt:
                    dom_texts.append(txt)

                html = await node.inner_html()
                if html:
                    dom_texts.append(html)

                li_nodes = node.locator("li, ul li, h3, .option-name")
                li_count = await li_nodes.count()
                for j in range(min(li_count, 100)):
                    t = await _safe_inner_text(li_nodes.nth(j))
                    if t:
                        dom_texts.append(t)
        except Exception:
            pass

    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass

    all_texts = dom_texts + captured_responses
    sizes: list[str] = []
    for blob in all_texts:
        sizes.extend(_extract_sizes_from_text_blob(blob))

    return _dedupe_keep_order(sizes)


async def _extract_sizes_in_browser_context(page: Page) -> list[str]:
    """
    상세 페이지 내부 JS 상태를 활용해서 사이즈를 직접 계산.
    - optionlist[] (PS)
    - spcode/spcode2 (NL)
    - 마지막 fallback으로 body 텍스트
    """
    try:
        raw = await page.evaluate(
            """
            () => {
                const out = [];

                const clean = (s) => (s || "").replace(/\\s+/g, " ").trim();
                const looksLikeSize = (s) => {
                    s = clean(s);
                    if (!s) return false;
                    const bad = ['옵션','선택','choose','필수','재고수량','무제한','품절','sold out','장바구니','바로구매','총 상품금액','색상'];
                    const lower = s.toLowerCase();
                    if (bad.some(x => lower.includes(x))) return false;
                    return (
                        /^\\d{3}$/.test(s) ||
                        /^\\d{2,3}mm$/i.test(s) ||
                        /^(US|UK|EU)\\s?\\d+(?:\\.\\d+)?$/i.test(s) ||
                        /^\\d{2,3}\\/\\d{2,3}$/.test(s)
                    );
                };

                // 1) PS 구조
                const selects = Array.from(document.querySelectorAll("select[name='optionlist[]']"));
                if (selects.length > 0) {
                    const mandatoryIdx = [];
                    selects.forEach((sel, idx) => {
                        if ((sel.getAttribute("mandatory") || "").toUpperCase() === "Y") {
                            mandatoryIdx.push(idx);
                        }
                    });

                    const idxs = mandatoryIdx.length ? mandatoryIdx : selects.map((_, idx) => idx);

                    if (idxs.length === 1) {
                        const sel = selects[idxs[0]];
                        Array.from(sel.options).forEach(opt => {
                            const text = clean(opt.getAttribute("origin") || opt.text || "");
                            const value = clean(opt.value || "");
                            if (value && looksLikeSize(text)) out.push(text);
                        });
                    } else if (idxs.length >= 2) {
                        const firstSel = selects[idxs[0]];
                        const lastSel = selects[idxs[idxs.length - 1]];

                        for (const opt of Array.from(firstSel.options)) {
                            const value = clean(opt.value || "");
                            const text = clean(opt.text || "");
                            if (!value || text.includes("선택") || text.includes("옵션")) continue;

                            firstSel.value = value;
                            firstSel.dispatchEvent(new Event("change", { bubbles: true }));

                            Array.from(lastSel.options).forEach(lastOpt => {
                                const t = clean(lastOpt.getAttribute("origin") || lastOpt.text || "");
                                const v = clean(lastOpt.value || "");
                                if (v && looksLikeSize(t)) out.push(t);
                            });
                        }
                    }
                }

                // 2) NL 구조
                const sp1 = document.querySelector("select[name='spcode']");
                const sp2 = document.querySelector("select[name='spcode2']");

                if (sp1 && sp2) {
                    for (const opt of Array.from(sp1.options)) {
                        const value = clean(opt.value || "");
                        const text = clean(opt.text || "");
                        if (!value || text.includes("선택") || text.includes("옵션")) continue;

                        sp1.value = value;
                        sp1.dispatchEvent(new Event("change", { bubbles: true }));

                        Array.from(sp2.options).forEach(opt2 => {
                            const t = clean(opt2.getAttribute("origin") || opt2.text || "");
                            const v = clean(opt2.value || "");
                            if (v && looksLikeSize(t)) out.push(t);
                        });
                    }
                } else if (sp1) {
                    Array.from(sp1.options).forEach(opt => {
                        const t = clean(opt.getAttribute("origin") || opt.text || "");
                        const v = clean(opt.value || "");
                        if (v && looksLikeSize(t)) out.push(t);
                    });
                } else if (sp2) {
                    Array.from(sp2.options).forEach(opt => {
                        const t = clean(opt.getAttribute("origin") || opt.text || "");
                        const v = clean(opt.value || "");
                        if (v && looksLikeSize(t)) out.push(t);
                    });
                }

                // 3) 최후 fallback
                if (out.length === 0) {
                    const body = clean(document.body ? document.body.innerText : "");
                    const tokens = body.match(/(?:US|UK|EU)\\s?\\d+(?:\\.\\d+)?|\\d{2,3}mm|\\b\\d{3}\\b|\\b\\d{2,3}\\/\\d{2,3}\\b/gi) || [];
                    tokens.forEach(t => { if (looksLikeSize(t)) out.push(clean(t)); });
                }

                return [...new Set(out)];
            }
            """
        )
        return _dedupe_keep_order(raw if isinstance(raw, list) else [])
    except Exception:
        return []


async def _collect_sizes_from_detail(
    context: BrowserContext,
    detail_url: str,
    semaphore: asyncio.Semaphore,
) -> list[str]:
    if not detail_url:
        return []

    async with semaphore:
        page = await context.new_page()
        await _block_unnecessary_resources(page)

        try:
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(500)
            return await _extract_sizes_in_browser_context(page)
        except Exception:
            return []
        finally:
            await page.close()


async def _page_has_next(page: Page, current_page_no: int) -> bool:
    pager_links = page.locator("a[href*='pagemove(']")
    count = await pager_links.count()

    for i in range(count):
        href = await _safe_attr(pager_links.nth(i), "href")
        page_no = _extract_page_no_from_href(href)
        if page_no is not None and page_no > current_page_no:
            return True
    return False


async def _collect_products_from_page(
    page: Page,
    min_price: int,
    max_price: int,
) -> list[dict[str, Any]]:
    rows = page.locator("tr").filter(has=page.locator("font.brandbrandname"))
    row_count = await rows.count()

    products: list[dict[str, Any]] = []

    for i in range(row_count):
        row = rows.nth(i)

        name = await _safe_inner_text(row.locator("font.brandbrandname").first)
        if not name:
            continue

        price_text = await _safe_inner_text(
            row.locator("td.brandprice .mk_price").first
        )
        if not price_text:
            price_text = await _safe_inner_text(row.locator("td.brandprice").first)

        price = _parse_price(price_text)
        if price is None or not (min_price <= price <= max_price):
            continue

        detail_href = ""
        preview_onclick = ""

        anchors = row.locator("a")
        a_count = await anchors.count()
        for j in range(a_count):
            a = anchors.nth(j)
            href = await _safe_attr(a, "href")
            onclick = await _safe_attr(a, "onclick")

            if "shopdetail.html?branduid=" in href and not detail_href:
                detail_href = href
            if "mk_prd_option_preview(" in onclick and not preview_onclick:
                preview_onclick = onclick

        detail_url = urljoin(BASE_URL, detail_href) if detail_href else ""
        branduid = _extract_branduid(preview_onclick) or _extract_branduid(detail_href)

        image_url = ""
        imgs = row.locator("img")
        img_count = await imgs.count()
        for j in range(img_count):
            src = await _safe_attr(imgs.nth(j), "src")
            if "/shopimages/" in src:
                image_url = _normalize_url(src)
                break

        preview_sizes = await _collect_preview_sizes(page, branduid)

        products.append(
            {
                "product_name": name,
                "product_price": price,
                "sizes": preview_sizes,
                "image_url": image_url,
                "detail_url": detail_url,
                "branduid": branduid,
            }
        )

    return products


async def redsoccer_crawl(
    product_keyword: str,
    min_price: int,
    max_price: int,
    max_concurrency: int = 6,
) -> list[dict[str, Any]]:
    if min_price > max_price:
        raise ValueError("min_price는 max_price보다 클 수 없습니다.")
    if max_concurrency < 1:
        raise ValueError("max_concurrency는 1 이상이어야 합니다.")

    encoded_keyword = quote_plus(product_keyword, encoding="euc-kr", errors="ignore")

    def build_url(page_no: int) -> str:
        return (
            f"{BASE_URL}{SEARCH_PATH}"
            f"?search={encoded_keyword}"
            f"&page={page_no}"
            f"&sort="
            f"&money1={min_price}"
            f"&money2={max_price}"
            f"&prize1=&company1=&content1=&brcode=&code="
        )

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
        await _block_unnecessary_resources(page)

        try:
            all_products: list[dict[str, Any]] = []
            page_no = 1
            visited_detail_keys = set()

            while True:
                await page.goto(
                    build_url(page_no), wait_until="domcontentloaded", timeout=20000
                )
                await page.wait_for_timeout(400)

                page_products = await _collect_products_from_page(
                    page=page,
                    min_price=min_price,
                    max_price=max_price,
                )

                if not page_products:
                    break

                added_on_this_page = 0
                for product in page_products:
                    key = (
                        product["detail_url"]
                        or product["branduid"]
                        or (
                            product["product_name"],
                            product["product_price"],
                        )
                    )
                    if key in visited_detail_keys:
                        continue
                    visited_detail_keys.add(key)
                    all_products.append(product)
                    added_on_this_page += 1

                has_next = await _page_has_next(page, page_no)

                # 다음 페이지가 없으면 종료
                if not has_next:
                    break

                # 다음 페이지가 있다고 적혀 있는데 새 상품이 하나도 추가 안 되면 무한루프 방지
                if added_on_this_page == 0:
                    break

                page_no += 1

            # preview에서 못 잡은 상품만 상세페이지 fallback 병렬 처리
            semaphore = asyncio.Semaphore(max_concurrency)
            tasks = []
            idxs = []

            for idx, product in enumerate(all_products):
                if product["sizes"]:
                    continue
                if not product["detail_url"]:
                    continue
                idxs.append(idx)
                tasks.append(
                    _collect_sizes_from_detail(
                        context=context,
                        detail_url=product["detail_url"],
                        semaphore=semaphore,
                    )
                )

            if tasks:
                detail_sizes = await asyncio.gather(*tasks, return_exceptions=True)
                for idx, result in zip(idxs, detail_sizes):
                    if not isinstance(result, Exception) and result:
                        all_products[idx]["sizes"] = result

            return all_products

        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    data = asyncio.run(
        redsoccer_crawl(
            product_keyword="나이키 머큐리얼 베이퍼",
            min_price=100000,
            max_price=250000,
            max_concurrency=6,
        )
    )

    from pprint import pprint

    pprint(data)

# 해결해야할 사항
## 레드사커 -> 2페이지에도 상품이 존재하는데 해당 페이지에서 상품 데이터 수집 안함 / 사이즈 데이터 수집 안함
