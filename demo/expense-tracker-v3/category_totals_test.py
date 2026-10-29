import unittest
from category_totals import render_category_totals
from unittest.mock import MagicMock, patch
from expenses import ExpenseManager

class TestCategoryTotals(unittest.TestCase):
    def test_render_category_totals(self):
        expenses = [
            {"amount": 100, "category": "Groceries"},
            {"amount": 50, "category": "Utilities"}
        ]
        with patch('streamlit.write') as mock_write:
            render_category_totals(expenses)
            mock_write.assert_any_call("Groceries: $100.00")
            mock_write.assert_any_call("Utilities: $50.00")

if __name__ == '__main__':
    unittest.main()
