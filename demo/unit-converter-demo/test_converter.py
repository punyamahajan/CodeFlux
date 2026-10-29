import io
import unittest
from contextlib import redirect_stdout

from cli import main
from converter import convert, convert_length, convert_temperature, convert_weight


class ConverterTest(unittest.TestCase):
    def test_length(self):
        self.assertAlmostEqual(convert_length(10, "m", "km"), 0.01)
        self.assertAlmostEqual(convert_length(10, "km", "mi"), 6.21371, places=5)
        self.assertAlmostEqual(convert_length(1, "mi", "m"), 1609.344)

    def test_weight(self):
        self.assertAlmostEqual(convert_weight(10, "g", "kg"), 0.01)
        self.assertAlmostEqual(convert_weight(10, "kg", "lb"), 22.04623, places=5)
        self.assertAlmostEqual(convert_weight(1, "lb", "g"), 453.59237)

    def test_temperature(self):
        self.assertAlmostEqual(convert_temperature(10, "C", "F"), 50)
        self.assertAlmostEqual(convert_temperature(10, "F", "C"), -12.22222, places=5)
        self.assertAlmostEqual(convert_temperature(0, "C", "K"), 273.15)
        self.assertAlmostEqual(convert_temperature(212, "F", "K"), 373.15)

    def test_same_unit_is_unchanged(self):
        self.assertEqual(convert(5, "kg", "kg"), 5)

    def test_unknown_or_mixed_units_raise(self):
        for args in [(10, "x", "km"), (10, "km", "kg"), (10, "C", "lb")]:
            with self.assertRaises(ValueError):
                convert(*args)


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(list(args))
        return code, output.getvalue().strip()

    def test_converts(self):
        self.assertEqual(self.run_cli("10", "km", "mi"), (0, "10 km = 6.214 mi"))

    def test_bad_input(self):
        self.assertEqual(self.run_cli("10", "km")[0], 2)
        self.assertEqual(self.run_cli("ten", "km", "mi")[0], 1)
        self.assertEqual(self.run_cli("10", "km", "kg")[0], 1)


if __name__ == "__main__":
    unittest.main()
