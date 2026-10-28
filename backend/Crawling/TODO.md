# TODO - Crawling

## 진행 중
- [ ] 

## 버그
- [ ] 

## 예정
- [ ] 

## 완료
- [x] 통합 크롤러 출력 정규화에서 `product_price=None`/빈 `product_url`이 유효한 `price`/`detail_url`
  fallback을 막던 문제 수정. null 이름·사이즈·이미지 필드도 공통 빈 값으로 정규화하고
  `Test/test_crawler_normalization.py` 회귀 테스트 추가.
- [x] 레드사커 사이즈 파싱 오염 버그 수정 (실사용 재현: 제품 비교 카드 사이즈 목록에 139, 143, 155,
  159, 169 같은 비정상 값이 250~295 정상 사이즈와 함께 노출 — 크레이지11/카포스토어에는 없고 레드사커만
  발생). 근본 원인: `redsoccer_test.py`의 `_looks_like_size`가 순수 3자리 숫자를 범위 제한 없이
  전부 사이즈로 인정(`^\d{3}$`)해, 상세 페이지 텍스트/XHR 응답에 섞인 상품코드 조각·리뷰 수 같은
  무관한 3자리 숫자까지 사이즈로 오인식함. Python 쪽(`_looks_like_size`)과 브라우저 컨텍스트에서
  동일 로직을 그대로 복제해 쓰는 JS(`_extract_sizes_in_browser_context` 내부 `looksLikeSize`) 양쪽에
  신발 사이즈로 말이 되는 범위(200~330mm) 제한 추가. 회귀 테스트:
  `Test/test_redsoccer_size_extraction.py`.
