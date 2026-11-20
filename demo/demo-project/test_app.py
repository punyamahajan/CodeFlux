import unittest
from app import calculate_balance

class TestExpenseTracker(unittest.TestCase):
    def test_calculate_balance_empty(self):
        self.assertEqual(calculate_balance([]), 0.0)

    def test_calculate_balance_positive(self):
        expenses = [{"description": "test", "amount": 100.0}, {"description": "test2", "amount": 50.0}]
        self.assertEqual(calculate_balance(expenses), 150.0)

    def test_calculate_balance_mixed(self):
        expenses = [
            {"description": "salary", "amount": 1000.0},
            {"description": "rent", "amount": -500.0},
            {"description": "food", "amount": -100.0}
        ]
        self.assertEqual(calculate_balance(expenses), 400.0)

if __name__ == "__main__":
    unittest.main()
