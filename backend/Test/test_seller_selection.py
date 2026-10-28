import unittest

from Tools.seller_selection import (
    parse_seller_price,
    select_cheapest_seller,
    select_cheapest_seller_from_markdown,
    validate_seller_candidate,
)


def candidate(seller="crazy11", price=109000, **overrides):
    domains = {
        "crazy11": "crazy11.co.kr",
        "soccerboom": "soccerboom.co.kr",
        "redsoccer": "redsoccer.co.kr",
        "capostore": "capostore.co.kr",
    }
    row = {
        "seller": seller,
        "product_name": "나이키 머큐리얼 베이퍼 16 아카데미",
        "product_url": f"https://{domains[seller]}/product/1",
        "sale_price": price,
        "original_price": 159000,
        "availability": "판매 중",
        "product_match": True,
        "source": "test",
    }
    row.update(overrides)
    return row


class SellerSelectionTests(unittest.TestCase):
    def test_sale_price_wins_over_original_price(self):
        result = select_cheapest_seller([
            candidate("crazy11", 99000, original_price=150000),
            candidate("soccerboom", None, original_price=105000),
        ])
        self.assertEqual("크레이지11", result["selected"]["seller"])
        self.assertEqual(99000, result["selected"]["effective_price"])

    def test_original_price_is_safe_fallback(self):
        normalized, reason = validate_seller_candidate(candidate(price=None, original_price="₩ 109,000"))
        self.assertIsNone(reason)
        self.assertEqual(109000, normalized["effective_price"])

    def test_price_parser_handles_spacing_and_rejects_implausible_values(self):
        self.assertEqual(109000, parse_seller_price(" ￦ 109,000 원 "))
        self.assertEqual(109000, parse_seller_price("109 000원"))
        self.assertIsNone(parse_seller_price("가격 문의"))
        self.assertIsNone(parse_seller_price("9,900원"))

    def test_invalid_candidates_are_never_selected(self):
        rows = [
            None,
            candidate(price=None, original_price=None),
            candidate(product_url=""),
            candidate(product_url="https://unsupported.example/item"),
            candidate(availability="품절"),
            candidate(product_match=False),
            candidate("soccerboom", 80000),
        ]
        result = select_cheapest_seller(rows, excluded_sellers=frozenset({"사커붐"}))
        self.assertEqual("no_results", result["status"])
        self.assertIsNone(result["selected"])
        for reason in ("unverified_price", "missing_url", "unsupported_seller", "unavailable", "product_mismatch", "excluded_seller"):
            self.assertEqual(1, result["rejection_summary"][reason])

    def test_equal_price_is_deterministic_by_seller_then_url(self):
        rows = [
            candidate("soccerboom", 99000, product_url="https://soccerboom.co.kr/z"),
            candidate("crazy11", 99000, product_url="https://crazy11.co.kr/z"),
            candidate("crazy11", 99000, product_url="https://crazy11.co.kr/a"),
        ]
        result = select_cheapest_seller(rows)
        self.assertEqual("https://soccerboom.co.kr/z", result["selected"]["product_url"])

    def test_legacy_markdown_uses_supported_url_and_no_arbitrary_default(self):
        answer = """
| 판매처 | 판매 여부 | 최저가 | 바로가기 |
|---|---|---|---|
| 크레이지11 | 판매 중 | 109,000원 | [방문](https://crazy11.co.kr/item/1) |
| 카포스토어 | 판매 중 | 101,400원 | [방문](https://capostore.co.kr/item/2) |
"""
        self.assertEqual("카포스토어", select_cheapest_seller_from_markdown(answer))
        self.assertIsNone(select_cheapest_seller_from_markdown("결과 없음", default="크레이지11"))


if __name__ == "__main__":
    unittest.main()
