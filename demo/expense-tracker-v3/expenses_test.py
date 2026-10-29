import unittest
from expenses import ExpenseManager

class TestExpenseManager(unittest.TestCase):
    def test_load_expenses(self):
        expense_manager = ExpenseManager()
        self.assertNotEqual(len(expense_manager.expenses), 0)

    def test_add_expense(self):
        expense_manager = ExpenseManager()
        initial_count = len(expense_manager.expenses)
        expense_manager.add_expense(100, "Groceries")
        self.assertEqual(len(expense_manager.expenses), initial_count + 1)

    def test_get_expenses(self):
        expense_manager = ExpenseManager()
        expenses = expense_manager.get_expenses()
        self.assertNotEqual(len(expenses), 0)

if __name__ == '__main__':
    unittest.main()
