import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from Tools.seller_normalization import (
    find_seller_displays_in_query,
    normalize_seller_crawler,
    normalize_seller_display,
    replace_seller_aliases_in_query,
)


class SellerNormalizationTest(unittest.TestCase):
    def test_display_name_collapses_space_variant(self):
        self.assertEqual(normalize_seller_display("크레이지 11"), "크레이지11")

    def test_crawler_key_collapses_space_variant(self):
        self.assertEqual(normalize_seller_crawler("크레이지 11"), "crazy11")

    def test_query_aliases_are_rewritten_to_canonical_display(self):
        query = "크레이지 11에서 머큐리얼 베이퍼 성인용 TF 10만원대 비교해줘"
        normalized = replace_seller_aliases_in_query(query)
        self.assertIn("크레이지11에서", normalized)
        self.assertNotIn("크레이지 11", normalized)

    def test_query_seller_detection_uses_canonical_display(self):
        sellers = find_seller_displays_in_query(
            "크레이지 11과 사커붐에서 머큐리얼 베이퍼 비교해줘"
        )
        self.assertEqual(sellers, ["크레이지11", "사커붐"])


if __name__ == "__main__":
    unittest.main()
