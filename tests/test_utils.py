import unittest

from utils.datetime_utils import parse_iso_utc
from utils.privacy import mask_phone, mask_username


class UtilsTests(unittest.TestCase):
    def test_parse_iso_utc_valid(self):
        value = parse_iso_utc("2026-04-27T12:00:00+00:00")
        self.assertIsNotNone(value)
        self.assertEqual(value.year, 2026)

    def test_parse_iso_utc_invalid(self):
        self.assertIsNone(parse_iso_utc("not-a-date"))

    def test_mask_phone(self):
        self.assertEqual(mask_phone("+77071234567"), "+7***4567")

    def test_mask_username(self):
        self.assertEqual(mask_username("@abcdef"), "@ab***")


if __name__ == "__main__":
    unittest.main()
