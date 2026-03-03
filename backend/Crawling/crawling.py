from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import copy
import os
import re
import threading
import time


DEFAULT_WAIT_SECONDS = float(os.getenv("CRAWL_DEFAULT_WAIT_SECONDS", "1.2"))
CACHE_TTL_SECONDS = int(os.getenv("CRAWL_CACHE_TTL_SECONDS", "300"))
_CRAWL_CACHE: dict[tuple[str, str, int, int], dict] = {}
_DRIVER_PATH: str | None = None
_DRIVER_PATH_LOCK = threading.Lock()


def get_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("window-size=1920x1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
    )
    options.add_experimental_option(
        "excludeSwitches", ["enable-logging", "enable-automation"]
    )
    options.add_experimental_option("useAutomationExtension", False)

    global _DRIVER_PATH
    if _DRIVER_PATH is None:
        # Avoid concurrent install calls when multiple crawl threads start together.
        with _DRIVER_PATH_LOCK:
            if _DRIVER_PATH is None:
                try:
                    _DRIVER_PATH = ChromeDriverManager().install()
                except Exception:
                    _DRIVER_PATH = ""

    if _DRIVER_PATH:
        return webdriver.Chrome(service=Service(_DRIVER_PATH), options=options)
    return webdriver.Chrome(options=options)


def _cached_site_call(
    site_name: str, site_fetcher, product_keyword: str, min_price: int, max_price: int
):
    key = (site_name, product_keyword.strip().lower(), int(min_price), int(max_price))
    now = time.time()
    cached = _CRAWL_CACHE.get(key)
    if cached and now - cached["ts"] < CACHE_TTL_SECONDS:
        return copy.deepcopy(cached["data"])

    data = site_fetcher(product_keyword, min_price, max_price)
    _CRAWL_CACHE[key] = {"ts": now, "data": data}
    return copy.deepcopy(data)


def _normalize_price_to_int(raw_price: str | None):
    if not raw_price:
        return None
    digits = re.sub(r"[^\d]", "", raw_price)
    return int(digits) if digits else None


def _build_product_info(name: str, price: str | None):
    return f"{name} | {price}" if price else name


def _abs_url(base: str, maybe_relative: str | None):
    if not maybe_relative:
        return None
    if maybe_relative.startswith("http://") or maybe_relative.startswith("https://"):
        return maybe_relative
    if maybe_relative.startswith("//"):
        return f"https:{maybe_relative}"
    if maybe_relative.startswith("/"):
        return f"{base}{maybe_relative}"
    return f"{base}/{maybe_relative}"


def crazy11_info(product_keyword: str, min_price: int, max_price: int):
    driver = get_driver()
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    products = []
    try:
        driver.get("https://www.crazy11.co.kr/")
        search_input = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@type='text' or @name='search' or @name='keyword']")
            )
        )
        search_input.send_keys(product_keyword)
        search_input.send_keys(Keys.RETURN)

        min_box = wait.until(EC.presence_of_element_located((By.NAME, "money1")))
        max_box = wait.until(EC.presence_of_element_located((By.NAME, "money2")))
        min_box.clear()
        min_box.send_keys(min_price)
        max_box.clear()
        max_box.send_keys(max_price)

        search_button = wait.until(
            EC.element_to_be_clickable((By.CLASS_NAME, "search__box-result-btn"))
        )
        search_button.click()

        product_boxes = wait.until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "itemsList__item"))
        )
        for box in product_boxes:
            try:
                product_info = box.find_element(
                    By.CLASS_NAME, "itemInfo-area"
                ).text.strip()
                link = box.find_element(By.TAG_NAME, "a").get_attribute("href")
                img_elem = box.find_element(By.TAG_NAME, "img")
                img = (
                    img_elem.get_attribute("src")
                    or img_elem.get_attribute("data-src")
                    or img_elem.get_attribute("data-original")
                )
                img = _abs_url("https://www.crazy11.co.kr", img)
                products.append(
                    {
                        "product_info": product_info,
                        "product_size": None,
                        "product_url": link,
                        "product_image": img,
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    finally:
        driver.quit()
    return products


def redsoccer_info(product_keyword: str, min_price: int, max_price: int):
    driver = get_driver()
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    products = []
    try:
        driver.get("https://www.redsoccer.co.kr/")
        search_input = wait.until(EC.presence_of_element_located((By.NAME, "search")))
        search_input.send_keys(product_keyword)
        search_input.send_keys(Keys.RETURN)

        min_box = wait.until(EC.presence_of_element_located((By.NAME, "money1")))
        max_box = wait.until(EC.presence_of_element_located((By.NAME, "money2")))
        min_box.clear()
        min_box.send_keys(min_price)
        max_box.clear()
        max_box.send_keys(max_price)

        search_button = wait.until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    '//*[@id="mk_center"]/form/table[1]/tbody/tr[7]/td/table/tbody/tr[1]/td[2]/table/tbody/tr/td[4]/a',
                )
            )
        )
        search_button.send_keys(Keys.ENTER)

        tr_elems = wait.until(
            EC.presence_of_all_elements_located(
                (By.XPATH, '//*[@id="mk_search_production"]/tbody/tr')
            )
        )

        for tr in tr_elems:
            try:
                name_font = tr.find_elements(By.CSS_SELECTOR, "font.brandbrandname")
                if not name_font:
                    continue
                name = name_font[0].text.strip()
                price_elem = tr.find_elements(By.CSS_SELECTOR, "span.mk_price")
                price = price_elem[0].text.strip() if price_elem else None
                product_info = _build_product_info(name, price)

                img_elem = tr.find_elements(By.CSS_SELECTOR, "img[src*='shopimages/']")
                image_url = img_elem[0].get_attribute("src") if img_elem else None
                image_url = _abs_url("https://www.redsoccer.co.kr", image_url)

                a_elem = tr.find_elements(By.CSS_SELECTOR, "a[href*='shopdetail.html']")
                product_url = a_elem[0].get_attribute("href") if a_elem else None
                product_url = _abs_url("https://www.redsoccer.co.kr", product_url)

                products.append(
                    {
                        "product_info": product_info,
                        "product_size": None,
                        "product_url": product_url,
                        "product_image": image_url,
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    finally:
        driver.quit()
    unique = {
        f"{p.get('product_info')}|{p.get('product_url')}": p for p in products
    }.values()
    return list(unique)


def soccerboom_info(product_keyword: str, min_price: int, max_price: int):
    driver = get_driver()
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    products = []
    try:
        driver.get("https://soccerboom.co.kr/")

        search_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input#keyword"))
        )
        search_box.send_keys(product_keyword)
        search_box.send_keys(Keys.RETURN)

        try:
            min_box = wait.until(
                EC.presence_of_element_located((By.NAME, "product_price1"))
            )
            max_box = wait.until(
                EC.presence_of_element_located((By.NAME, "product_price2"))
            )
            min_box.clear()
            min_box.send_keys(min_price)
            max_box.clear()
            max_box.send_keys(max_price)
            driver.find_element(
                By.CSS_SELECTOR, "#searchForm input[type=image]"
            ).click()
        except Exception:
            pass

        items = wait.until(
            EC.presence_of_all_elements_located(
                (By.CSS_SELECTOR, "ul.prdList > li.xans-record-")
            )
        )
        for li in items:
            try:
                name = li.find_element(By.CLASS_NAME, "name").text.strip()
                desc = li.find_element(By.CSS_SELECTOR, "div.description")
                sale_price = desc.get_attribute("data-sale_price")
                product_info = _build_product_info(name, sale_price)

                img_src = li.find_element(
                    By.CSS_SELECTOR, "div.thumbnail img"
                ).get_attribute("src")
                image_url = _abs_url("https://soccerboom.co.kr", img_src)
                href = li.find_element(
                    By.CSS_SELECTOR, "div.thumbnail a"
                ).get_attribute("href")
                product_url = _abs_url("https://soccerboom.co.kr", href)

                products.append(
                    {
                        "product_info": product_info,
                        "product_size": None,
                        "product_url": product_url,
                        "product_image": image_url,
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    finally:
        driver.quit()
    return products


def cafo_info(product_keyword: str, min_price: int, max_price: int):
    driver = get_driver()
    wait = WebDriverWait(driver, DEFAULT_WAIT_SECONDS)
    results = []

    try:
        driver.get("https://capostore.co.kr/")

        search_input = wait.until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='keyword']"))
        )
        search_input.send_keys(product_keyword)
        search_input.send_keys(Keys.RETURN)

        product_boxes = wait.until(
            EC.presence_of_all_elements_located((By.CLASS_NAME, "item_cont"))
        )
        for box in product_boxes:
            try:
                name = box.find_element(
                    By.CSS_SELECTOR, "strong.item_name"
                ).text.strip()
                price = box.find_element(
                    By.CSS_SELECTOR, "strong.item_price span"
                ).text.strip()
                parsed_price = _normalize_price_to_int(price)
                if parsed_price is not None and not (
                    min_price <= parsed_price <= max_price
                ):
                    continue

                href = box.find_element(
                    By.CSS_SELECTOR, "div.item_photo_box a"
                ).get_attribute("href")
                product_url = _abs_url(
                    "https://capostore.co.kr", href.replace("../", "")
                )
                img_src = box.find_element(
                    By.CSS_SELECTOR, "div.item_photo_box img"
                ).get_attribute("src")
                product_image = _abs_url("https://capostore.co.kr", img_src)

                size_tags = box.find_elements(By.CSS_SELECTOR, "div.list_options span")
                size_list = [s.text.strip() for s in size_tags if s.text.strip()]
                product_size = ", ".join(size_list) if size_list else None

                results.append(
                    {
                        "product_info": _build_product_info(name, price),
                        "product_size": product_size,
                        "product_url": product_url,
                        "product_image": product_image,
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    finally:
        driver.quit()
    return results


def crawl_info(site_keyword: str, product_keyword: str, min_price: int, max_price: int):
    normalized = site_keyword.strip().lower()

    crazy11_aliases = {"crazy11", "crazy 11", "크레이지11", "크레이지 11"}
    redsoccer_aliases = {"redsoccer", "레드사커"}
    soccerboom_aliases = {"soccerboom", "사커붐"}
    cafostore_aliases = {
        "cafostore",
        "cafofootball store",
        "카포스토어",
        "카포풋볼스토어",
    }

    if normalized in crazy11_aliases:
        return _cached_site_call(
            "crazy11", crazy11_info, product_keyword, min_price, max_price
        )
    if normalized in redsoccer_aliases:
        return _cached_site_call(
            "redsoccer", redsoccer_info, product_keyword, min_price, max_price
        )
    if normalized in soccerboom_aliases:
        return _cached_site_call(
            "soccerboom", soccerboom_info, product_keyword, min_price, max_price
        )
    if normalized in cafostore_aliases:
        return _cached_site_call(
            "cafostore", cafo_info, product_keyword, min_price, max_price
        )

    raise ValueError(f"지원하지 않는 판매자입니다: {site_keyword}")
