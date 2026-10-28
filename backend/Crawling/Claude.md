# Crawling 폴더

## 역할
쇼핑몰 셀러 사이트 크롤링. 상품 정보 수집 후 Tools/crawl_and_index.py로 ChromaDB에 인덱싱.

## 주요 파일
- `crawler_result.csv` → 크롤링 결과 샘플 데이터

## 판매처별 크롤러 (`Tools/crawl_and_index.py`가 `seller_total_test.crawl_multiple_sellers`로 호출)
- `cafostore_test.py`
- `crazy11_test.py`
- `redsoccer_test.py`
- `soccerboom_test.py`
- `seller_total_test.py`

## 크롤링 대상 셀러
cafostore, crazy11, redsoccer, soccerboom 등 축구용품 쇼핑몰

## 의존성
- Playwright, Selenium, BeautifulSoup4
- Firecrawl (API 기반 크롤링)
- `Tools/crawl_and_index.py`: 크롤링 결과 인덱싱
