import unittest

from utils.validators import MIN_FIO_LEN, validate_min_plaintext, validate_phone


class ValidatorsTests(unittest.TestCase):
    def test_min_plaintext(self):
        self.assertFalse(validate_min_plaintext("  ab  ", min_len=MIN_FIO_LEN))
        self.assertTrue(validate_min_plaintext("  Абылай Абылайұлы  ", min_len=MIN_FIO_LEN))

    def test_phone_unchanged(self):
        self.assertTrue(validate_phone("+77071234567"))


if __name__ == "__main__":
    unittest.main()
