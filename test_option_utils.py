import unittest

from option_utils import select_nearby_strikes, to_float, to_int


class TestOptionUtils(unittest.TestCase):
    def test_numeric_conversions_tolerate_blank_values(self):
        self.assertEqual(to_float(""), 0.0)
        self.assertEqual(to_float(None, 1.5), 1.5)
        self.assertEqual(to_float(float("nan"), 2.5), 2.5)
        self.assertEqual(to_int("12.0"), 12)
        self.assertEqual(to_int("not-a-number", 7), 7)

    def test_select_nearby_strikes_ignores_invalid_strikes(self):
        chain = [
            {"strike": "90"},
            {"strike": "95"},
            {"strike": "100"},
            {"strike": "105"},
            {"strike": ""},
        ]

        selected = select_nearby_strikes(chain, 100, 1)

        self.assertEqual([item["strike"] for item in selected], ["95", "100"])


if __name__ == "__main__":
    unittest.main()
