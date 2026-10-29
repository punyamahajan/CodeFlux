import unittest
from expenses import ExpenseManager

class TestExpenseManager(unittest.TestCase):
    def test_add_expense(self):
        expense_manager = ExpenseManager()
        initial_count = len(expense_manager.expenses)
        expense_manager.add_expense(100, "Groceries")
        self.assertEqual(len(expense_manager.expenses), initial_count + 1)

    def test_get_expenses(self):
        expense_manager = ExpenseManager()
        expense_manager.add_expense(100, "Groceries")
        expenses = expense_manager.get_expenses()
        self.assertEqual(len(expenses), 1)
        self.assertEqual(expenses[0], {"amount": 100, "category": "Groceries"})

if __name__ == '__main__':
    unittest.main()
