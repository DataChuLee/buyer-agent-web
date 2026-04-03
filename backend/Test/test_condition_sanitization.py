import os
import sys
import unittest


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from Tools.condition_sanitization import sanitize_condition_map, sanitize_optional_text


class ConditionSanitizationTest(unittest.TestCase):
    def test_sanitize_optional_text_drops_null_like_strings(self):
        self.assertIsNone(sanitize_optional_text("None"))
        self.assertIsNone(sanitize_optional_text(" null "))

    def test_sanitize_condition_map_drops_null_like_values(self):
        sanitized = sanitize_condition_map(
            {
                "seller": "카포스토어",
                "age_group": "None",
                "surface": "TF",
                "position": "null",
            }
        )
        self.assertEqual(
            sanitized,
            {
                "seller": "카포스토어",
                "surface": "TF",
            },
        )


if __name__ == "__main__":
    unittest.main()
