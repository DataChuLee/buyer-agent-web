import os
import sys
import unittest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from Crawling.redsoccer_test import _extract_sizes_from_text_blob, _looks_like_size


class RedsoccerSizeExtractionTest(unittest.TestCase):
    def test_rejects_three_digit_numbers_outside_shoe_size_range(self):
        # 회귀: 상세 페이지 텍스트/XHR 응답에 섞인 무관한 3자리 숫자(상품코드 조각, 리뷰 수 등)가
        # 신발 사이즈로 오인식되던 문제(실사용 재현: 139/143/155/159/169가 정상 사이즈와 함께 노출).
        for bogus in ["139", "143", "155", "159", "169", "999", "001"]:
            self.assertFalse(_looks_like_size(bogus), f"{bogus} should not look like a shoe size")

    def test_accepts_realistic_shoe_sizes(self):
        for real in ["220", "250", "265", "295", "305"]:
            self.assertTrue(_looks_like_size(real), f"{real} should look like a shoe size")

    def test_extract_sizes_from_text_blob_filters_out_noise(self):
        blob = "사이즈: 250 255 260 265 (상품리뷰:139개) 코드 IM5811-001 재고수량 무제한"
        sizes = _extract_sizes_from_text_blob(blob)

        self.assertEqual(sizes, ["250", "255", "260", "265"])
        self.assertNotIn("139", sizes)


if __name__ == "__main__":
    unittest.main()
