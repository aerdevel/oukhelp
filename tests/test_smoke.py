import unittest

from core.resources.text_file.catalog import SPECIALTIES
from core.resources.text_file.pricing import BASE_TUITION_YEAR, DISCOUNTS
from services.calculator import calculate_tuition
from utils.validators import format_phone, validate_phone


class SmokeTests(unittest.TestCase):
    def test_catalog_not_empty(self):
        self.assertTrue(SPECIALTIES["ru"])
        self.assertTrue(SPECIALTIES["kz"])

    def test_calculator_discount(self):
        _, rate = DISCOUNTS["ru"]["unt_50"]
        year_price, total_price = calculate_tuition(BASE_TUITION_YEAR, rate)
        self.assertEqual(year_price, 405000)
        self.assertEqual(total_price, 1620000)

    def test_phone_validation_and_format(self):
        self.assertTrue(validate_phone("+77071234567"))
        self.assertEqual(format_phone("87071234567"), "+77071234567")


if __name__ == "__main__":
    unittest.main()
