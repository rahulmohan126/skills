import unittest
from timekit.fmt import format_duration


class FormatDurationTests(unittest.TestCase):
    def test_hours_minutes(self):
        self.assertEqual(format_duration(5400), "1h30m")

    def test_zero(self):
        self.assertEqual(format_duration(0), "0s")

    def test_negative(self):
        with self.assertRaises(ValueError):
            format_duration(-1)


if __name__ == "__main__":
    unittest.main()
